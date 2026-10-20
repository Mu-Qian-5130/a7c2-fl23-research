"""Original sequence-creation and TRINITY-clear boundaries, never a device tool.

Uses synthetic state. Mutex and diagnostic calls are explicitly omitted; stops
before allocation, transport or clear/callback service execution. A constructed
request or callback descriptor does not prove capture cancellation or centering.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from trinity_replay import profile as mode_profile
from cp_metadata_replay import program


@lru_cache(maxsize=2)
def profile(directory):
    image, info, mode_entry, _, _ = mode_profile(directory)
    target = info['model'] == 'ILCE-7CM2'
    creator = image.qword(0x5578920 + 0x4bd * 8)
    code = image.instructions(creator, 0x2c)
    if not any(i.mnemonic == 'mov' and i.op_str == 'w1, #0x4bd' for i in code):
        raise ValueError('Original still-record factory does not select sequence 0x4bd')
    calls = [int(i.op_str.lstrip('#'), 16) for i in code if i.mnemonic == 'bl']
    branches = [int(i.op_str.lstrip('#'), 16) for i in code if i.mnemonic == 'b']
    if len(calls) != 1 or len(branches) != 1:
        raise ValueError('Unexpected still-record factory wrapper')
    getter = image.instructions(calls[0], 12)
    if [i.mnemonic for i in getter] != ['adrp', 'add', 'ret'] or not getter[0].op_str.startswith('x0, #') or not getter[1].op_str.startswith('x0, x0, #'):
        raise ValueError('Native sequence-manager getter changed')
    manager = int(getter[0].op_str.split('#')[1], 0) + int(getter[1].op_str.split('#')[1], 0)
    gate = 0x25018d4 if target else 0x2501a98
    allocator = 0x24a5c18 if target else 0x24a5ddc
    gate_code = image.instructions(gate, 0xb0)
    mutex = [int(i.op_str.lstrip('#'), 16) for i in gate_code if i.mnemonic == 'bl'][:2]
    if (len(mutex) != 2 or not any(i.mnemonic == 'ldrb' and i.op_str == 'w23, [x0, #0x608]' for i in gate_code)
            or not any(i.mnemonic == 'bl' and int(i.op_str.lstrip('#'), 16) == allocator for i in gate_code)):
        raise ValueError('Original sequence enqueue gate changed')
    clear = mode_entry - 0x6c
    if not any(i.mnemonic == 'mov' and i.op_str == 'w0, #0x40ef' for i in image.instructions(clear, 0x6c)):
        raise ValueError('Original TRINITY clear builder changed')
    data, cp_model, _, _ = program(directory)
    if cp_model != info['model']:
        raise ValueError('AP/CP model mismatch')
    return image, data, dict(model=info['model'], creator=creator, manager_getter=calls[0], manager_global=manager,
                             construct=branches[0], gate=gate, allocator=allocator,
                             mutex=mutex, clear=clear, send=int(info['send'], 16),
                             trace=int(info['trace'], 16),
                             cp_begin=0x359ede if target else 0x35a03e,
                             cp_stop=0x359f00 if target else 0x35a060,
                             cp_end=0x4757e9 if target else 0x475a01,
                             cp_end_label=0x475844 if target else 0x475a5c)


def a64_machine(image, regions, state_pages=()):
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
    from unicorn.arm64_const import UC_ARM64_REG_SP, UC_ARM64_REG_LR
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    pages = set()
    for begin, end in regions:
        pages.update(range(begin & ~4095, (end + 4095) & ~4095, 4096))
    for page in pages:
        off = image.offset(page, 4096)
        cpu.mem_map(page, 4096)
        cpu.mem_write(page, image.data[off:off + 4096])
    for page in state_pages:
        if page not in pages:
            cpu.mem_map(page, 4096)
    cpu.mem_map(0x10000000, 0x10000)
    cpu.reg_write(UC_ARM64_REG_SP, 0x1000f000)
    cpu.reg_write(UC_ARM64_REG_LR, 0x10003000)
    return cpu


def clear_packet(directory, capture_id):
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1,
                                     UC_ARM64_REG_X2, UC_ARM64_REG_PC, UC_ARM64_REG_LR)
    image, _, p = profile(directory)
    cpu = a64_machine(image, [(p['clear'], p['clear'] + 0x6c),
                             (p['send'], p['send'] + 4), (p['trace'], p['trace'] + 4)])
    args, output = 0x10001000, 0x10002000
    source = struct.pack('<I', capture_id) + b'\xa5' * 12
    cpu.mem_write(args, source)
    cpu.mem_write(output, b'\xa5' * 4)
    cpu.reg_write(UC_ARM64_REG_X0, args)
    cpu.reg_write(UC_ARM64_REG_X1, output)
    result = {'transport_executed': False, 'diagnostic_calls_omitted': 0}

    def hook(uc, pc, size, context):
        if pc == p['trace']:
            result['diagnostic_calls_omitted'] += 1
            uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))
        elif pc == p['send']:
            length = uc.reg_read(UC_ARM64_REG_X2)
            if length != 12:
                raise ValueError('Unexpected clear packet size')
            result.update(routing=uc.reg_read(UC_ARM64_REG_X0),
                          packet=bytes(uc.mem_read(uc.reg_read(UC_ARM64_REG_X1), length)).hex())
            uc.emu_stop()
        elif not p['clear'] <= pc < p['clear'] + 0x6c:
            raise ValueError('Unhandled clear builder call')

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.emu_start(p['clear'], 0x10003000, count=120)
    if 'packet' not in result or bytes(cpu.mem_read(args, 16)) != source or bytes(cpu.mem_read(output, 4)) != b'\xa5' * 4:
        raise ValueError('Clear builder changed inputs or missed the send boundary')
    return result


def creator_request(directory, flags):
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3
    image, _, p = profile(directory)
    cpu = a64_machine(image, [(p['creator'], p['creator'] + 0x2c),
                             (p['manager_getter'], p['manager_getter'] + 12),
                             (p['construct'], p['construct'] + 4)])
    descriptor = 0x10001000
    raw = struct.pack('<IIQ4I', 0x4bd, flags, 0x12345678, 11, 22, 33, 44)
    cpu.mem_write(descriptor, raw)
    cpu.reg_write(UC_ARM64_REG_X0, descriptor)
    result = {'construction_executed': False}

    def hook(uc, pc, size, context):
        if pc == p['construct']:
            if uc.reg_read(UC_ARM64_REG_X0) != p['manager_global']:
                raise ValueError('Factory did not use its original native manager')
            result.update(sequence_id=uc.reg_read(UC_ARM64_REG_X1), flags=uc.reg_read(UC_ARM64_REG_X3),
                          payload_is_native_record_field=uc.reg_read(UC_ARM64_REG_X2) == descriptor + 16,
                          native_manager_rva=hex(uc.reg_read(UC_ARM64_REG_X0)), native_manager_verified=True)
            uc.emu_stop()
        elif not (p['creator'] <= pc < p['creator'] + 0x2c or p['manager_getter'] <= pc < p['manager_getter'] + 12):
            raise ValueError('Unhandled factory call')

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.emu_start(p['creator'], 0x10003000, count=80)
    if 'sequence_id' not in result or bytes(cpu.mem_read(descriptor, len(raw))) != raw:
        raise ValueError('Factory wrapper changed the original request')
    return result


def enqueue_gate(directory, enabled, flags):
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1,
                                     UC_ARM64_REG_X2, UC_ARM64_REG_PC, UC_ARM64_REG_LR)
    image, _, p = profile(directory)
    cpu = a64_machine(image, [(p['gate'], p['gate'] + 0xb0), (p['allocator'], p['allocator'] + 4),
                             *[(target, target + 4) for target in p['mutex']]],
                      (0x7e4d000, 0x7e4e000))
    cpu.mem_write(0x7e4e608, bytes([enabled]))
    cpu.mem_write(0x10001000, b'\xa5' * 32)
    cpu.reg_write(UC_ARM64_REG_X0, 0x10001000)
    cpu.reg_write(UC_ARM64_REG_X1, flags)
    cpu.reg_write(UC_ARM64_REG_X2, 0x10002000)
    result = {'allocation_executed': False, 'queue_execution_tested': False, 'mutex_calls_omitted': 0}

    def hook(uc, pc, size, context):
        if pc in p['mutex']:
            result['mutex_calls_omitted'] += 1
            uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))
        elif pc == p['allocator']:
            result.update(boundary='request_allocation', flags=uc.reg_read(UC_ARM64_REG_X1),
                          payload_unchanged=uc.reg_read(UC_ARM64_REG_X0) == 0x10001000,
                          future_unchanged=uc.reg_read(UC_ARM64_REG_X2) == 0x10002000)
            uc.emu_stop()
        elif not p['gate'] <= pc < p['gate'] + 0xb0:
            raise ValueError('Unhandled gate path')

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.emu_start(p['gate'], 0x10003000, count=150)
    if not enabled:
        if cpu.reg_read(UC_ARM64_REG_PC) != 0x10003000 or 'boundary' in result:
            raise ValueError('Disabled gate did not return without request allocation')
        result['boundary'] = 'returned_without_request'
    elif result.get('boundary') != 'request_allocation':
        raise ValueError('Enabled gate missed the allocation boundary')
    if (bytes(cpu.mem_read(0x7e4e608, 1)) != bytes([enabled])
            or bytes(cpu.mem_read(0x10001000, 32)) != b'\xa5' * 32):
        raise ValueError('Gate changed synthetic state or input')
    return result


def cp_clear_descriptor(directory, context):
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_PC
    _, data, p = profile(directory)
    label = data[p['cp_end_label'] - 0x108000:]
    if not label.startswith(b'FW: TrinityShotEnd\0'):
        raise ValueError('Native clear completion callback label changed')
    cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    page = p['cp_begin'] & ~4095
    cpu.mem_map(page, 4096)
    cpu.mem_write(page, data[page - 0x108000:page - 0x108000 + 4096])
    cpu.mem_map(0x30000000, 0x10000)
    stack = 0x30008000
    cpu.mem_write(stack, b'\xa5' * 0x100)
    cpu.reg_write(UC_ARM_REG_SP, stack)
    cpu.reg_write(UC_ARM_REG_R0, context)

    def hook(uc, pc, size, unused):
        if pc == p['cp_stop']:
            uc.emu_stop()
        elif not p['cp_begin'] <= pc < p['cp_stop']:
            raise ValueError('Clear descriptor reached an unhandled function')

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.emu_start(p['cp_begin'] | 1, p['cp_stop'] + 4, count=60)
    if cpu.reg_read(UC_ARM_REG_PC) != p['cp_stop']:
        raise ValueError('Native clear descriptor missed its service boundary')
    record = struct.unpack('<5I', bytes(cpu.mem_read(stack + 4, 20)))
    if (record[2] != p['cp_end'] or record[1] or record[3] or record[4]
            or not record[0] & 1 or cpu.reg_read(UC_ARM_REG_R1) != stack + 4
            or cpu.reg_read(UC_ARM_REG_R0) != context or cpu.reg_read(UC_ARM_REG_R2) or cpu.reg_read(UC_ARM_REG_R3)):
        raise ValueError('Unexpected native clear callback descriptor')
    if bytes(cpu.mem_read(stack, 4)) != b'\xa5' * 4 or bytes(cpu.mem_read(stack + 24, 32)) != b'\xa5' * 32:
        raise ValueError('Native clear descriptor changed adjacent bytes')
    return {'record': [hex(value) for value in record], 'callback': 'TrinityShotEnd',
            'context_unchanged': True, 'service_executed': False, 'callback_executed': False,
            'centering_verified': False, 'begin_after_context_getter': True}


def compare(c2, reference):
    cases = []
    for capture_id in (0, 1, 0x12345678, 0xffffffff):
        a, b = clear_packet(c2, capture_id), clear_packet(reference, capture_id)
        expected = struct.pack('<BBHII', 5, 0, 0x40ef, capture_id, 0).hex()
        if a != b or a['packet'] != expected or a['routing'] != 0x90030001:
            raise ValueError('C2/A7CR clear packets differ')
        cases.append(dict(kind='clear_packet', capture_id=capture_id, target=a, reference=b))
    for enabled in (0, 1, 2, 255):
        for flags in (0, 1, 0x101):
            a, b = enqueue_gate(c2, enabled, flags), enqueue_gate(reference, enabled, flags)
            if a != b or (enabled and (a['flags'] != flags & 255 or not a['payload_unchanged'] or not a['future_unchanged'])):
                raise ValueError('C2/A7CR enqueue gates differ')
            cases.append(dict(kind='enqueue_gate', enabled=enabled, flags=flags, target=a, reference=b))
    for flags in (0, 1, 0x100, 0xdeadbeef):
        a, b = creator_request(c2, flags), creator_request(reference, flags)
        if ({k: v for k, v in a.items() if k != 'native_manager_rva'} != {k: v for k, v in b.items() if k != 'native_manager_rva'}
                or a['sequence_id'] != 0x4bd or a['flags'] != flags or not a['payload_is_native_record_field']):
            raise ValueError('C2/A7CR still-record creator requests differ')
        cases.append(dict(kind='creator_request', flags=flags, target=a, reference=b))
    for context in (0x30000100, 0x30000200):
        a, b = cp_clear_descriptor(c2, context), cp_clear_descriptor(reference, context)
        # Function addresses are model-specific; compare the audited layout/role,
        # not a guessed global relocation delta or unexecuted callback behavior.
        if {k: v for k, v in a.items() if k != 'record'} != {k: v for k, v in b.items() if k != 'record'}:
            raise ValueError('C2/A7CR clear descriptor layouts differ')
        cases.append(dict(kind='cp_clear_descriptor', context=context, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-lifecycle-replay/1', paired_cases=len(cases), cases=cases,
                camera_io=False, installable=False, physical_shift_verified=False, centering_verified=False,
                limit='Synthetic state; mutex/trace omissions; stop before construction, allocation, transport or clear service. No integrated boot, capture or actuator validation.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    report = compare(args.c2, args.reference)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != 'cases'}))


if __name__ == '__main__':
    main()
