"""Offline parameter-capability audit, separate from the menu support gate.

Executes original AP capability/value validators. No USB, native notifications,
settings, firmware output, capture or stabilizer calls. The optional table change
exists only in the emulator and does not establish camera safety or operation.
"""
import argparse
import json
from pathlib import Path
import struct

from native_replay import source

PROPERTY = 0x5db
TABLE = 0x56c4118
EXCLUSION_PARAMETER = 0x28c


def profile(directory):
    image, info = source(directory)
    delta = 0 if info['model'] == 'ILCE-7CM2' else 0x3cc
    return image, dict(model=info['model'], classify=0x28bbd58 + delta,
                      validate=0x28bbcc8 + delta, fallback=0x28bbb68 + delta,
                      array_validator=0x28bbad4 + delta)


def definition(directory):
    image, p = profile(directory)
    at = TABLE + PROPERTY * 24
    callback, data, count = struct.unpack_from('<QQI', image.data, image.offset(at, 20))
    values = None
    if callback == p['array_validator']:
        off = image.offset(data, count)
        values = list(image.data[off:off + count])
    elif callback != p['fallback']:
        raise ValueError('Unrecognized original parameter validator')
    return dict(property=hex(PROPERTY), row=hex(at), callback=hex(callback),
                defined=callback != p['fallback'], count=count, allowed_values=values)


def replay(directory, value=None, *, emulated_definition=False, initialization=False):
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_UNMAPPED
    from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1,
        UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC)
    image, p = profile(directory)
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    pages = set()

    def load(page):
        if page not in pages:
            off = image.offset(page, 4096)
            cpu.mem_map(page, 4096)
            cpu.mem_write(page, image.data[off:off + 4096])
            pages.add(page)

    def unmapped(uc, access, at, length, data, _):
        load(at & ~4095)
        return True

    cpu.hook_add(UC_HOOK_MEM_UNMAPPED, unmapped)
    if emulated_definition:
        if p['model'] != 'ILCE-7CM2':
            raise ValueError('The hypothetical definition is C2-only')
        # Use an existing native three-value definition, not donor code/padding.
        donor = TABLE + 3 * 24
        callback, data, count = struct.unpack_from('<QQI', image.data, image.offset(donor, 20))
        if callback != p['array_validator'] or count != 3:
            raise ValueError('Native three-value fixture changed')
        off = image.offset(data, count)
        if image.data[off:off + count] != b'\1\1\1':
            raise ValueError('Native three-value fixture is not fully defined')
        row = TABLE + PROPERTY * 24
        load(row & ~4095)
        cpu.mem_write(row, struct.pack('<QQI', callback, data, count))
    cpu.mem_map(0x10000000, 0x10000)
    cpu.reg_write(UC_ARM64_REG_SP, 0x1000f000)
    cpu.reg_write(UC_ARM64_REG_LR, 0x10000000)
    cpu.reg_write(UC_ARM64_REG_X0, PROPERTY)
    cpu.reg_write(UC_ARM64_REG_X1, 0 if value is None else value & 0xffffffff)
    cpu.reg_write(UC_ARM64_REG_X2, 0)
    cpu.reg_write(UC_ARM64_REG_X3, 0)  # Do not enter warning/logging functions.
    ranges = [(p['classify'], p['classify'] + 0x74),
              (p['validate'], p['validate'] + 0x88),
              (p['fallback'], p['fallback'] + 0x14),
              (p['array_validator'], p['array_validator'] + 0x20)]
    notifications = []
    entry = p['classify'] if value is None else p['validate']
    if initialization:
        if p['model'] != 'ILCE-7CM2':
            raise ValueError('Initializer registry fixture is C2-only')
        cpu.mem_map(0x20000000, 0x10000)
        # Minimal native linked/hash registries, with only this parameter and
        # its three options. Original lookup, classification and validation run.
        for at, data in [
            (0x20000010, struct.pack('<Q', 0x20000100)),
            (0x20000100, struct.pack('<QII', 0, PROPERTY, EXCLUSION_PARAMETER)),
            (0x20000200, struct.pack('<QQ', 0x20000300, 1)),
            (0x20000300, struct.pack('<Q', 0x20000400)),
            (0x20000400, struct.pack('<Q', 0x20000500)),
            (0x20000500, struct.pack('<QI', 0, PROPERTY)),
            (0x20000520, struct.pack('<Q', 0x20000600))]:
            cpu.mem_write(at, data)
        for k in range(3):
            cpu.mem_write(0x20000600 + k * 32,
                struct.pack('<QII', 0x20000600 + (k + 1) * 32 if k < 2 else 0, k, 0x2927 + k))
        for at, pointer in [(0x5b52f58, 0x20000000), (0x5b76a20, 0x20000200)]:
            load(at & ~4095)
            cpu.mem_write(at, struct.pack('<Q', pointer))
        cpu.reg_write(UC_ARM64_REG_X0, 0x20000800)  # Opaque manager; notifier is not executed.
        cpu.reg_write(UC_ARM64_REG_X1, 9)
        cpu.reg_write(UC_ARM64_REG_X2, 1)
        entry = 0x247051c
        ranges.extend([(0x247051c, 0x2470608), (0x24704b4, 0x247051c)])

    def hook(uc, at, size, _):
        if initialization and at == 0x246f404:
            # Observe a void notification boundary. Do not execute its writes
            # or model callbacks, or substitute success for any device call.
            notifications.append(dict(parameter=hex(uc.reg_read(UC_ARM64_REG_X1)),
                                      inhibited_item=hex(uc.reg_read(UC_ARM64_REG_X2)),
                                      inhibit=uc.reg_read(UC_ARM64_REG_X3)))
            uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))
            return
        if not any(a <= at < b for a, b in ranges):
            raise ValueError('Original validator entered an unhandled function: ' + hex(at))

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.emu_start(entry, 0x10000000, count=1000 if initialization else 200)
    if cpu.reg_read(UC_ARM64_REG_PC) != 0x10000000:
        raise ValueError('Original validator did not return')
    return notifications if initialization else bool(cpu.reg_read(UC_ARM64_REG_X0))


def c2_rules(directory):
    """Decode the actual incoming-rule index; do not confuse outgoing links."""
    image, p = profile(directory)
    if p['model'] != 'ILCE-7CM2':
        raise ValueError('This exclusion-table profile is C2-only')
    names = 0x57fd340

    def name(idx):
        at = image.qword(names + idx * 8)
        off = image.offset(at)
        end = image.data.find(b'\0', off)
        if not off <= end < off + 512:
            raise ValueError('Invalid native exclusion label')
        return image.data[off:end].decode('ascii')

    if name(EXCLUSION_PARAMETER) != 'PRM_setting_px_shift_multi_shoot':
        raise ValueError('Wrong native exclusion parameter')
    incoming, ranges = image.qword(0x5b66c10), image.qword(0x5b874a8)
    ptr, count = image.qword(incoming + EXCLUSION_PARAMETER * 16), image.qword(incoming + EXCLUSION_PARAMETER * 16 + 8)
    if count != 10:
        raise ValueError('Unexpected native incoming-rule count')
    rules = []
    for j in range(count):
        rule = image.qword(ptr + j * 8)
        mapping = image.qword(rule)
        affected, condition = struct.unpack_from('<II', image.data, image.offset(rule + 8, 8))
        if affected != EXCLUSION_PARAMETER:
            raise ValueError('Incoming rule belongs to a different target')
        lo, hi, special = struct.unpack_from('<III', image.data, image.offset(ranges + condition * 12, 12))
        if special or not 0 < hi - lo < 128:
            raise ValueError('Unexpected condition mapping')
        values = []
        for value in range(lo, hi + 1):
            vector = image.qword(mapping + (value - lo) * 8)
            effects = []
            if vector:
                data, size = image.qword(vector), image.qword(vector + 8)
                if size > 128:
                    raise ValueError('Unexpected native effect count')
                for k in range(size):
                    packed, a, b = struct.unpack_from('<III', image.data, image.offset(data + k * 12, 12))
                    effects.append(dict(kind=packed & 255, flags=(packed >> 8) & 255,
                                        operand_a=hex(a), operand_b=hex(b)))
            values.append(dict(value=hex(value), name=name(value), effects=effects))
        rules.append(dict(condition=hex(condition), name=name(condition), values=values))
    return rules


def compare(c2, reference):
    a, b = definition(c2), definition(reference)
    if a['defined'] or not b['defined'] or b['allowed_values'] != [1, 1, 1]:
        raise ValueError('Original C2/A7CR parameter definitions differ from the audited sources')
    classified = dict(c2=replay(c2), reference=replay(reference), emulated_c2=replay(c2, emulated_definition=True))
    if classified != dict(c2=False, reference=True, emulated_c2=True):
        raise ValueError('Native parameter classification differs')
    cases = []
    for value in (-1, 0, 1, 2, 3, 4, 255):
        row = dict(value=value, c2=replay(c2, value), reference=replay(reference, value),
                   emulated_c2=replay(c2, value, emulated_definition=True))
        if not row['c2'] or row['reference'] != (value in (0, 1, 2)) or row['emulated_c2'] != row['reference']:
            raise ValueError('Original value validation differs')
        cases.append(row)
    initial = replay(c2, initialization=True)
    changed = replay(c2, initialization=True, emulated_definition=True)
    expected_items = [hex(x) for x in (EXCLUSION_PARAMETER, 0x2927, 0x2928, 0x2929)]
    if [r['inhibited_item'] for r in initial] != expected_items or changed:
        raise ValueError('Original unsupported-parameter inhibition differs')
    if any(r['parameter'] != hex(EXCLUSION_PARAMETER) or r['inhibit'] != 1 for r in initial):
        raise ValueError('Unexpected inhibition source or direction')
    return dict(schema='a7c2-pixelshift-eligibility/1', target=a, reference=b,
                native_classification=classified, value_cases=cases,
                original_instruction_cases=26, c2_incoming_rules=c2_rules(c2),
                initialization_notifications=dict(original=initial, emulated_definition=changed,
                    registry='synthetic one-parameter native linked/hash registries', notifier_executed=False),
                camera_io=False, installable=False, physical_shift_verified=False,
                limit='Parameter definitions and static rules only; no live refresh, notifier or capture is executed')


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
    print(json.dumps(dict(original_instruction_cases=report['original_instruction_cases'],
                          incoming_rules=len(report['c2_incoming_rules']), camera_io=False,
                          installable=False, output=str(args.output))))


if __name__ == '__main__':
    main()
