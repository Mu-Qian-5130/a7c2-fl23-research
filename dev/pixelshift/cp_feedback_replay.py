"""Follow a validated alternate reply through its native decoder and getters.

Continues in the wire replay's RAM after its original 40-byte accepted copy.
The decoder extracts three halfwords, updates a native 20-entry history ring,
and its getters sign-extend the values. History inputs are SYNTHETIC. This is
not the separate first-phase reply decoder, live feedback, position units, sensor
settling or a capture-admission test. No hardware call or success is supplied.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_alternate_wire_replay import wire_sequence, profile as wire_profile
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, wire = wire_profile(directory)
    target = wire['receive'] == 0xaa80f0
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, size):
        return list(md.disasm(data[at - 0x108000:at - 0x108000 + size], at))

    def literal(at, size, register):
        return [v for r, v in literals(code(at, size)) if r == register][0]

    p = dict(decode=0xaa9026 if target else 0xaa8ec0,
             getter=0xaa92a2 if target else 0xaa913c,
             copy=0x61e60c if target else 0x61e824)
    calls = [int(i.op_str.lstrip('#'), 0) for i in code(p['decode'], 0x9a) if i.mnemonic == 'bl']
    if len(calls) != 3 or len(set(calls)) != 1:
        raise ValueError('Alternate reply decoder getter layout changed')
    p['snapshot_getter'] = calls[0]
    if literal(calls[0], 10, 'r0') != wire['snapshot']:
        raise ValueError('Alternate decoder does not read the validated 40-byte snapshot')
    p['values'] = literal(p['decode'] + 10, 12, 'r4')
    if literal(p['getter'], 14, 'r1') != p['values']:
        raise ValueError('Signed feedback getter reads a different output block')
    p['source_pointer'] = literal(p['decode'] + 0x24, 12, 'r0')
    p['index'] = literal(p['decode'] + 0x38, 12, 'r0')
    p['ring'] = literal(p['decode'] + 0x44, 12, 'r0')
    p['previous'] = literal(p['decode'] + 0x7c, 16, 'r0')
    p['regions'] = [(p['decode'], p['decode'] + 0x9a),
                    (p['snapshot_getter'], p['snapshot_getter'] + 10),
                    (p['getter'], p['getter'] + 14), (p['copy'], p['copy'] + 0x300)]
    return data, p


def feedback_sequence(directory):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R2, UC_ARM_REG_SP,
                                   UC_ARM_REG_PC, UC_ARM_REG_LR)
    _, p = profile(directory)
    context, stack, finish = 0x30012000, 0x3001f000, 0x3001e000

    def observe(cpu, wire, ordinal, case, accepted):
        if not accepted:
            return None
        for address, length in ((p['values'] - 4, 14), (p['source_pointer'], 4),
                                (p['index'], 4), (p['ring'] - 4, 328), (p['previous'], 4)):
            for page in range(address & ~4095, (address + length + 4095) & ~4095, 4096):
                if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
                    cpu.mem_map(page, 4096)
        snapshot = bytes(cpu.mem_read(wire['snapshot'], 40))
        expected_values = list(struct.unpack_from('<3h', snapshot, 4))
        cases, copies, phase = [], [], 'decode'
        output_index = 0

        def hook(uc, address, size, unused):
            if not any(lo <= address and address + size <= hi for lo, hi in p['regions']):
                raise ValueError('Feedback replay reached omitted code: ' + hex(address))
            if address == p['copy']:
                copies.append(uc.reg_read(UC_ARM_REG_R2))

        def write_hook(uc, access, address, size, value, unused):
            if stack - 512 <= address and address + size <= stack:
                return
            allowed = [] if phase == 'getter' else [(p['values'], 6), (p['index'], 4),
                       (p['previous'], 4), (p['ring'] + output_index * 16, 16)]
            if not any(lo <= address and address + size <= lo + n for lo, n in allowed):
                raise ValueError('Feedback decoder wrote unrelated state: ' + hex(address))

        def run(at):
            cpu.reg_write(UC_ARM_REG_SP, stack)
            cpu.reg_write(UC_ARM_REG_LR, finish | 1)
            cpu.emu_start(at | 1, finish, count=2000)
            if cpu.reg_read(UC_ARM_REG_PC) != finish or cpu.reg_read(UC_ARM_REG_SP) != stack:
                raise ValueError('Native feedback decoder did not finish with balanced stack')

        ch = cpu.hook_add(UC_HOOK_CODE, hook)
        wh = cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
        for source_kind in (0, 6, 1):
            for output_index in (0, 19):
                phase = 'decode'
                initial = bytearray(b'\x8d' * 320)
                prior = bytes((i + ordinal * 17) & 255 for i in range(16))
                initial[7 * 16:8 * 16] = prior
                source = bytearray(b'\xa5' * 64)
                source[11:27] = bytes((255 - i - ordinal * 17) & 255 for i in range(16))
                source[28] = source_kind
                cpu.mem_write(context, bytes(source))
                cpu.mem_write(p['source_pointer'], struct.pack('<I', context))
                cpu.mem_write(p['index'], struct.pack('<I', output_index))
                cpu.mem_write(p['previous'], struct.pack('<I', 7))
                # Adjacent bytes contain other live native flags, including the
                # publisher's bank selector. Preserve them instead of planting canaries.
                ring_neighbors = bytes(cpu.mem_read(p['ring'] - 4, 328))
                value_neighbors = bytes(cpu.mem_read(p['values'] - 4, 14))
                cpu.mem_write(p['ring'], bytes(initial))
                cpu.mem_write(p['values'], b'\x7c' * 6)
                before_copies = len(copies)
                run(p['decode'])
                phase = 'getter'
                actual = []
                for axis in range(3):
                    cpu.reg_write(UC_ARM_REG_R0, axis)
                    run(p['getter'])
                    value = cpu.reg_read(UC_ARM_REG_R0)
                    actual.append(value if value < 0x80000000 else value - 0x100000000)
                expected = initial[:]
                expected[output_index * 16:(output_index + 1) * 16] = (source[11:27]
                    if source_kind in (0, 6) else prior)
                if (actual != expected_values
                        or bytes(cpu.mem_read(p['values'], 6)) != snapshot[4:10]
                        or bytes(cpu.mem_read(p['values'] - 4, 4)) != value_neighbors[:4]
                        or bytes(cpu.mem_read(p['values'] + 6, 4)) != value_neighbors[-4:]
                        or bytes(cpu.mem_read(p['ring'] - 4, 328)) != ring_neighbors[:4] + expected + ring_neighbors[-4:]
                        or struct.unpack('<I', cpu.mem_read(p['index'], 4))[0] != (output_index + 1) % 20
                        or struct.unpack('<I', cpu.mem_read(p['previous'], 4))[0] != output_index
                        or bytes(cpu.mem_read(wire['snapshot'], 40)) != snapshot
                        or bytes(cpu.mem_read(context, 64)) != source
                        or copies[before_copies:] != [16]):
                    raise ValueError('Native feedback fields, history, signed values or bounds differ')
                cases.append(dict(source_kind=source_kind, initial_index=output_index,
                                  next_index=(output_index + 1) % 20, signed_values=actual,
                                  history_source='context' if source_kind in (0, 6) else 'previous_entry',
                                  native_history_copy_bytes=16))
        cpu.hook_del(ch)
        cpu.hook_del(wh)
        return dict(cases=cases, physical_units_verified=False, settling_verified=False)

    result = wire_sequence(directory, observe_reply=observe)
    return dict(shots=[r['observation'] for s in result['shots'] for r in s['reply_cases']
                      if r['input'] == 'valid'], camera_io=False, installable=False,
                synthetic_reply_and_history=True, physical_shift_verified=False,
                hardware_acknowledgment_verified=False)


def compare(c2, reference):
    a, b = feedback_sequence(c2), feedback_sequence(reference)
    if a != b:
        raise ValueError('C2/A7CR native alternate reply decoding differs')
    return dict(schema='a7c2-pixelshift-cp-feedback/1',
                paired_cases=sum(len(shot['cases']) for shot in a['shots']),
                target=a, reference=b, camera_io=False, installable=False,
                physical_shift_verified=False, settling_verified=False)


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
