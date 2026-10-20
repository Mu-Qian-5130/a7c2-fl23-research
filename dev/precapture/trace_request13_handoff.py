"""Native target request13 handoff to formal recording-reference callbacks.

Runs original control/getter/packet-store/bridge instructions on synthetic
objects. Stops before real timer reads, request sends or callback enqueues.
No hardware response or successful OS operation is fabricated.
"""
import argparse
import hashlib
import itertools
import json
import struct
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import (
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
    UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R8,
    UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11, UC_ARM_REG_SP,
)
from support.reference import SPECS
from trace_shutter_edges import NativeEdges

MEM, STACK = 0x30000000, 0x40000000


def word(v):
    return struct.pack('<I', v)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    cp = a.cp.read_bytes()
    if hashlib.sha256(cp).hexdigest() != SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported original target')
    u = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    for at, size in [(0x350000, 0x1000), (0x9D9000, 4096), (0x9DA000, 4096), (0x9DB000, 4096),
                     (0x3AE000, 4096), (0x69F000, 4096)]:
        u.mem_map(at, size);u.mem_write(at, cp[at:at + size])
    u.mem_map(MEM, 0x4000);u.mem_map(STACK, 0x4000)
    stops, observed = set(), []

    def stop(cpu, address, size, user):
        if address in stops:
            observed.append((address, [cpu.reg_read(r) for r in
                                      [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3]]))
            cpu.emu_stop()

    u.hook_add(UC_HOOK_CODE, stop)

    def run(start, boundaries):
        nonlocal stops
        stops = set(boundaries)
        before = len(observed)
        u.emu_start(start | 1, 0xFFFFFFFF, count=100)
        assert len(observed) == before + 1
        return observed[-1]

    references = NativeEdges(cp)
    cases = []
    for active13, pressed, subtype, context in itertools.product([0, 1], [0, 1], [1, 2, 13], [0, 0x12345678]):
        u.mem_write(MEM, bytes(0x4000))
        u.mem_write(MEM + 0x158 + 13 * 16 + 0x14, bytes([active13]))
        before = bytes(u.mem_read(MEM, 0x400))
        u.reg_write(UC_ARM_REG_SP, STACK + 0x3000)
        if pressed:
            for reg, value in [(UC_ARM_REG_R4, MEM), (UC_ARM_REG_R9, subtype), (UC_ARM_REG_R11, context)]:
                u.reg_write(reg, value)
            boundary, args = run(0x350AA4, [0x69F488, 0x350ACA])
            assert boundary == (0x69F488 if active13 else 0x350ACA)
            if active13:
                # Explicit input to a post-timer slice, not a mocked return
                # from a hardware timer. No claimed timestamp unit/rate.
                u.reg_write(UC_ARM_REG_R0, 0x89ABCDEF)
                boundary, args = run(0x350ABC, [0x9DBCCA])
        else:
            for reg, value in [(UC_ARM_REG_R10, MEM), (UC_ARM_REG_R5, subtype), (UC_ARM_REG_R9, context)]:
                u.reg_write(reg, value)
            boundary, args = run(0x350E60, [0x9DBCCA, 0x9DA59E, 0x350E7C])
            wanted = 0x350E7C if not active13 else (0x9DA59E if subtype == 13 else 0x9DBCCA)
            assert boundary == wanted
        assert bytes(u.mem_read(MEM, 0x400)) == before
        item = {'request13_active': active13, 'pressed': pressed, 'subtype': subtype,
                'context': context, 'boundary': hex(boundary), 'native_queue_unchanged': True}
        if boundary == 0x9DBCCA:
            assert args == [pressed, subtype, context, 0x89ABCDEF if pressed else 0]
            # Native notification constructor field stores, starting after
            # allocation with an explicit synthetic buffer input. Constructor
            # allocation/send are never executed or replaced with success.
            packet = MEM + 0x1000
            u.mem_write(packet, bytes(24))
            u.mem_write(STACK + 0x3000 + 0x14, word(packet))
            for reg, value in [(UC_ARM_REG_R4, pressed), (UC_ARM_REG_R5, context),
                               (UC_ARM_REG_R6, subtype), (UC_ARM_REG_R8, args[3])]:
                u.reg_write(reg, value)
            run(0x9DBCF2, [0x9DBD06])
            raw = bytes(u.mem_read(packet, 24))
            assert raw == struct.pack('<BBH5I', 2, 0, 0x3026, context, pressed, subtype, args[3], 0)
            # The real bridge copies notification data to event0x8203.
            u.reg_write(UC_ARM_REG_R5, packet)
            run(0x3AE2AA, [0x3AE2C0])
            event = bytes(u.mem_read(STACK + 0x3000 + 0x14, 28))
            assert struct.unpack_from('<I', event)[0] == 0x8203
            assert struct.unpack_from('<I', event, 4)[0] == context
            assert struct.unpack_from('<3I', event, 12) == (pressed, subtype, args[3])
            # Existing target recording-reference construction, with debug
            # selection explicitly synthetic. Normal enabled binding remains
            # a future hook rather than pretending the debug byte is set.
            callback = references.reference(0x11, 1 - pressed, pressed, subtype, context, args[3])
            assert (callback['request'] == 'enqueue-reference') == (subtype != 13)
            if subtype != 13:
                assert callback['owner_va'] == '0x1a3aae0'
                assert callback['callback_va'] == ('0x474fad' if pressed else '0x475015')
            item.update(notification_hex=raw.hex(), reference_callback=callback)
        cases.append(item)
    report = {'mode': 'OFFLINE_NATIVE_REQUEST13_RECORDING_HANDOFF', 'camera_io': False,
              'firmware_modified': False, 'cases': cases,
              'limits': ['No real timer, sensor, allocation, message send or callback enqueue ran',
                         'Synthetic debug selection is not a live enabled-state binding',
                         'References do not prove a pre-shutter RAW or SD file was retained']}
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(report, f, indent=2);f.write('\n')
    print(f'Native request13 formal-recording handoff: {len(cases)} cases; no hardware requests delivered.')


if __name__ == '__main__':
    main()
