"""Audit native Pixel Shift descriptor support, without calling a camera.

Model indices are synthetic replay inputs. The owner's previously observed C2
index is 16; this script does not infer an A7CR identity from a numeric index.
The returned support flag is not proof of working IBIS or an installable patch.
"""
import argparse
import json
from pathlib import Path
import struct

from native_replay import source


def descriptor(directory, query):
    image, info = source(directory)
    mapping = 0x3df8d40 if info['model'] == 'ILCE-7CM2' else 0x3df9230
    offset = image.offset(mapping, 0x3008)
    entries = dict(struct.iter_unpack('<II', image.data[offset:offset + 0x3008]))
    index = entries[query]
    offset = image.offset(0x51c1858, 0x5910)
    defaults = dict(struct.iter_unpack('<QQ', image.data[offset:offset + 0x5910]))
    address = defaults[index]
    if struct.unpack_from('<I', image.data, image.offset(address, 4))[0] != 0x0200a84f:
        raise ValueError('Descriptor does not have the native Pixel Shift label ID')
    return image, info, index, address


def support(directory, query, model_index, *, override=None):
    from unicorn import (Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE,
                         UC_HOOK_MEM_UNMAPPED)
    from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_SP,
                                     UC_ARM64_REG_PC, UC_ARM64_REG_LR)
    if query not in (0x12f, 0x130) or not 0 <= model_index <= 25:
        raise ValueError('Expected one of the two native queries and a model index 0..25')
    image, info, index, address = descriptor(directory, query)
    target = info['model'] == 'ILCE-7CM2'
    entry = 0x1b76520 if target else 0x1b76600
    wrapper = 0x1b6cb8c if target else 0x1b6cc6c
    mapper = 0x1b61718 if target else 0x1b617f8
    family = 0x1797d44 if target else 0x1797e24
    ranges = [(entry, entry + 0x30), (wrapper, wrapper + 0x28),
              (mapper, mapper + 0x30), (family, family + 0x18)]
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    pages = set()

    def load(page):
        if page not in pages:
            at = image.offset(page, 4096)
            cpu.mem_map(page, 4096)
            cpu.mem_write(page, image.data[at:at + 4096])
            pages.add(page)

    def unmapped(uc, access, at, size, value, _):
        load(at & ~4095)
        return True

    cpu.hook_add(UC_HOOK_MEM_UNMAPPED, unmapped)
    load(0x5bc35b0 & ~4095)
    cpu.mem_write(0x5bc35b0, struct.pack('<I', model_index))
    cpu.mem_map(0x10000000, 0x10000)
    cpu.mem_write(0x10000000, b'\0' * 4)
    cpu.reg_write(UC_ARM64_REG_X0, address)
    cpu.reg_write(UC_ARM64_REG_SP, 0x1000f000)
    cpu.reg_write(UC_ARM64_REG_LR, 0x10000000)
    result = {'query': hex(query), 'descriptor_index': hex(index),
              'model_input': model_index, 'model_identity_inferred': False,
              'external_calls_executed': 0}

    def hook(uc, at, size, _):
        if not any(a <= at < b for a, b in ranges):
            raise ValueError('Capability replay reached an unhandled native function')
        if at == entry + 0x14:
            slot = uc.reg_read(UC_ARM64_REG_X0)
            if slot >= 19:
                raise ValueError('Native model slot outside descriptor')
            window = address + 0x2c + slot * 2
            original = image.data[image.offset(window, 2):image.offset(window, 2) + 2]
            result.update(slot=slot, support_window=hex(window), original=original.hex())
            if override is not None:
                load(window & ~4095)
                cpu.mem_write(window, struct.pack('<H', override))

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.emu_start(entry, 0x10000000, count=120)
    if cpu.reg_read(UC_ARM64_REG_PC) != 0x10000000:
        raise ValueError('Native descriptor support did not return')
    result['support'] = bool(cpu.reg_read(UC_ARM64_REG_X0))
    return result


def compare(c2, reference):
    cases = []
    for query in (0x12f, 0x130):
        for model in range(26):
            a, b = support(c2, query, model), support(reference, query, model)
            # Address layout is not assumed equal; compare computed behavior.
            for field in ('descriptor_index', 'slot', 'original', 'support'):
                if a[field] != b[field]:
                    raise ValueError('C2/A7CR native descriptor behavior differs')
            cases.append(dict(target=a, reference=b))
    before = support(c2, 0x12f, 16)
    after = support(c2, 0x12f, 16, override=1)
    if before['slot'] != 9 or before['support'] or not after['support']:
        raise ValueError('Unexpected C2 descriptor behavior')
    return {'schema': 'a7c2-pixelshift-capability-replay/1', 'cases': cases,
            'paired_cases': len(cases), 'camera_io': False,
            'emulated_one_field_change': {'before': before, 'after': after},
            'installable': False, 'physical_shift_verified': False,
            'limit': 'Static descriptor support only; no live feature cache, menu or driver executed'}


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
    print(json.dumps({'paired_cases': report['paired_cases'], 'camera_io': False,
                      'installable': False, 'output': str(args.output)}))


if __name__ == '__main__':
    main()
