"""Replay native AP/CP capture-status mask checks and the AP event boundary.

The CP status provider is synthetic. Its refresh, reply allocation, transports
and event dispatcher are not executed. Original request encoding, effective-
mask calculation, reply fields, AP decoding and the request/failure branch do
execute. This tests a software status gate, never sensor-position readiness.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from trinity_replay import profile as mode_profile
from cp_metadata_replay import program
from lifecycle_replay import a64_machine
from cp_sequence_replay import machine as thumb_machine


BITS = (1, 10, 11, 17, 19, 22, 25, 6, 21, 24, 13, 23)


@lru_cache(maxsize=2)
def profile(directory):
    image, info, _, _, _ = mode_profile(directory)
    data, model, _, _ = program(directory)
    if model != info['model']:
        raise ValueError('AP/CP model mismatch')
    target = model == 'ILCE-7CM2'
    p = dict(query=0x3539910 if target else 0x3539df8,
             event=0x34a0424 if target else 0x34a08fc,
             event_dispatch=0x24cb2d4 if target else 0x24cb498,
             cp_mask=0xae1432 if target else 0xae1290,
             cp_reply=0xae1f96 if target else 0xae1df4,
             send=int(info['send'], 16), trace=int(info['trace'], 16))
    query = image.instructions(p['query'], 0x120)
    event = image.instructions(p['event'], 0x54)
    if not any(i.mnemonic == 'mov' and i.op_str == 'w2, #0x4040' for i in query):
        raise ValueError('Native capture-status request builder changed')
    if not all(any(i.mnemonic == 'mov' and i.op_str == 'w0, #' + hex(code) for i in event)
               for code in (0x212, 0x213)):
        raise ValueError('Native capture request/failure event branch changed')
    return image, data, p


def cp_reply(directory, packet, flags, excluded):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R4, UC_ARM_REG_R5,
                                   UC_ARM_REG_R6, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)
    _, data, p = profile(directory)
    cpu = thumb_machine(data, ())
    request, status, output, stack, finish = 0x30001000, 0x30002000, 0x30003000, 0x30018000, 0x3001e000
    cpu.mem_write(request, packet)
    cpu.mem_write(status + 8, struct.pack('<II', flags, excluded))
    cpu.mem_write(output - 4, b'\xa5' * 24)
    cpu.mem_write(output, b'\0' * 16)  # Preallocated reply storage; no allocator success is mocked.
    cpu.reg_write(UC_ARM_REG_R0, status)
    cpu.reg_write(UC_ARM_REG_LR, finish | 1)
    cpu.reg_write(UC_ARM_REG_SP, stack)
    phase = 'mask'

    def hook(uc, address, size, unused):
        begin, end = (p['cp_mask'], p['cp_mask'] + 10) if phase == 'mask' else (p['cp_reply'], p['cp_reply'] + 0x28)
        if not begin <= address < end:
            raise ValueError('Status gate reached unhandled CP code: ' + hex(address))

    def write_hook(uc, access, address, size, value, unused):
        if phase == 'reply' and (output <= address and address + size <= output + 16
                                 or address == stack + 0x1c and size == 1):
            return
        raise ValueError('Status gate changed unrelated CP state')

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    cpu.emu_start(p['cp_mask'] | 1, finish, count=10)
    if cpu.reg_read(UC_ARM_REG_PC) != finish:
        raise ValueError('Native effective-mask getter did not return')
    effective = cpu.reg_read(UC_ARM_REG_R0)
    phase = 'reply'
    cpu.mem_write(stack + 0x14, struct.pack('<I', output))
    cpu.reg_write(UC_ARM_REG_R4, struct.unpack_from('<I', packet, 8)[0])
    cpu.reg_write(UC_ARM_REG_R5, request)
    cpu.reg_write(UC_ARM_REG_R6, effective)
    cpu.emu_start(p['cp_reply'] | 1, p['cp_reply'] + 0x28, count=30)
    raw = bytes(cpu.mem_read(output, 16))
    if (cpu.reg_read(UC_ARM_REG_PC) != p['cp_reply'] + 0x28
            or bytes(cpu.mem_read(output - 4, 4)) != b'\xa5' * 4
            or bytes(cpu.mem_read(output + 16, 4)) != b'\xa5' * 4
            or bytes(cpu.mem_read(request, 12)) != packet
            or bytes(cpu.mem_read(status + 8, 8)) != struct.pack('<II', flags, excluded)):
        raise ValueError('Native reply fields changed their inputs or guards')
    return raw, effective


def exchange(directory, *, logical_mask, flags, excluded=0, capture_id=0x12345678):
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2,
                                     UC_ARM64_REG_X3, UC_ARM64_REG_X4, UC_ARM64_REG_X5,
                                     UC_ARM64_REG_X19, UC_ARM64_REG_X20, UC_ARM64_REG_X29,
                                     UC_ARM64_REG_PC, UC_ARM64_REG_LR)
    image, _, p = profile(directory)
    cpu = a64_machine(image, [(p['query'], p['query'] + 0x1f0), (p['event'], p['event'] + 0x54),
                             *[(p[k], p[k] + 4) for k in ('send', 'trace', 'event_dispatch')]])
    args, event_frame = 0x10001000, 0x10008000
    output = event_frame + 0x58
    inputs = struct.pack('<II', capture_id, logical_mask)
    cpu.mem_write(args, inputs)
    cpu.mem_write(output - 4, b'\xa5' * 16)
    cpu.reg_write(UC_ARM64_REG_X0, args)
    cpu.reg_write(UC_ARM64_REG_X1, output)
    result = dict(trace_calls_omitted=0, status_provider_synthetic=True,
                  cp_refresh_executed=False, cp_reply_allocator_executed=False,
                  transport_executed=False, event_dispatcher_executed=False,
                  physical_readiness_verified=False)
    phase = 'request'

    def hook(uc, address, size, unused):
        if phase == 'request' and address == p['trace']:
            result['trace_calls_omitted'] += 1
            uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))
        elif phase == 'request' and address == p['send']:
            if (uc.reg_read(UC_ARM64_REG_X0), uc.reg_read(UC_ARM64_REG_X2),
                    uc.reg_read(UC_ARM64_REG_X3), uc.reg_read(UC_ARM64_REG_X5)) != (0x90040193, 12, 0x4040, 16):
                raise ValueError('Unexpected native status-query transport arguments')
            result['packet'] = bytes(uc.mem_read(uc.reg_read(UC_ARM64_REG_X1), 12)).hex()
            result['reply_address'] = uc.reg_read(UC_ARM64_REG_X4)
            uc.emu_stop()
        elif phase == 'event' and address == p['event_dispatch']:
            if uc.reg_read(UC_ARM64_REG_X0) != event_frame + 0x60:
                raise ValueError('Native event branch used a different event object')
            result['event'] = struct.unpack('<I', uc.mem_read(event_frame + 0x60, 4))[0]
            uc.emu_stop()
        elif phase == 'request' and p['query'] <= address < p['query'] + 0x120:
            pass
        elif phase == 'decode' and p['query'] + 0x120 <= address < p['query'] + 0x1f0:
            pass
        elif phase == 'event' and p['event'] <= address < p['event'] + 0x54:
            pass
        else:
            raise ValueError('Status query reached unhandled AP code: ' + hex(address))

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.emu_start(p['query'], 0x10003000, count=250)
    if 'packet' not in result:
        raise ValueError('Native status query did not reach its transport boundary')
    packet = bytes.fromhex(result['packet'])
    reply, effective = cp_reply(directory, packet, flags, excluded)
    cpu.mem_write(result.pop('reply_address'), reply)  # Byte bridge, no synthetic acknowledgement value.
    phase = 'decode'
    cpu.emu_start(p['query'] + 0x120, p['query'] + 0x1f0, count=100)
    if cpu.reg_read(UC_ARM64_REG_PC) != p['query'] + 0x1f0:
        raise ValueError('Native status reply decoding did not finish')
    status, decoded = struct.unpack('<II', cpu.mem_read(output, 8))
    phase = 'event'
    cpu.reg_write(UC_ARM64_REG_X29, event_frame)
    cpu.reg_write(UC_ARM64_REG_X20, event_frame + 0x60)
    cpu.emu_start(p['event'], p['event'] + 0x54, count=30)
    wire_mask = sum(1 << bit for index, bit in enumerate(BITS) if logical_mask & (1 << index))
    overlap = effective & wire_mask
    expected_decoded = sum(1 << index for index, bit in enumerate(BITS) if overlap & (1 << bit))
    expected_event = 0x1000213 if overlap else 0x1000212
    if (struct.unpack_from('<I', packet, 8)[0] != wire_mask or effective != flags & ~excluded
            or struct.unpack_from('<I', reply, 8)[0] != (0xf001 if overlap else 0xf000)
            or (status, decoded) != (int(bool(overlap)), expected_decoded)
            or result.get('event') != expected_event or bytes(cpu.mem_read(args, 8)) != inputs):
        raise ValueError('Native status-mask exchange or request/failure event differs')
    return dict(result, effective_flags=effective, reply=reply.hex(), ap_status=status,
                decoded_flags=decoded, software_gate_passed=status == 0)


def compare(c2, reference):
    cases = []
    masks = sorted({0, 1, 0xdce, 0x1dce, 0xfff, *[1 << index for index in range(13)]})
    for mask in masks:
        wire = sum(1 << bit for index, bit in enumerate(BITS) if mask & (1 << index))
        for flags, excluded in ((0, 0), (wire, 0), (~wire & 0xffffffff, 0),
                                (wire, wire), (0xffffffff, 0), (0xffffffff, wire)):
            args = dict(logical_mask=mask, flags=flags, excluded=excluded)
            a, b = exchange(c2, **args), exchange(reference, **args)
            if a != b:
                raise ValueError('C2/A7CR status gate differs')
            cases.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-capture-gate/1', paired_cases=len(cases), camera_io=False,
                installable=False, physical_readiness_verified=False, cases=cases)


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
