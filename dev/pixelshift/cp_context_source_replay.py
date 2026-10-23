"""Bind original copied register handles to the native input-source consumer.

Original interface-bank copy and complete context binding execute before the
existing register-to-snapshot replay, in the same RAM. Source handles, unused
auxiliary pointers, register words/mappings and invocation order are fixtures.
This executes neither backend construction nor normal startup, full pipeline
dispatch, actual MMIO, sensor position, settling or exposure. Native handle
copying is not a device response. No host writes the consumed child pointer or
the destination register-base words.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_input_source_replay import profile as source_profile, replay as source_replay
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, s = source_profile(directory)
    delta = s['select']-0xb3bff2
    p = dict(copy=0xb26dce+delta, bind=0xb2e73e+delta,
             core_bind=0xb2ea2c+delta, bank_offset=0x209c, child_offset=0xe18)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    code = list(md.disasm(data[p['bind']-0x108000:p['bind']-0x108000+16], p['bind']))
    calls = [int(row.op_str.lstrip('#'), 0) for row in code if row.mnemonic == 'bl']
    if calls != [p['core_bind']]:
        raise ValueError('Original context initializer no longer calls its complete core binder')
    # The actual constructor store and its original vtable/RTTI distinguish
    # the read and configuration interfaces. Names alone do not identify
    # physical units or prove a sensor-position feedback peripheral.
    p['interface_types'] = {}
    for name, constructor, slot in (('reader', 0xb128c6+delta, 0x80),
                                    ('configuration', 0xb122fa+delta, 0x100)):
        start = constructor+0xe8
        block = list(md.disasm(data[start-0x108000:start-0x108000+0x24], start))
        tables = [value+8 for reg, value in literals(block) if reg == 'r1']
        if (len(tables) != 1 or not any(row.mnemonic == 'strd'
                and row.op_str == f'r1, r0, [r3, #{hex(slot)}]' for row in block)
                or not any(row.mnemonic == 'adds' and row.op_str == 'r1, #8' for row in block)):
            raise ValueError('Original interface constructor no longer binds its inspected slot')

        def word(at):
            if not 0x108000 <= at <= 0x108000+len(data)-4:
                raise ValueError('Original interface RTTI pointer is outside the supplied image')
            return struct.unpack_from('<I', data, at-0x108000)[0]

        at = word(word(tables[0]-4)+4)-0x108000
        if not 0 <= at < len(data):
            raise ValueError('Original interface RTTI name is outside the supplied image')
        raw = data[at:at+120].split(b'\0', 1)[0]
        p['interface_types'][name] = raw.decode('ascii')
    return data, s, p


def initialize(cpu, directory, obj, child, register_bases, present):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    _, s, p = profile(directory)
    source_root, target_root = 0x30010000, child-p['child_offset']
    source_bank = source_root+p['bank_offset']
    target_bank = target_root+p['bank_offset']
    bank_length, stack, finish = 0x39c, 0x3001f000, 0x3001e000
    # Only source handles are host-supplied. Their destination slots retain
    # canaries until the original assignment routine copies the second words.
    inputs = bytearray((n*17+31) & 255 for n in range(bank_length))
    handle_offset = p['child_offset']+0x1304-p['bank_offset']
    for n, base in enumerate(register_bases):
        struct.pack_into('<I', inputs, handle_offset+4+8*n, base if present[n] else 0)
    cpu.mem_write(source_bank, bytes(inputs))
    cpu.mem_write(target_bank-4, b'\x6b'*(bank_length+8))
    cpu.mem_write(obj-4, b'\xa5'*208)
    auxiliary = [0x30016000+n*0x100 for n in range(9)]
    cpu.mem_write(target_root+0x4e38, struct.pack('<9I', *auxiliary))
    relative_fields = {
        0: 0, 4: 0xd68, 8: 0xdc0, 12: 0xe18, 0x10: 0x2950, 0x14: 0x3930,
        0x18: 0x3cb0, 0x1c: 0x3be8, 0x20: 0x3d48, 0x24: 0x39ec,
        0x28: 0x39dc, 0x2c: 0x3d58, 0x30: 0x3d74, 0x34: 0x3e80,
        0x38: 0x41c8, 0x3c: 0x4330, 0x60: 0x4e60, 0x6c: 0x3920,
        0x74: 0x3963, 0x7c: 0x4310, 0x84: 0x3d44, 0x88: 0x3be0,
        0x90: 0x3448, 0x94: 0x3e74, 0x9c: 0x3958, 0xa0: 0x41c4,
        0xa8: 0x3964, 0xac: 0x39ea, 0xb0: 0x430c, 0xb8: 0x3c9c,
        0xc0: 0x3d18, 0xc4: 0x4358}
    pointer_fields = {0x5c: (8, 0), 0x64: (0, 0),
        0x40: (1, 0), 0x68: (1, 0x90c), 0x8c: (1, 0x75c),
        0x44: (2, 0), 0x70: (2, 0x1ec), 0x98: (2, 0x1e8),
        0x48: (3, 0), 0x78: (3, 0x19e4), 0xa4: (3, 0x2dc),
        0x4c: (4, 0), 0xb4: (4, 2), 0x50: (5, 0),
        0x80: (5, 0x3c), 0xbc: (5, 0x48), 0x54: (6, 0), 0x58: (7, 0)}
    expected_context = bytearray(b'\xa5'*200)
    for offset, relative in relative_fields.items():
        struct.pack_into('<I', expected_context, offset, target_root+relative)
    for offset, (index, relative) in pointer_fields.items():
        struct.pack_into('<I', expected_context, offset, auxiliary[index]+relative)
    original_inputs = bytes(cpu.mem_read(source_bank, bank_length))
    expected_bank = bytearray(b'\x6b'*bank_length)
    for offset in range(4, 0x320, 8):
        expected_bank[offset:offset+4] = inputs[offset:offset+4]
    expected_bank[0x320:] = inputs[0x320:]
    phase, copied_handles = 'copy', []
    protected = [getattr(arm, 'UC_ARM_REG_R'+str(n)) for n in range(4, 12)]
    values = [0x66550000+n for n in range(8)]

    def code_hook(uc, at, length, unused):
        regions = [(p['copy'], p['copy']+0x2fa), (s['memcpy'], s['memcpy']+0x300)] if phase == 'copy' else [
            (p['bind'], p['bind']+0x86), (p['core_bind'], p['core_bind']+0x118)]
        if not any(lo <= at and at+length <= hi for lo, hi in regions):
            raise ValueError('Original context construction entered an unresolved dependency: '+hex(at))

    def write_hook(uc, access, at, length, value, unused):
        if stack-4096 <= at and at+length <= stack:
            return
        lo, size = (target_bank, bank_length) if phase == 'copy' else (obj, 200)
        if not lo <= at or at+length > lo+size:
            raise ValueError('Original context construction changed unrelated state: '+hex(at))
        if phase == 'copy' and at in (child+0x1308, child+0x1310):
            copied_handles.append((at-child, length, value))

    ch, wh = cpu.hook_add(UC_HOOK_CODE, code_hook), cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)

    def run(entry, first, second):
        for register, value in zip(protected, values):
            cpu.reg_write(register, value)
        cpu.reg_write(arm.UC_ARM_REG_R0, first)
        cpu.reg_write(arm.UC_ARM_REG_R1, second)
        cpu.reg_write(arm.UC_ARM_REG_SP, stack)
        cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(entry | 1, finish, count=5000)
        if (cpu.reg_read(arm.UC_ARM_REG_PC) != finish
                or cpu.reg_read(arm.UC_ARM_REG_SP) != stack
                or [cpu.reg_read(register) for register in protected] != values):
            raise ValueError('Original context construction did not preserve its complete native return')

    try:
        run(p['copy'], target_bank, source_bank)
        expected_handles = [(0x1308+8*n, 4, base if present[n] else 0)
                            for n, base in enumerate(register_bases)]
        if (bytes(cpu.mem_read(target_bank, bank_length)) != bytes(expected_bank)
                or copied_handles != expected_handles
                or bytes(cpu.mem_read(source_bank, bank_length)) != original_inputs):
            raise ValueError('Native register-handle assignment/preserved first words differ')
        phase = 'bind'
        run(p['bind'], target_root, obj)
        if struct.unpack('<I', cpu.mem_read(obj+12, 4))[0] != child:
            raise ValueError('Complete native binder did not generate the consumer child pointer')
        if bytes(cpu.mem_read(obj, 200)) != bytes(expected_context):
            raise ValueError('Complete native context differs from independent pointer arithmetic')
        if (cpu.mem_read(target_bank-4, 4) != b'\x6b'*4
                or cpu.mem_read(target_bank+bank_length, 4) != b'\x6b'*4
                or cpu.mem_read(obj-4, 4) != b'\xa5'*4
                or cpu.mem_read(obj+200, 4) != b'\xa5'*4):
            raise ValueError('Native assignment/binder changed neighboring canaries')
    finally:
        cpu.hook_del(ch)
        cpu.hook_del(wh)
    return dict(native_selected_register_handle_words_copied=2, native_handle_entries_checked=100,
                native_assignment_bytes_checked=bank_length, native_context_bytes_checked=200,
                native_child_pointer_bound=True, original_context_binder_returned=True,
                native_interface_types=p['interface_types'],
                original_constructor_types_audited=True, original_constructors_executed=False,
                native_callee_saved_registers_preserved=True, source_handle_bank_preserved=True,
                destination_first_words_preserved=True,
                host_assigned_consumed_child_or_register_bases=False,
                source_handles_and_auxiliary_pointers_are_fixtures=True,
                backend_initialization_executed=False, full_pipeline_dispatch_executed=False,
                register_bases_are_verified_camera_addresses=False,
                sensor_position_or_settling_verified=False)


def replay(directory, *, flags=(1, 1), present=(1, 1)):
    return source_replay(directory, flags=flags, present=present,
        initialize_context=lambda cpu, obj, child, bases, available: initialize(
            cpu, directory, obj, child, bases, available))


def compare(c2, reference):
    rows = []
    for flags in ((0, 0), (1, 0), (0, 1), (1, 1)):
        for present in ((0, 0), (1, 0), (0, 1), (1, 1)):
            args = dict(flags=flags, present=present)
            a, b = replay(c2, **args), replay(reference, **args)
            if a != b:
                raise ValueError('Native C2/CR copied-context/input behavior differs')
            rows.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-native-context-input-source/1', paired_cases=len(rows), cases=rows,
                camera_io=False, physical_shift_verified=False, installable=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = compare(args.c2, args.reference)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps({key: report[key] for key in ('paired_cases', 'camera_io', 'physical_shift_verified')}))


if __name__ == '__main__':
    main()
