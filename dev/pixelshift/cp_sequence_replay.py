"""Replay native per-frame CP sequence selection, with synthetic frame state.

Original byte getters, the selector and its descriptor initializer execute.
Selection stops BEFORE the logging/sequence-configuration boundary. Descriptor
callbacks, capture preparation, hardware and completion are never executed.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_metadata_replay import program


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, model, _, _ = program(directory)
    target = model == 'ILCE-7CM2'
    p = dict(selector=0x48335c if target else 0x483574,
             initializer=0xb1446a if target else 0xb142c8,
             classify=0xb198e0 if target else 0xb1973e,
             first_getter=0xb0b1f6 if target else 0xb0b054,
             second_getter=0xb1ab90 if target else 0xb1a9ee,
             low_getter=0xb090f8 if target else 0xb08f56,
             boundary=0xb1a5ca if target else 0xb1a428,
             trace=0xb4457a if target else 0xb443d8,
             debug=0x1a533a4 if target else 0x1a52154,
             continuation_state=0x1ac56d0 if target else 0x1ac42f4)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def instructions(entry, size):
        return list(md.disasm(data[entry - 0x108000:entry - 0x108000 + size], entry))

    def direct_byte_address(entry):
        code = instructions(entry, 12)
        if ([i.mnemonic for i in code] != ['movw', 'movt', 'ldrb', 'bx']
                or code[2].op_str != 'r0, [r0]' or code[3].op_str != 'lr'):
            raise ValueError('Unexpected native state-byte getter')
        return int(code[0].op_str.split('#')[1], 0) | (int(code[1].op_str.split('#')[1], 0) << 16)

    p['first_byte'] = direct_byte_address(p['first_getter'])
    p['second_byte'] = direct_byte_address(p['low_getter'])
    start = instructions(p['initializer'], 0x20)
    if (start[0].mnemonic != 'movw' or not start[0].op_str.startswith('r2, #')
            or start[4].mnemonic != 'movt' or not start[4].op_str.startswith('r2, #')):
        raise ValueError('Native sequence descriptor initializer changed')
    p['descriptors'] = int(start[0].op_str.split('#')[1], 0) | (int(start[4].op_str.split('#')[1], 0) << 16)
    return data, p


def machine(data, state_pages):
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB
    from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_LR
    cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    size = (len(data) + 4095) & ~4095
    cpu.mem_map(0x108000, size)
    cpu.mem_write(0x108000, data)
    for page in sorted(set(state_pages)):
        if not 0x108000 <= page < 0x108000 + size:
            cpu.mem_map(page, 4096)
    cpu.mem_map(0x30000000, 0x20000)
    cpu.reg_write(UC_ARM_REG_SP, 0x3001f000)
    cpu.reg_write(UC_ARM_REG_LR, 0x3001e001)
    return cpu


@lru_cache(maxsize=2)
def descriptors(directory):
    """Execute the original straight-line 17-record initializer slice only."""
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import UC_ARM_REG_PC
    data, p = profile(directory)
    base = p['descriptors']
    cpu = machine(data, range(base & ~4095, (base + 340 + 4095) & ~4095, 4096))
    cpu.mem_write(base - 4, b'\xa5' * 348)
    begin, end = p['initializer'], p['initializer'] + 0x15e

    def hook(uc, address, size, unused):
        if not begin <= address < end:
            raise ValueError('Descriptor slice left its original initializer')

    def write_hook(uc, access, address, size, value, unused):
        if not base <= address or address + size > base + 340:
            raise ValueError('Initializer wrote outside its 17 descriptors')

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    cpu.emu_start(begin | 1, end, count=200)
    if (cpu.reg_read(UC_ARM_REG_PC) != end or bytes(cpu.mem_read(base - 4, 4)) != b'\xa5' * 4
            or bytes(cpu.mem_read(base + 340, 4)) != b'\xa5' * 4):
        raise ValueError('Descriptor initializer did not finish within its bounds')
    records = [struct.unpack('<5I', cpu.mem_read(base + index * 20, 20)) for index in range(17)]
    if any(not record[0] & 1 or record[1] or not record[2] & 1 or record[3] or record[4] for record in records):
        raise ValueError('Unexpected native sequence descriptor shape')
    return records


def select(directory, *, mode, ordinal, first_flag, second_flag, continuation_state=0):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                                   UC_ARM_REG_PC, UC_ARM_REG_LR)
    data, p = profile(directory)
    pages = {p[k] & ~4095 for k in ('first_byte', 'second_byte', 'debug')}
    pages.add(p['continuation_state'] & ~4095)
    cpu = machine(data, pages)
    frame, args, output = 0x30000000, 0x30010000, 0x30011000
    cpu.mem_write(frame, b'\xa5' * 0x7000)
    for offset, value in ((0x66e8, 1), (0x5c10, 0), (0x210, mode), (0x208, ordinal)):
        cpu.mem_write(frame + offset, struct.pack('<I', value))
    cpu.mem_write(frame + 0x5c38, b'\1')
    before = bytes(cpu.mem_read(frame, 0x7000))
    cpu.mem_write(args, struct.pack('<I', frame))
    cpu.mem_write(output, b'\xa5' * 20)
    cpu.mem_write(p['first_byte'], bytes([first_flag]))
    cpu.mem_write(p['second_byte'], bytes([second_flag]))
    cpu.mem_write(p['continuation_state'], bytes([continuation_state]))
    cpu.reg_write(UC_ARM_REG_R0, output)
    cpu.reg_write(UC_ARM_REG_R1, args)
    result = dict(configuration_executed=False, callback_executed=False,
                  synthetic_frame_and_flags=True, diagnostic_calls_omitted=0,
                  physical_shift_verified=False)
    regions = [(p['selector'], p['selector'] + 0x14c), (p['classify'], p['classify'] + 0x3c),
               (p['first_getter'], p['first_getter'] + 12), (p['second_getter'], p['second_getter'] + 0x28),
               (p['low_getter'], p['low_getter'] + 12)]

    def hook(uc, address, size, unused):
        if address == p['boundary']:
            if uc.reg_read(UC_ARM_REG_R0) != frame or uc.reg_read(UC_ARM_REG_R1) != 0:
                raise ValueError('Selector changed its native configuration arguments')
            result['sequence_index'] = uc.reg_read(UC_ARM_REG_R2)
            uc.emu_stop()
        elif address == p['trace']:
            result['diagnostic_calls_omitted'] += 1
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1)
        elif not any(begin <= address < end for begin, end in regions):
            raise ValueError('Selector reached unhandled code: ' + hex(address))

    def write_hook(uc, access, address, size, value, unused):
        if not 0x30018000 <= address or address + size > 0x3001f000:
            raise ValueError('Selector wrote outside its stack')

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    cpu.emu_start(p['selector'] | 1, 0x3001e000, count=300)
    if ('sequence_index' not in result or bytes(cpu.mem_read(frame, 0x7000)) != before
            or bytes(cpu.mem_read(output, 20)) != b'\xa5' * 20):
        raise ValueError('Selector changed input/output before its configuration boundary')
    record = descriptors(directory)[result['sequence_index']]
    result['native_callback'] = hex(record[2])
    return result


def compare(c2, reference):
    cases = []
    for mode in (2, 23):
        for ordinal in range(4):
            for first, second in ((0, 0), (0, 1), (1, 0), (1, 1)):
                for continuation in (0, 1):
                    args = dict(mode=mode, ordinal=ordinal, first_flag=first, second_flag=second,
                                continuation_state=continuation)
                    a, b = select(c2, **args), select(reference, **args)
                    if ({k: v for k, v in a.items() if k != 'native_callback'}
                            != {k: v for k, v in b.items() if k != 'native_callback'}):
                        raise ValueError('C2/A7CR per-frame selection differs')
                    expected = 4 if first else 9
                    if mode != 23 and ordinal:
                        expected += 3 if continuation else 1
                    if a['sequence_index'] != expected:
                        raise ValueError('Native Pixel Shift did not retain its first-frame sequence')
                    cases.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-cp-sequence/1', camera_io=False, installable=False,
                physical_shift_verified=False, paired_cases=len(cases), cases=cases)


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
    print(json.dumps({key: report[key] for key in ('paired_cases', 'camera_io', 'installable')}))


if __name__ == '__main__':
    main()
