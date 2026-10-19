"""Trace original frame-class production, before any processing or capture.

Raw inputs have no assumed camera UI names. Pure original helper leaves run;
diagnostics and downstream processing are stop boundaries.
No USB, patch output or image-buffer allocation is provided.
"""
import argparse
import collections
import hashlib
import itertools
import json
import struct
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6,
    UC_ARM_REG_R10, UC_ARM_REG_R11, UC_ARM_REG_SP, UC_ARM_REG_PC)
from audit_control import SPECS

FRAME, STACK = 0x30000000, 0x40000000
SPECS_PROFILE = {
    'a7c2-2.01': dict(start=0x3A1C92, end=0x3A1DA0, code=(0x3A1000, 0x2000),
        frame_reg=UC_ARM_REG_R10, profile=0x1698, kind=0x5C10, drive=0x210,
        async_enable=0xA0D, readout=0x5C08, preference=0x5764, cls=0xBB4,
        master=0x1AC5644, debug=0x1A533A4,
        pure_leaves=(0xA119FA, 0xA2F00A), special_byte=0xBB8, threshold=0x11E0,
        boundaries={0xA3C57A: 'native-diagnostic'}),
    'a1ii-4.00': dict(start=0x3EB0EA, end=0x3EB216, code=(0x3EB000, 0x1000),
        frame_reg=UC_ARM_REG_R11, profile=0x16E0, kind=0x5DA8, drive=0x228,
        async_enable=0xA51, readout=0x5DA0, preference=0x58B4, cls=0xBFC,
        master=0x19ACC14, debug=0x19386AC,
        pure_leaves=(0xAA5810, 0xAC48C0), special_byte=0xC00, threshold=0x1251,
        boundaries={0xAD1E8C: 'native-diagnostic'}),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = dict(schema='OFFLINE_NATIVE_FRAME_PROFILE/1', camera_io=False, models={})
    # Product deliberately keeps capture kind 0: the retention selector
    # requires that independent condition. Other cases are not claimed.
    inputs = list(itertools.product(range(5), (0, 1, 2, 9), (0, 1), (0, 1),
        range(4), (0, 1, 3), (0, 1, 16), (0, 3, 16), (0, 4, 8), range(3)))
    for model, spec in SPECS_PROFILE.items():
        cp = (args.firmware_root / model / 'components/cpapp-b.bin').read_bytes()
        if hashlib.sha256(cp).hexdigest() != SPECS[model]['sha256']:
            raise ValueError('Unsupported private original ' + model)
        u = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        begin, size = spec['code']
        u.mem_map(begin, size)
        u.mem_write(begin, cp[begin:begin + size])
        pages = set(range(begin, begin + size, 4096))
        for at in [spec['master'], spec['debug'], *spec['boundaries'], *spec['pure_leaves']]:
            page = at & ~4095
            if page not in pages:
                u.mem_map(page, 4096)
                if page < len(cp):
                    u.mem_write(page, cp[page:page + 4096])
                pages.add(page)
        u.mem_map(FRAME, 0x7000)
        u.mem_map(STACK, 0x4000)
        result = []
        counts, examples, leaf_calls = collections.Counter(), {}, collections.Counter()
        def stop(cpu, address, size, user):
            if address in spec['pure_leaves']:
                leaf_calls[hex(address)] += 1
            if address == spec['end'] or address in spec['boundaries']:
                result.append(address)
                cpu.emu_stop()
        u.hook_add(UC_HOOK_CODE, stop)
        for profile, drive, asynchronous, readout, preference, subtype, master, debug, flags, variant in inputs:
            before = bytearray(0x7000)
            for at, value in [(spec['profile'], profile), (spec['drive'], drive),
                    (spec['readout'], readout), (spec['preference'], preference), (0x54, subtype),
                    (spec['cls'], 0xA5A5A5A5)]:
                struct.pack_into('<I', before, at, value)
            before[spec['async_enable']] = asynchronous
            if variant == 1:
                struct.pack_into('<I', before, 0x38, 1)
                before[0x3C] = 2
            elif variant == 2:
                if model == 'a7c2-2.01':
                    struct.pack_into('<H', before, spec['threshold'], 0x1100)
                else:
                    before[spec['threshold']] = 17
            u.mem_write(FRAME, bytes(before))
            u.mem_write(spec['master'] + 0x8A, bytes([master]))
            u.mem_write(spec['debug'] + 0x6F, bytes([debug]))
            u.mem_write(spec['debug'] + 0x6A, bytes([flags]))
            u.reg_write(spec['frame_reg'], FRAME)
            u.reg_write(UC_ARM_REG_R6, FRAME + spec['kind'])
            if model == 'a7c2-2.01':
                u.reg_write(UC_ARM_REG_R4, FRAME + spec['kind'])
                u.reg_write(UC_ARM_REG_R5, 0)
                u.mem_write(STACK + 0x3008, struct.pack('<I', FRAME + spec['profile']))
            else:
                u.reg_write(UC_ARM_REG_R10, FRAME + spec['profile'])
                u.reg_write(UC_ARM_REG_R4, spec['debug'])
                # +0x7c is a diagnostic guard on donor only and is zero.
            u.reg_write(UC_ARM_REG_SP, STACK + 0x3000)
            result.clear()
            u.emu_start(spec['start'] | 1, 0xFFFFFFFF, count=180)
            if len(result) != 1 or u.reg_read(UC_ARM_REG_PC) != result[0]:
                raise AssertionError('Unresolved native profile ' + model)
            after = bytes(u.mem_read(FRAME, len(before)))
            if result[0] == spec['end']:
                cls = struct.unpack_from('<I', after, spec['cls'])[0]
                struct.pack_into('<I', before, spec['cls'], cls)
                label = 'class-' + str(cls)
            else:
                cls = None
                label = spec['boundaries'][result[0]]
            if after != bytes(before):
                raise AssertionError('Profile slice changed unrelated frame bytes')
            counts[label] += 1
            examples.setdefault(label, dict(profile_raw=profile, drive_raw=drive,
                asynchronous_byte=asynchronous, readout_word=readout, preference_raw=preference,
                subtype_raw=subtype, master_byte=master, debug_byte_6f=debug, debug_byte_6a=flags,
                extra_input_variant=variant, boundary=hex(result[0]), frame_class=cls))
        report['models'][model] = dict(cases=len(inputs), counts=dict(counts), examples=examples,
            original_pure_leaf_calls=dict(leaf_calls),
            frame_writes_limited_to_class=True, class_producer_store=hex(spec['end'] - 4))
    report['limits'] = ['Raw settings are not mapped to shutter/drive UI names',
        'Only frame kind0 is covered', 'Pure helper leaves execute; diagnostics stop before execution',
        'No class is forced or patched; these are synthetic native producer inputs',
        'Fresh physical frame profile and sensor acquisition are unverified']
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print('Original target/donor frame-profile slices executed; no capture helpers or camera I/O.')


if __name__ == '__main__':
    main()
