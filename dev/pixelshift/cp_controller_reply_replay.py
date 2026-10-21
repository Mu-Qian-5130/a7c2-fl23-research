"""Feed H8-generated reply payloads through original CP validation/decoding.

This replays the post-transport receive side only. H8 peripheral inputs,
framing and CP history/context are synthetic; no camera, genuine feedback,
command/feedback timing or capture is modeled. Valid payload bytes are never
repaired or re-encoded by the host before native CP validation.
"""
import argparse
import json
from pathlib import Path
import struct

from cp_alternate_wire_replay import profile as wire_profile
from cp_feedback_replay import profile as feedback_profile
from cp_sequence_replay import machine


def decode_reply(directory, payload):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_PC,
                                   UC_ARM_REG_SP, UC_ARM_REG_LR)
    payload = bytes(payload)
    if len(payload) != 40:
        raise ValueError('Expected the complete 40-byte controller reply payload')
    data, w = wire_profile(directory)
    _, f = feedback_profile(directory)
    cpu = machine(data, [])
    for address, length in ((w['rx'], 80), (f['values'], 6), (f['source_pointer'], 4),
                            (f['ring'], 320), (f['index'], 4), (f['previous'], 4)):
        for page in range(address & ~4095, (address + length + 4095) & ~4095, 4096):
            if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
                cpu.mem_map(page, 4096)
    context, stack, finish = 0x30010000, 0x3001f000, 0x3001e000
    source = bytearray(b'\xa5' * 64)
    source[0x1c] = 0
    cpu.mem_write(context, bytes(source))
    cpu.mem_write(f['source_pointer'], struct.pack('<I', context))
    cpu.mem_write(f['index'], bytes(4))
    cpu.mem_write(f['previous'], struct.pack('<I', 7))
    cpu.mem_write(f['ring'], b'\x6b' * 320)
    cpu.mem_write(w['snapshot'], b'\x8d' * 40)
    phase, outcome, copies = 'receive', None, []

    def hook(uc, address, size, unused):
        nonlocal outcome
        if phase == 'receive' and address in (w['accepted'], w['rejected']):
            outcome = 'accepted' if address == w['accepted'] else 'rejected'
            uc.emu_stop()
            return
        regions = [(w['receive'], w['accepted'])] if phase == 'receive' else f['regions']
        if not any(lo <= address and address + size <= hi for lo, hi in regions):
            raise ValueError('Controller-reply replay reached omitted code: ' + hex(address))
        if address == f['copy']:
            from unicorn.arm_const import UC_ARM_REG_R2
            copies.append(uc.reg_read(UC_ARM_REG_R2))

    def write_hook(uc, access, address, size, value, unused):
        if stack - 512 <= address and address + size <= stack:
            return
        allowed = ([(w['snapshot'], 40)] if phase == 'receive' else
                   [(f['values'], 6), (f['ring'], 16), (f['index'], 4), (f['previous'], 4)]
                   if phase == 'decode' else [])
        if not any(lo <= address and address + size <= lo + n for lo, n in allowed):
            raise ValueError('Controller-reply replay wrote unrelated state: ' + hex(address))

    def run(at, end=finish):
        cpu.reg_write(UC_ARM_REG_SP, stack)
        cpu.reg_write(UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(at | 1, end, count=4000)
        if phase != 'receive' and (cpu.reg_read(UC_ARM_REG_PC) != end
                                  or cpu.reg_read(UC_ARM_REG_SP) != stack):
            raise ValueError('Native CP reply decoder/getter did not finish with balanced stack')

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    damaged = bytearray(payload)
    damaged[38] ^= 1
    cpu.mem_write(w['rx'], bytes(damaged))
    run(w['receive'], 0)
    if outcome != 'rejected' or bytes(cpu.mem_read(w['snapshot'], 40)) != b'\x8d' * 40:
        raise ValueError('Native CP accepted the corrupt controller checksum or changed its snapshot')
    outcome = None
    cpu.mem_write(w['rx'], payload)
    run(w['receive'], 0)
    if outcome != 'accepted' or bytes(cpu.mem_read(w['snapshot'], 40)) != payload:
        raise ValueError('Native CP did not accept/copy the exact controller-generated payload')
    phase = 'decode'
    run(f['decode'])
    phase = 'getter'
    values = []
    for axis in range(3):
        cpu.reg_write(UC_ARM_REG_R0, axis)
        run(f['getter'])
        value = cpu.reg_read(UC_ARM_REG_R0)
        values.append(value if value < 0x80000000 else value - 0x100000000)
    if (bytes(cpu.mem_read(w['snapshot'], 40)) != payload
            or bytes(cpu.mem_read(f['values'], 6)) != payload[4:10]
            or bytes(cpu.mem_read(f['ring'], 16)) != source[11:27]
            or copies != [16] or bytes(cpu.mem_read(context, 64)) != source):
        raise ValueError('Native reply decoding changed its source or history-copy contract')
    return dict(values=values, complete_40_byte_copy=True, native_signed_getters_executed=True,
                bad_checksum_rejected=True, native_history_copy_bytes=16,
                payload_reencoded_by_host=False, transport_executed=False,
                physical_feedback_verified=False)


def compare(c2, reference, h8_report):
    cases = []
    for row in h8_report['cases']:
        payload = bytes.fromhex(row['native_reply_payload'])
        a, b = decode_reply(c2, payload), decode_reply(reference, payload)
        if a != b or a['values'] != row['reply_words']:
            raise ValueError('H8-generated peripheral words differ from native C2/A7CR decoding')
        cases.append(dict(label=row['label'], bank=row['bank'], target=a, reference=b))
    return dict(schema='a7c2-pixelshift-controller-reply/1', paired_payloads=len(cases),
                cases=cases, receive_side_only=True, synthetic_peripheral_inputs=True,
                command_and_feedback_scheduling_executed=False, camera_io=False,
                installable=False, physical_shift_verified=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--h8-report', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    report = compare(args.c2, args.reference, json.loads(args.h8_report.read_text(encoding='utf-8')))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps({key: report[key] for key in ('paired_payloads', 'camera_io', 'installable')}))


if __name__ == '__main__':
    main()
