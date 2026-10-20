"""Offline audit of Pixel Shift's three individual menu-option support gates.

The parent descriptor, parameter definition and child visibility are distinct.
Only original getters execute; this does not run the menu or camera hardware.
"""
import argparse
import json
from pathlib import Path
import struct

from capability_replay import descriptor


def options(directory):
    image, info, _, parent = descriptor(directory, 0x12f)
    count = struct.unpack_from('<I', image.data, image.offset(parent + 0x54, 4))[0]
    children = image.qword(parent + 0x58)
    if count != 3:
        raise ValueError('Expected three original Pixel Shift options')
    result = []
    for i in range(count):
        at = children + i * 0xb8
        ident, canonical, label = struct.unpack_from('<III', image.data, image.offset(at, 12))
        value, prop = struct.unpack_from('<II', image.data, image.offset(at + 0x60, 8))
        if (ident, canonical, value, prop) != (0x3e0 + i, 0x3e0 + i, i, 0x5db):
            raise ValueError('Original Pixel Shift option layout differs')
        result.append(dict(index=i, item=ident, label=label, value=value, address=at))
    return image, info, result


def support(directory, option, model_index, *, override=None):
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_UNMAPPED
    from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_SP,
                                     UC_ARM64_REG_LR, UC_ARM64_REG_PC)
    if option not in (0, 1, 2) or not 0 <= model_index <= 25:
        raise ValueError('Expected an option 0..2 and model input 0..25')
    image, info, items = options(directory)
    delta = 0 if info['model'] == 'ILCE-7CM2' else 0xe0
    entry, predicate = 0x1b76980 + delta, 0x1b76970 + delta
    wrapper, mapper, family = 0x1b6cb8c + delta, 0x1b61718 + delta, 0x1797d44 + delta
    address = items[option]['address']
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    pages = set()

    def load(page):
        if page not in pages:
            off = image.offset(page, 4096)
            cpu.mem_map(page, 4096)
            cpu.mem_write(page, image.data[off:off + 4096])
            pages.add(page)

    def unmapped(uc, access, at, size, value, _):
        load(at & ~4095)
        return True

    cpu.hook_add(UC_HOOK_MEM_UNMAPPED, unmapped)
    load(0x5bc35b0 & ~4095)
    cpu.mem_write(0x5bc35b0, struct.pack('<I', model_index))
    cpu.mem_map(0x10000000, 0x10000)
    cpu.reg_write(UC_ARM64_REG_X0, address)
    cpu.reg_write(UC_ARM64_REG_SP, 0x1000f000)
    cpu.reg_write(UC_ARM64_REG_LR, 0x10000000)
    regions = [(entry, entry + 0x2c), (predicate, predicate + 0x10),
               (wrapper, wrapper + 0x28), (mapper, mapper + 0x30), (family, family + 0x18)]
    result = dict(option=option, value=items[option]['value'], item=hex(items[option]['item']),
                  descriptor=hex(address), model_input=model_index, model_identity_inferred=False)

    def hook(uc, at, size, _):
        if not any(a <= at < b for a, b in regions):
            raise ValueError('Original option getter reached an unhandled function: ' + hex(at))
        if at == entry + 0x14:
            slot = uc.reg_read(UC_ARM64_REG_X0)
            if not 0 <= slot < 19:
                raise ValueError('Model column is outside the option descriptor')
            field = address + 0x20 + slot * 2  # Child layout differs from the parent.
            off = image.offset(field, 2)
            result.update(slot=slot, field=hex(field), original=image.data[off:off + 2].hex())
            if override is not None:
                load(field & ~4095)
                cpu.mem_write(field, struct.pack('<H', override))

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.emu_start(entry, 0x10000000, count=150)
    if cpu.reg_read(UC_ARM64_REG_PC) != 0x10000000:
        raise ValueError('Original option getter did not return')
    result['visible_by_model'] = bool(cpu.reg_read(UC_ARM64_REG_X0))
    result['external_calls_executed'] = 0
    return result


def compare(c2, reference):
    cases = []
    for option in (0, 1, 2):
        for model in range(26):
            a, b = support(c2, option, model), support(reference, option, model)
            if any(a[k] != b[k] for k in ('option', 'value', 'item', 'slot', 'original', 'visible_by_model')):
                raise ValueError('C2/A7CR original option support differs')
            cases.append(dict(target=a, reference=b))
    before = [support(c2, i, 16) for i in range(3)]
    after = [support(c2, i, 16, override=1 if i in (0, 1) else None) for i in range(3)]
    if any(r['visible_by_model'] for r in before) or [r['visible_by_model'] for r in after] != [True, True, False]:
        raise ValueError('Unexpected native C2 option visibility')
    strict = support(c2, 1, 16, override=2)
    if strict['visible_by_model']:
        raise ValueError('Strict native option getter accepted a value other than 1')
    return dict(schema='a7c2-pixelshift-option-replay/1', paired_cases=len(cases), cases=cases,
                emulated_c2_four_shot_options=dict(before=before, after=after, strict_value_two=strict),
                camera_io=False, installable=False, physical_shift_verified=False,
                limit='Original model-based child visibility only; no loaded cache, permissions, menu rendering or capture is executed')


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
    print(json.dumps(dict(paired_cases=report['paired_cases'], camera_io=False, installable=False,
                          original_c2_visible=0, emulated_c2_visible=2, output=str(args.output))))


if __name__ == '__main__':
    main()
