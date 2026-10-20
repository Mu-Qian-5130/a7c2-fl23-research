"""Original marker3 pipeline entry and stage descriptors, offline only.

Metadata is synthetic. Allocation, logging, RTOS and image work are stopped
before execution. Post-call slices do not model successful external calls.
This identifies a marker route, not FIFO ordering or a terminal fence.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R4,
    UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R8, UC_ARM_REG_R9,
    UC_ARM_REG_R10, UC_ARM_REG_R11, UC_ARM_REG_SP, UC_ARM_REG_LR)
from audit_capture_transition import NativeCapture, BASE, OWNER, STACK, STOP, words
from support.cp_mapping import PINNED

PIPE, OUT, WIRE, FRAME = OWNER + 0x1000, OWNER + 0x1800, OWNER + 0x2000, OWNER + 0x4000
TABLE = 0x110eca4


def audit(cp):
    n = NativeCapture(cp)
    u = n.u
    u.mem_map(0x1a4f000, 0x4000)
    u.mem_map(0x165b000, 4096)
    u.mem_map(0x1a3f000, 0x7000)
    n.call(0xa0c46a, [])
    n.call(0xa08e2c, [])
    # Actual marker constructor prefix, before its native frame allocation.
    got = n.run(0xa058b6, (0x36ba24,), [
        (UC_ARM_REG_SP, STACK + 0x8000), (UC_ARM_REG_LR, STOP | 1)])
    assert got['args'][2] == 0
    # Explicit post-frame-allocation continuation with an existing marker3
    # header. Allocation, stats operations and producer scheduling are not
    # supplied as successful calls.
    u.mem_write(FRAME, bytes(0x7000))
    u.mem_write(FRAME + 0x66e8, words(3))
    got = n.run(0xa05922, (0x366884,), [
        (UC_ARM_REG_R4, FRAME), (UC_ARM_REG_R5, 0),
        (UC_ARM_REG_SP, STACK + 0x7000), (UC_ARM_REG_LR, STOP | 1)])
    assert got['args'][1:3] == [FRAME, 0xffff]
    wire = bytes(u.mem_read(got['args'][0], 24))
    assert struct.unpack('<6I', wire) == (0xb0dd6f, 0, 0, 0, 0, 2)
    u.mem_write(WIRE, wire)
    u.mem_write(PIPE, bytes(68))
    # Native holder stores AFTER allocation. Explicit pre-existing pointer
    # inputs, not an emulated allocator return.
    got = n.run(0x3668b2, (0x366900,), [
        (UC_ARM_REG_R10, PIPE), (UC_ARM_REG_R11, WIRE),
        (UC_ARM_REG_R9, FRAME), (UC_ARM_REG_R8, 0xffff),
        (UC_ARM_REG_R6, 0), (UC_ARM_REG_R4, 1)])
    assert got['address'] == BASE + 0x366900
    assert struct.unpack('<I', u.mem_read(PIPE, 4))[0] == FRAME
    assert struct.unpack('<I', u.mem_read(PIPE + 0x20, 4))[0] == 0
    assert u.mem_read(PIPE + 0x27, 1)[0] == 0
    # Actual marker-specific initial selector: no generic marker folklore.
    stages = []
    specs = [
        (0, 0x37b35c, 0x37b37c, 0, 0x37fe60),
        (2, 0x37aaac, 0x37ab02, 1, 0x37fe60),
        (3, 0x37c254, 0x37c2aa, 1, 0x37fe60),
        (4, 0x37c5ac, 0x37c5da, 1, 0x37fe60),
        (5, 0x3798d4, None, 1, 0xa0dd98),
    ]
    for stage, selector, post_log, index, body in specs:
        u.mem_write(OUT, bytes(20))
        u.mem_write(PIPE, words(FRAME) + bytes(64))
        got = n.run(selector, (0xa125ca, 0xa12614), [
            (UC_ARM_REG_R0, OUT), (UC_ARM_REG_R1, PIPE),
            (UC_ARM_REG_SP, STACK + 0x8000), (UC_ARM_REG_LR, STOP | 1)])
        assert got['args'][:3] == [FRAME, stage, index]
        table = struct.unpack('<6I', u.mem_read(TABLE + stage*24, 24))
        descriptor = bytes(u.mem_read(table[3] + index*20, 20))
        if post_log is not None:
            # Output copy on original post-log slice; no log return consumed.
            n.run(post_log, ())
            assert bytes(u.mem_read(OUT, 20)) == descriptor
        callback = (struct.unpack_from('<I', descriptor, 8)[0] & ~1) - BASE
        got = n.run(callback, (body,), [
            (UC_ARM_REG_R0, PIPE), (UC_ARM_REG_SP, STACK + 0x8000),
            (UC_ARM_REG_LR, STOP | 1)])
        assert got['address'] == BASE + body
        stages.append(dict(stage=stage, descriptor=index, callback_file=hex(callback),
            phase0_body_file=hex(body), phase0_body_executed=False))
    # Stage1 has a separate pure property-dependent selector. Inspect the
    # native decision on explicit raw metadata rather than assigning UI names.
    stage1 = []
    for property_word in (0, 0x31):
        for raw9ac in (0, 1, 2, 3):
            u.mem_write(0x165bca8, words(property_word))
            u.mem_write(FRAME + 0x9ac, words(raw9ac))
            got = n.call(0x37bb30, [FRAME])
            assert got['address'] == STOP
            selected = u.reg_read(UC_ARM_REG_R0)
            assert selected <= 8
            stage1.append(dict(property_word=property_word, raw9ac=raw9ac, descriptor=selected))
    # Native new/replayed-stage admission with an occupied predecessor.
    # Both insertion routines are stop boundaries, not successful allocators.
    control = struct.unpack('<I', u.mem_read(TABLE, 4))[0]
    constructor = bytes(u.mem_read(control, 0x30))
    assert constructor[0x2c:0x2e] == b'\1\0'
    admission = []
    for replay in (0, 1):
        for pending in (0, 1):
            for running in (0, 1):
                q = bytearray(constructor)
                struct.pack_into('<I', q, 12, pending)
                q[0x2d] = running
                if pending:
                    struct.pack_into('<2I', q, 4, WIRE, WIRE)
                    u.mem_write(WIRE, words(control + 4, control + 4, PIPE))
                u.mem_write(control, bytes(q))
                u.mem_write(STACK + 0x8000, words(0))
                got = n.run(0xa09348, (0xa01c02, 0xa0996a), [
                    (UC_ARM_REG_R0, control), (UC_ARM_REG_R1, PIPE),
                    (UC_ARM_REG_R2, replay), (UC_ARM_REG_R3, 1),
                    (UC_ARM_REG_SP, STACK + 0x8000), (UC_ARM_REG_LR, STOP | 1)])
                queued = bool(running or (pending and not replay))
                assert got['address'] == BASE + (0xa01c02 if queued else 0xa0996a)
                expected = bytearray(q)
                if not queued:
                    struct.pack_into('<I', expected, 0x28, 1)
                assert bytes(u.mem_read(control, 0x30)) == expected
                position = None
                if queued:
                    assert got['args'][0] == control + 4
                    position = struct.unpack('<I', u.mem_read(got['args'][1], 4))[0]
                    # New entries append; a replayed busy head returns ahead
                    # of the remaining pending list. It cannot pass running1.
                    assert position == (WIRE if replay and pending else control + 4)
                admission.append(dict(replay=replay, pending=pending, running=running,
                    queued=queued, insertion_position=hex(position) if position else None,
                    insertion_or_allocation_executed=False))
    return dict(marker_holder_initial_stage=0, marker_info_hex=wire.hex(),
        marker_stage_routes=stages, stage1_decisions=stage1, admission=admission)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    cp = a.cp.read_bytes()
    digest = hashlib.sha256(cp).hexdigest()
    if digest not in PINNED:
        raise ValueError('Unsupported complete target CP')
    result = dict(schema='OFFLINE_ORIGINAL_MARKER3_FRONTIER/1', camera_io=False,
        cp_sha256=digest, **audit(cp), limits=[
            'Pre-existing frame and holder metadata are not allocated pixels',
            'Marker descriptor selection does not establish native scheduling order',
            'No proof all old frames entered stage0 before this marker is supplied',
            'No whole-stage quiescence, real pre-capture or installation is supplied'])
    with a.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print('Original marker3 entry, five phase0 routes, eight stage1 decisions and eight admission boundaries checked.')


if __name__ == '__main__':
    main()
