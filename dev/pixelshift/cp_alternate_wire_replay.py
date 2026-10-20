"""Replay alternate TC's original 40-byte packet and reply-validation boundary.

The same emulator RAM retains the native default selector, frame flag and
ordinal-derived vector. Original packing and XOR checksum instructions run.
Reply bytes are independently SYNTHETIC and injected only after packet tests;
the native branch accepts/rejects them without a supplied hardware return.
No GPIO, serial/DMA transfer, device acknowledgment, exposure or centering runs.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_vector_replay import _vector_sequence, profile as vector_profile
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, vector = vector_profile(directory)
    target = vector['vector'] == 0xaa8738
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, size):
        return list(md.disasm(data[at - 0x108000:at - 0x108000 + size], at))

    def literal(at, size, register, index=0):
        return [v for r, v in literals(code(at, size)) if r == register][index]

    p = dict(pack=0x418d64 if target else 0x418f7c,
             checksum=0xaa7f26 if target else 0xaa7dc0,
             receive=0xaa80f0 if target else 0xaa7f8a,
             accepted=0xaa8168 if target else 0xaa8002,
             rejected=0xaa81dc if target else 0xaa8076)
    helpers = list(dict.fromkeys(int(row.op_str.lstrip('#'), 0)
                                for row in code(p['pack'], 0x28c) if row.mnemonic == 'bl'))
    sizes = [10, 10, 10, 12, 12, 12, 12, 12, 12, 12, 12, 38,
             12, 12, 12, 20, 14, 12, 12, 42, 14, 14, 56]
    if len(helpers) != len(sizes) or helpers[0] != vector['shared'] or helpers[16] != vector['vector_flag']:
        raise ValueError('Native alternate packet helper layout changed')
    p['packet'] = literal(helpers[1], 10, 'r0')
    p['cached_flag'] = literal(helpers[22] + 0x2c, 12, 'r1')
    if literal(helpers[2], 10, 'r0') != vector['vector_data']:
        raise ValueError('Original packet no longer reads the native ordinal-vector block')
    nested = [int(row.op_str.lstrip('#'), 0) for row in code(helpers[19], sizes[19]) if row.mnemonic == 'bl']
    if len(nested) != 2:
        raise ValueError('Native packet auxiliary branch changed')
    p['regions'] = [(p['pack'], p['pack'] + 0x28c), (p['checksum'], p['checksum'] + 0x36),
                    (p['receive'], p['accepted'])]
    p['regions'] += [(at, at + size) for at, size in zip(helpers, sizes)]
    # Only the inspected pure predicate runs; its hardware-dependent true branch is outside the replay.
    p['regions'].append((nested[0], nested[0] + 0x22))
    p['rx'] = literal(p['receive'], 0x14, 'r1')
    p['snapshot'] = literal(p['accepted'] - 0x1c, 0x1c, 'r1')
    if p['snapshot'] != p['rx'] + 40:
        raise ValueError('Inspected native RX/snapshot adjacency changed')
    p['pages'] = sorted({v & ~4095 for begin, end in p['regions']
                         for _, v in literals(code(begin, end - begin))
                         if 0x1100000 <= v < 0x2000000})
    return data, p


def wire_sequence(directory, *, scales=None):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_SP, UC_ARM_REG_PC
    data, p = profile(directory)
    stack, finish = 0x3001f000, 0x3001e000

    def observe(cpu, vector_profile, ordinal, vector):
        for page in p['pages']:
            if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
                cpu.mem_map(page, 4096)
        phase, outcome = 'pack', None
        allowed = dict(pack=[(p['packet'], 40), (p['cached_flag'], 1)], checksum=[(p['packet'] + 38, 2)],
                       receive=[(p['snapshot'], 40)])
        cpu.mem_write(p['packet'] - 4, b'\x6b' * 4 + bytes(40) + b'\x6b' * 4)
        before_vector = bytes(cpu.mem_read(vector_profile['vector_data'], 13))

        def hook(uc, address, size, unused):
            nonlocal outcome
            if phase == 'receive' and address in (p['accepted'], p['rejected']):
                outcome = 'accepted' if address == p['accepted'] else 'rejected'
                uc.emu_stop()
                return
            if not any(lo <= address and address + size <= hi for lo, hi in p['regions']):
                raise ValueError('Alternate wire replay reached omitted ' + phase + ' code: ' + hex(address))

        def write_hook(uc, access, address, size, value, unused):
            if stack - 512 <= address and address + size <= stack:
                return
            if not any(lo <= address and address + size <= lo + n for lo, n in allowed[phase]):
                raise ValueError('Alternate wire replay changed unrelated ' + phase + ' state: ' + hex(address))

        def run(at, end=finish):
            cpu.reg_write(UC_ARM_REG_SP, stack)
            cpu.reg_write(UC_ARM_REG_LR, finish | 1)
            cpu.emu_start(at | 1, end, count=5000)
            if outcome is None and cpu.reg_read(UC_ARM_REG_PC) != end:
                raise ValueError('Original packet slice did not reach its boundary')

        ch = cpu.hook_add(UC_HOOK_CODE, hook)
        wh = cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
        run(p['pack'])
        phase = 'checksum'
        run(p['checksum'], p['checksum'] + 0x36)
        packet = bytes(cpu.mem_read(p['packet'], 40))
        expected_xor = 0x0f0f
        for word in struct.unpack('<19H', packet[:38]):
            expected_xor ^= word
        if (packet[:4] != bytes([0x39, 8, 8, 2]) or list(struct.unpack_from('<3i', packet, 4)) != vector
                or packet[28] != 1 or struct.unpack_from('<H', packet, 38)[0] != expected_xor
                or bytes(cpu.mem_read(vector_profile['vector_data'], 13)) != before_vector
                or bytes(cpu.mem_read(p['packet'] - 4, 4)) != b'\x6b' * 4
                or bytes(cpu.mem_read(p['packet'] + 40, 4)) != b'\x6b' * 4):
            raise ValueError('Native alternate packet lost vector, TRINITY, checksum or bounds')
        phase = 'receive'
        results = []
        for case in ('valid', 'wrong_type', 'wrong_checksum'):
            reply = bytearray(40)
            reply[2] = 9 if case == 'wrong_type' else 8
            # Unrelated synthetic signed/control fields ensure the full native copy is checked.
            struct.pack_into('<3h', reply, 4, -17 - ordinal, 31 + ordinal, -5)
            struct.pack_into('<2h', reply, 34, -300 + ordinal, 400 - ordinal)
            check = 0x0f0f
            for word in struct.unpack('<18H', reply[2:38]):
                check ^= word
            struct.pack_into('<H', reply, 38, check ^ (1 if case == 'wrong_checksum' else 0))
            # These native buffers are adjacent; an internal canary would corrupt the reply checksum.
            cpu.mem_write(p['rx'] - 4, b'\x7c' * 4 + reply + b'\x8d' * 40 + b'\x7c' * 4)
            outcome = None
            run(p['receive'], 0)
            accepted = outcome == 'accepted'
            if (outcome is None or accepted != (case == 'valid')
                    or bytes(cpu.mem_read(p['snapshot'], 40)) != (bytes(reply) if accepted else b'\x8d' * 40)
                    or bytes(cpu.mem_read(p['snapshot'] + 40, 4)) != b'\x7c' * 4
                    or bytes(cpu.mem_read(p['rx'] - 4, 44)) != b'\x7c' * 4 + reply
                    or bytes(cpu.mem_read(p['packet'], 40)) != packet):
                raise ValueError('Native alternate reply acceptance/copy/bounds differ from its branch')
            results.append(dict(input=case, native_validation_branch=outcome,
                                complete_40_byte_copy=accepted))
        cpu.hook_del(ch)
        cpu.hook_del(wh)
        return dict(packet=packet.hex(), packet_vector_raw=list(struct.unpack_from('<3i', packet, 4)),
                    trinity=packet[28], native_xor_checksum=True, reply_cases=results,
                    synthetic_reply_bytes=True, receive_slice_only=True,
                    transport_executed=False, hardware_acknowledgment_verified=False,
                    exposure_or_centering_executed=False, physical_shift_verified=False)

    previous = _vector_sequence(directory, scales=scales, observe_vector=observe)
    return dict(shots=[s['wire'] for s in previous['shots']], original_scale_bytes=previous['original_scale_bytes'],
                synthetic_scales=scales is not None, camera_io=False, installable=False)


def compare(c2, reference):
    cases = []
    for scales in (None, (3, 5, 7)):
        a, b = wire_sequence(c2, scales=scales), wire_sequence(reference, scales=scales)
        if a != b:
            raise ValueError('C2/A7CR native alternate packet/validation behavior differs')
        cases.append(dict(scales=scales, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-cp-alternate-wire/1', paired_sequences=2,
                paired_packets=8, paired_reply_cases=24, cases=cases, camera_io=False,
                installable=False, hardware_acknowledgment_verified=False, physical_shift_verified=False)


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
    print(json.dumps({key: report[key] for key in ('paired_packets', 'paired_reply_cases', 'camera_io', 'installable')}))


if __name__ == '__main__':
    main()
