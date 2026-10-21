"""Trace native alternate-TC ordinal and TRINITY into a control-vector slice.

Original frame-flag export, 192-byte publication/snapshot copy and ordinal
vector calculation execute. Capture scheduling, the rest of the producer,
wire packing/transfer and actuators do not. Factory scale bytes are loaded
through native BK4 code; optional nonzero scales are SYNTHETIC sensitivity
inputs, not camera settings, pixel units or a proposed hardware patch.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_alternate_replay import _sequence, profile as alternate_profile
from cp_defaults_replay import factory_bank
from cp_serial_replay import literals, profile as serial_profile


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, alt = alternate_profile(directory)
    _, serial = serial_profile(directory)
    target = alt['alternate'] == 0xaa5c08
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, size):
        return list(md.disasm(data[at - 0x108000:at - 0x108000 + size], at))

    def literal(at, size, register, index=0):
        return [v for r, v in literals(code(at, size)) if r == register][index]

    p = dict(flag_slice=serial['frame_slice'] + 14, flag_setter=serial['flag_setter'],
             export=0x41c530 if target else 0x41c748,
             flag_getter=serial['flag_getter'], flag=serial['flag'],
             export_root=0x1a07d04 if target else 0x1a06ab4,
             publish=0xaa90c0 if target else 0xaa8f5a,
             snapshot=0xaa8dc4 if target else 0xaa8c5e,
             vector=0xaa8738 if target else 0xaa85d2,
             stop=0xaa87ce if target else 0xaa8668)
    p['vector_flag'] = int(code(p['vector'], 4)[0].op_str.lstrip('#'), 0)
    p['ordinal_getter'] = 0xaa9898 if target else 0xaa9732
    p['shared'] = alt['shared']
    p['shared_state'] = alt['shared_state']
    p['bank'] = literal(p['publish'], 0x24, 'r4')
    p['buffers'] = literal(p['publish'] + 0x1e, 0x1e, 'r0')
    p['snapshot_data'] = literal(p['snapshot'], 0x22, 'r0', -1)
    p['scales'] = literal(p['vector'] + 0x174, 0x20, 'r6') + 0x70
    p['vector_data'] = literal(p['vector'] + 0x19a, 0x12, 'r4')
    p['copy'] = 0x61e60c if target else 0x61e824
    p['regions'] = [(p['flag_slice'], p['flag_slice'] + 16),
                    (p['flag_setter'], p['flag_setter'] + 14),
                    (p['flag_getter'], p['flag_getter'] + 14),
                    (p['export'], p['export'] + 12),
                    (p['publish'], p['publish'] + 0x4c),
                    (p['snapshot'], p['snapshot'] + 0x26),
                    (p['vector'], p['vector'] + 0x20),
                    (p['vector'] + 0xf8, p['vector'] + 0x20a),
                    (p['vector_flag'], p['vector_flag'] + 14),
                    (p['ordinal_getter'], p['ordinal_getter'] + 12),
                    (p['shared'], p['shared'] + 10),
                    (p['copy'], p['copy'] + 0x300)]
    return data, p


def _vector_sequence(directory, *, scales=None, exponent=0, observe_vector=None, vector_producer=None):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
                                   UC_ARM_REG_R4, UC_ARM_REG_R10, UC_ARM_REG_SP,
                                   UC_ARM_REG_LR, UC_ARM_REG_PC)
    if scales is not None and (len(scales) != 3 or any(not 0 <= x <= 127 for x in scales)):
        raise ValueError('Sensitivity scales must be three nonnegative synthetic bytes')
    if not 0 <= exponent <= 20:
        raise ValueError('Needs a bounded synthetic shift exponent')
    data, p = profile(directory)
    frame, source, stack, finish = 0x30006000, 0x30008000, 0x3001f000, 0x3001e000
    first, original_scales = True, None

    def observe(cpu, alt, default, ordinal):
        nonlocal first, original_scales
        def map_at(address, size):
            for page in range(address & ~4095, (address + size + 4095) & ~4095, 4096):
                if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
                    cpu.mem_map(page, 4096)

        for address, size in [(p['export_root'], 4), (p['buffers'], 384),
                              (p['snapshot_data'], 192), (p['scales'] - 0x70, 256),
                              (p['vector_data'], 16)]:
            map_at(address, size)
        phase, copies, omitted_locks = 'load', [], []
        loaded = p['scales'] - 0x70
        writes = dict(load=[(loaded, 256)], flag=[(p['flag'], 1)],
                      export=[(source + 0x6f, 1)],
                      publish=[(p['buffers'], 384), (p['bank'], 1)],
                      snapshot=[(p['snapshot_data'], 192)],
                      vector=[(p['vector_data'], 13)])

        def hook(uc, address, size, unused):
            if phase == 'load' and address in default['locks']:
                # Same void mutex boundary as the defaults loader; no success supplied.
                uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1)
                omitted_locks.append(address)
                return
            regions = default['regions'] if phase == 'load' else p['regions']
            if not any(lo <= address and address + size <= hi for lo, hi in regions):
                raise ValueError('Control-vector replay reached omitted ' + phase + ' code: ' + hex(address))
            if address == p['copy']:
                copies.append((phase, uc.reg_read(UC_ARM_REG_R0),
                               uc.reg_read(UC_ARM_REG_R1), uc.reg_read(UC_ARM_REG_R2)))

        def write_hook(uc, access, address, size, value, unused):
            if stack - 512 <= address and address + size <= stack:
                return
            if not any(lo <= address and address + size <= lo + n for lo, n in writes[phase]):
                raise ValueError('Control-vector replay changed unrelated ' + phase + ' state: ' + hex(address))

        def run(at, end=finish, balanced=True):
            cpu.reg_write(UC_ARM_REG_SP, stack)
            cpu.reg_write(UC_ARM_REG_LR, finish | 1)
            cpu.emu_start(at | 1, end, count=4000)
            if cpu.reg_read(UC_ARM_REG_PC) != end or (balanced and cpu.reg_read(UC_ARM_REG_SP) != stack):
                raise ValueError('Native control-vector slice did not reach its bounded end')

        ch = cpu.hook_add(UC_HOOK_CODE, hook)
        wh = cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
        if first:
            index = 37
            ident = struct.unpack('<I', cpu.mem_read(default['ids'] + index * 4, 4))[0]
            destination = struct.unpack('<I', cpu.mem_read(default['destinations'] + index * 4, 4))[0]
            if ident != 0x000f0025 or destination != loaded:
                raise ValueError('Native control-vector scale binding changed')
            cpu.reg_write(UC_ARM_REG_R0, default['ids'] + index * 4)
            cpu.reg_write(UC_ARM_REG_R1, default['destinations'] + index * 4)
            run(default['initialize'], default['initialize'] + 0x6a, balanced=False)
            _, bank = factory_bank(directory, 0)
            if (cpu.reg_read(UC_ARM_REG_R0) != 256 or len(copies) != 1
                    or copies[0][1] != loaded or copies[0][3] != 256):
                raise ValueError('Native scale parameter copy was not a complete binding load')
            start = copies[0][2] - 0x4000000
            if not 0 <= start <= len(bank) - 256 or bytes(cpu.mem_read(loaded, 256)) != bank[start:start + 256]:
                raise ValueError('Native control-vector parameter differs from its actual BK4 source')
            original_scales = list(cpu.mem_read(p['scales'], 3))
            if scales is not None:
                cpu.mem_write(p['scales'], bytes(scales))
            cpu.mem_write(p['shared_state'] + 0x8c, bytes([0, exponent]))
            cpu.mem_write(p['export_root'], struct.pack('<I', source))
            cpu.mem_write(p['bank'], bytes(1))
            first = False
        before_ordinal = bytes(cpu.mem_read(alt['observed'], 32))
        cpu.mem_write(frame, bytes(0x100))
        cpu.mem_write(frame + 0x98, struct.pack('<I', 1))
        cpu.mem_write(source, bytes(192))
        phase = 'flag'
        cpu.reg_write(UC_ARM_REG_R4, frame + 0x20)
        run(p['flag_slice'], p['flag_slice'] + 16)
        phase = 'export'
        cpu.reg_write(UC_ARM_REG_R10, p['export_root'])
        run(p['export'], p['export'] + 12)
        exported = bytes(cpu.mem_read(source, 192))
        if exported[0x6f] != 1:
            raise ValueError('Original frame/export slices did not propagate TRINITY')
        phase = 'publish'
        # ABI bridge for an original by-value 192-byte function argument.
        words = struct.unpack('<4I', exported[:16])
        for register, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), words):
            cpu.reg_write(register, value)
        cpu.mem_write(stack, exported[16:])
        run(p['publish'])
        phase = 'snapshot'
        cpu.reg_write(UC_ARM_REG_R2, 192)
        run(p['snapshot'], p['snapshot'] + 0x26)
        if bytes(cpu.mem_read(p['snapshot_data'], 192)) != exported:
            raise ValueError('Native 192-byte flag publication/snapshot lost source bytes')
        phase = 'vector'
        producer_report = None
        if vector_producer is None:
            cpu.mem_write(p['vector_data'] - 4, b'\x6b' * 24)
        neighbors = bytes(cpu.mem_read(p['vector_data'] - 4, 24))
        if vector_producer is None:
            run(p['vector'], p['stop'])
        else:
            # A full producer continuation retains its own prior vector state;
            # do not precompute/seed it through the conditional slice above.
            cpu.hook_del(ch)
            cpu.hook_del(wh)
            producer_report = vector_producer(cpu, p, ordinal)
            ch = cpu.hook_add(UC_HOOK_CODE, hook)
            wh = cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
        vector = list(struct.unpack('<3i', cpu.mem_read(p['vector_data'], 12)))
        factor = 1 << (exponent or 13)
        selected_scales = original_scales if scales is None else list(scales)
        pattern = [(0, 0), (2, 0), (2, 2), (0, 2)][ordinal]
        expected = [pattern[0] * selected_scales[0] * factor,
                    pattern[0] * selected_scales[1] * factor,
                    pattern[1] * selected_scales[2] * factor]
        if (vector != expected or cpu.mem_read(p['vector_data'] + 12, 1)[0] != 2
                or bytes(cpu.mem_read(alt['observed'], 32)) != before_ordinal
                or bytes(cpu.mem_read(p['vector_data'] - 4, 4)) != neighbors[:4]
                or bytes(cpu.mem_read(p['vector_data'] + 13, 7)) != neighbors[-7:]):
            raise ValueError('Native ordinal vector differs from inspected four-step pattern or bounds')
        for name, expected_length in [('publish', 192), ('snapshot', 192)]:
            if len([c for c in copies if c[0] == name and c[3] == expected_length]) != 1:
                raise ValueError('Native complete flag-copy instruction was not executed')
        cpu.hook_del(ch)
        cpu.hook_del(wh)
        result = dict(vector_raw=vector, native_pattern_mode=2, original_scale_bytes=original_scales,
                    sensitivity_scales_synthetic=scales is not None,
                    native_frame_flag_exported=True, native_shared_copy_bytes=192,
                    ordinal_unchanged=True, producer_slice_only=vector_producer is None,
                    scale_load_mutex_calls_omitted=len(omitted_locks),
                    physical_units_verified=False, serial_transport_executed=False,
                    physical_shift_verified=False)
        if producer_report is not None:
            result['producer'] = producer_report
        if observe_vector is not None:
            result['wire'] = observe_vector(cpu, p, ordinal, vector)
        return result

    result = _sequence(directory, shared_flag=1, gate=1, first=1, observe=observe)
    return dict(original_scale_bytes=original_scales, shots=[s['observation'] for s in result['shots']],
                interface_selector_preserved=result['official_selector_preserved'],
                synthetic_frame_and_shared_state=True, camera_io=False, installable=False)


def vector_sequence(directory, *, scales=None, exponent=0):
    return _vector_sequence(directory, scales=scales, exponent=exponent)


def compare(c2, reference):
    cases = []
    for scales, exponent in [(None, 0), ((3, 5, 7), 0), ((3, 5, 7), 12)]:
        a, b = vector_sequence(c2, scales=scales, exponent=exponent), vector_sequence(reference, scales=scales, exponent=exponent)
        if a != b:
            raise ValueError('C2/A7CR native ordinal vector propagation differs')
        cases.append(dict(scales=scales, exponent=exponent, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-cp-vector/1', paired_sequences=3, paired_cases=12,
                cases=cases, camera_io=False, installable=False, physical_shift_verified=False)


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
