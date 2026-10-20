"""Replay original CP PixelShiftInfo emission, using synthetic frame state.

Starts AFTER the native EXIF allocation/lookup boundary, with a preallocated
six-byte field. No allocator, capture, positioning or hardware success is mocked.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct


@lru_cache(maxsize=2)
def program(directory):
    data = (Path(directory) / 'cpapp-b.bin').read_bytes()
    # The surrounding MOVW selects Sony's actual PixelShiftInfo EXIF tag.
    variants = [
        ('ILCE-7CM2', 0x47285e, 0x472874, 0x4728fc),
        ('ILCE-7CR', 0x472a76, 0x472a8c, 0x472b14),
    ]
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    for model, tag, begin, end in variants:
        offset = tag - 0x108000
        instruction = list(md.disasm(data[offset:offset + 4], tag))
        if (len(instruction) == 1 and instruction[0].mnemonic == 'movw'
                and instruction[0].op_str == 'r1, #0x202f'):
            return data, model, begin, end
    raise ValueError('Native PixelShiftInfo writer was not recognized')


def emit(directory, *, active, ordinal, count, cached_group=0, seed=0x1234):
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
    from unicorn.arm_const import (UC_ARM_REG_R4, UC_ARM_REG_R5,
                                   UC_ARM_REG_SP, UC_ARM_REG_PC)
    data, model, begin, end = program(directory)
    cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    for page in range(begin & ~4095, (end + 4095) & ~4095, 4096):
        cpu.mem_map(page, 4096)
        offset = page - 0x108000
        cpu.mem_write(page, data[offset:offset + 4096])
    output, context, frame, group, stack = [0x30000000 + n * 0x10000 for n in range(5)]
    for address in (output, context, frame, group, stack):
        cpu.mem_map(address, 0x10000)
    cpu.mem_write(output, b'\xa5' * 32)
    cpu.mem_write(context + 0x78, struct.pack('<I', active))
    cpu.mem_write(frame + 0x208, struct.pack('<I', ordinal))
    cpu.mem_write(frame + 0x5aa0, struct.pack('<I', group))
    cpu.mem_write(frame + 0x5c08, struct.pack('<I', count))
    cpu.mem_write(frame + 0x6040, struct.pack('<I', seed))
    cpu.mem_write(frame + 0x977, bytes((1, 2, 3, 4)))
    cpu.mem_write(group + 0x5a8c, struct.pack('<I', cached_group))
    cpu.mem_write(stack + 12, struct.pack('<I', output))
    cpu.reg_write(UC_ARM_REG_R4, frame)
    cpu.reg_write(UC_ARM_REG_R5, context)
    cpu.reg_write(UC_ARM_REG_SP, stack)
    visited = []

    def hook(uc, address, size, _):
        if not begin <= address < end:
            raise ValueError('Metadata slice attempted an external call')
        visited.append(address)

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.emu_start(begin | 1, end, count=100)
    if cpu.reg_read(UC_ARM_REG_PC) != end:
        raise ValueError('Metadata slice did not finish')
    result = bytes(cpu.mem_read(output, 32))
    if result[6:] != b'\xa5' * 26:
        raise ValueError('Metadata wrote outside the six-byte field')
    cached = struct.unpack('<I', cpu.mem_read(group + 0x5a8c, 4))[0]
    return {'model': model, 'field': result[:6].hex(), 'cached_group': cached,
            'instructions': len(visited), 'external_calls': 0,
            'physical_frame_produced': False}


def compare(c2, reference):
    cases = []
    for count in (4, 16):
        for seed in (0, 0x1234, 0xffffffff):
            cached = 0
            for ordinal in range(count):
                values = dict(active=1, ordinal=ordinal, count=count,
                              cached_group=cached, seed=seed)
                target, donor = emit(c2, **values), emit(reference, **values)
                if target['field'] != donor['field']:
                    raise ValueError('C2/A7CR native metadata differs')
                field = bytes.fromhex(target['field'])
                if field[4:] != bytes((ordinal + 1, count)):
                    raise ValueError('Unexpected native source ordinal/count')
                actual_group = struct.unpack_from('<I', field)[0]
                if ordinal and actual_group != cached:
                    raise ValueError('Native group ID changed during sequence')
                cached = target['cached_group']
                cases.append(dict(values, target=target, reference=donor))
    for active in (0, 2, 255):
        values = dict(active=active, ordinal=0, count=4)
        target, donor = emit(c2, **values), emit(reference, **values)
        if target['field'] != '000000000000' or target['field'] != donor['field']:
            raise ValueError('Native non-PixelShift metadata is not cleared')
        cases.append(dict(values, target=target, reference=donor))
    return {'schema': 'a7c2-pixelshift-metadata-replay/1', 'paired_cases': len(cases),
            'camera_io': False, 'physical_shift_verified': False,
            'limit': 'Native field emission with synthetic frame state and preallocated output only',
            'cases': cases}


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
    print(json.dumps({k: v for k, v in report.items() if k != 'cases'}, indent=2))


if __name__ == '__main__':
    main()
