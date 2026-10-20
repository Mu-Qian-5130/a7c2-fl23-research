"""Trace original stop messages to queued work, not hardware completion.

Pinned private CP only. Synthetic owners/packets; native send, enqueue,
cancel replies and BLOG writes remain unexecuted stop boundaries.
No camera access, timing guarantee or installable firmware is supplied.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R4,
    UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R8, UC_ARM_REG_R10,
    UC_ARM_REG_SP, UC_ARM_REG_LR)
from audit_capture_transition import NativeCapture, BASE, OWNER, STACK, STOP, words
from support.cp_mapping import PINNED

WIRE, EVENT, CONTROLLER, CONTEXT = OWNER + 0x1000, OWNER + 0x2000, OWNER + 0x3000, OWNER + 0x4000
CAP = 0x1a3aae0


def audit(cp):
    n = NativeCapture(cp)
    u = n.u
    u.mem_map(0x1a23000, 4096)
    cases = []
    # Global startup proves which actor receives4039/cancellation messages.
    # Do not substitute the generic CAM callback queue for this custom loop.
    got = n.run(0x9da0d6, (0x515be0,), [
        (UC_ARM_REG_SP, STACK + 0x8000), (UC_ARM_REG_LR, STOP | 1)])
    assert got['args'][1] == 0x1a2332c
    n.run(0x9da0fe, ())  # Pure post-atexit task object stores.
    assert struct.unpack('<I', u.mem_read(0x1a2361c + 8, 4))[0] == BASE + 0x3510f8 + 1
    assert struct.unpack('<I', u.mem_read(0x1a2361c + 0x14, 4))[0] == 0x6f
    got = n.run(0x3510f8, (0x45d3a8,), [
        (UC_ARM_REG_SP, STACK + 0x8000), (UC_ARM_REG_LR, STOP | 1)])
    assert got['args'][0] == 0x90040193 and got['args'][2] == 0xffffffff
    cases.append(dict(kind='release-actor-binding', object='0x1a2361c',
        state='0x1a2332c', task=0x6f, queue_route='0x90040193',
        custom_loop_file='0x3510f8', receive_executed=False))
    # This apparent accessor actually resets native owner fields. Stop before
    # its configuration dependency; it must not be used as a live query.
    got = n.run(0x9da0a8, (0x34fcc4,), [
        (UC_ARM_REG_SP, STACK + 0x8000), (UC_ARM_REG_LR, STOP | 1)])
    assert struct.unpack('<2I', u.mem_read(0x1a2332c + 0x2e8, 8)) == (1, 0x40000001)
    assert got['args'][0] == 0x1a2332c + 0x2ac
    cases.append(dict(kind='startup-wrapper-is-not-query', wrapper_file='0x9da0a8',
        native_state_resets_observed=True, configuration_dependency_executed=False))
    # Resolve both actual TBH tables, rather than inferring names or order
    # from neighboring numeric command IDs.
    bridge = 0x3ae090 + 2*struct.unpack_from('<H', cp, 0x3ae090 + 2*13)[0]
    dispatch = 0x3ace12 + 2*struct.unpack_from('<H', cp, 0x3ace12 + 2)[0]
    assert bridge == 0x3ae170 and dispatch == 0x3ad03a
    for context in (0, 0x12345678):
        u.mem_write(WIRE, words(0x300d0002, context) + bytes(24))
        got = n.run(bridge, (0x3adfe4,), [
            (UC_ARM_REG_R5, WIRE), (UC_ARM_REG_R4, 0x90040193),
            (UC_ARM_REG_R8, 0x900302d9),
            (UC_ARM_REG_SP, STACK + 0x8000), (UC_ARM_REG_LR, STOP | 1)])
        assert got['args'][0:2] == [0x1a52b34, 0x900302d9] and got['args'][3] == 32
        packet = bytes(u.mem_read(got['args'][2], 32))
        assert packet == words(0, 0x101, context, 0x90040193, 0, 0, 0, 0)
        u.mem_write(EVENT, packet[4:])
        u.mem_write(CONTROLLER, bytes(0x40))
        u.mem_write(CONTROLLER + 12, words(CONTEXT))
        got = n.run(0x3accf0, (0xa19b3a,), [
            (UC_ARM_REG_R0, CONTROLLER), (UC_ARM_REG_R1, EVENT),
            (UC_ARM_REG_SP, STACK + 0x8000), (UC_ARM_REG_LR, STOP | 1)])
        assert got['args'][:2] == [CONTEXT, context]
        got = n.run(0xa19b3a, (0x407f1c,), [
            (UC_ARM_REG_R0, CONTEXT), (UC_ARM_REG_R1, context),
            (UC_ARM_REG_SP, STACK + 0x8000), (UC_ARM_REG_LR, STOP | 1)])
        assert got['args'][0] == CAP and got['args'][2:] == [context, 0]
        job = bytes(u.mem_read(got['args'][1], 20))
        assert job == words(0x870879, 0, BASE + 0x36d59c + 1, 0, 0)
        # This native post-enqueue call is a logger, not a next-state send.
        got = n.run(0xa19b6c, (0xa18dc4,))
        assert got['args'] == [context, 1, 0, 0]
        got = n.run(0xa18dc4, (0xa18cac,))
        assert got['args'][:2] == [4, 16]
        assert bytes(u.mem_read(got['args'][2], 16)) == words(context, 1, 0, 0)
        cases.append(dict(kind='300d-to101-to-native-work-job', context=context,
            wire_hex=packet.hex(), queued_job_hex=job.hex(),
            post_enqueue_call='BLOG argument wrapper, not a completion notification'))
    # Actual subtype13 stop branch reaches its existing controller helper.
    # No-pending-reply inputs return after clearing the request byte. Existing
    # normal-active byte and source words stay unchanged; no capture-end
    # or all-frame release is performed by that leaf.
    for normal_active in (0, 1):
        u.mem_write(OWNER, bytes(0x600))
        u.mem_write(OWNER + 0x158 + 0x14 + 13*16, b'\1')
        ctrl = OWNER + 0x278
        u.mem_write(ctrl + 0x18, bytes([normal_active, 1, 0, 0]))
        u.mem_write(ctrl + 0x1c, words(0xffffffff))
        got = n.run(0x350e60, (0x9da59e,), [
            (UC_ARM_REG_R10, OWNER), (UC_ARM_REG_R5, 13), (UC_ARM_REG_R6, 0),
            (UC_ARM_REG_SP, STACK + 0x8000), (UC_ARM_REG_LR, STOP | 1)])
        assert got['args'][0] == ctrl
        before = bytes(u.mem_read(ctrl, 0x24))
        n.call(0x9da59e, [ctrl])
        expected = bytearray(before)
        expected[0x19] = 0
        assert bytes(u.mem_read(ctrl, 0x24)) == expected
        cases.append(dict(kind='native-stop13-no-pending-reply', normal_active=normal_active,
            only_request_byte_cleared=True, hardware_completion=False))
    u.mem_write(CONTEXT, bytes(0x24))
    u.mem_write(CONTEXT + 0x19, b'\1')
    u.mem_write(CONTEXT + 0x1c, words(0x12345678))
    got = n.run(0x9da59e, (0x9dc4de,), [
        (UC_ARM_REG_R0, CONTEXT), (UC_ARM_REG_SP, STACK + 0x8000),
        (UC_ARM_REG_LR, STOP | 1)])
    assert got['args'][0] == 0x12345678
    assert u.mem_read(CONTEXT + 0x19, 1)[0] == 0
    assert bytes(u.mem_read(CONTEXT + 0x1c, 4)) == words(0x12345678)
    cases.append(dict(kind='native-stop13-pending-reply-boundary', reply_send_executed=False))
    # Identify the helper from its actual recipient and wire, not from the
    # fact it takes one32-bit context argument. No allocation or reply runs.
    n.external.remove(BASE + 0x9dc4de)
    try:
        got = n.run(0x9dc4de, (0x530176,), [
            (UC_ARM_REG_R0, 0x12345678), (UC_ARM_REG_SP, STACK + 0x8000),
            (UC_ARM_REG_LR, STOP | 1)])
    finally:
        n.external.add(BASE + 0x9dc4de)
    assert got['args'][1:] == [0x90040193, 0x80020002, 12]
    sp = u.reg_read(UC_ARM_REG_SP)
    u.mem_write(sp + 0x14, words(WIRE))
    u.mem_write(WIRE, bytes(12))
    got = n.run(0x9dc4fc, (0xa3c516,))
    reply = bytes(u.mem_read(WIRE, 12))
    assert reply == struct.pack('<BBH2I', 1, 0, 0x403d, 0x12345678, 0xf000)
    cases.append(dict(kind='actual403d-reply-constructor', origin='0x90040193',
        recipient='0x80020002', wire_hex=reply.hex(), allocation_or_send_executed=False))
    # Original reply/defer policy depends on the request origin, reason bits
    # and pre-read request byte. Some replies precede arbitration entirely.
    # None can be relabeled as a general all-frame release fence.
    for origin, mask, requested, reply_now, deferred in (
            (0x80020002, 4, 1, False, False),
            (0x80020002, 0x8000, 1, False, True),
            (0x80020002, 0x8000, 0, True, False),
            (0x90030001, 0x8000, 1, False, False)):
        n.fixture()
        arb = OWNER + 0x278
        u.mem_write(arb + 0x19, bytes([requested]))
        u.mem_write(arb + 0x1c, words(0xffffffff))
        u.mem_write(WIRE, words(0x403d0005, 0x12345678, mask, 1))
        got = n.run(0x9d9686, (0x9dc4de, 0x9da2c0), [
            (UC_ARM_REG_R4, OWNER), (UC_ARM_REG_R5, WIRE),
            (UC_ARM_REG_R6, WIRE + 12), (UC_ARM_REG_R10, origin),
            (UC_ARM_REG_SP, STACK + 0x8000), (UC_ARM_REG_LR, STOP | 1)])
        assert got['address'] == BASE + (0x9dc4de if reply_now else 0x9da2c0)
        assert struct.unpack('<I', u.mem_read(arb + 0x1c, 4))[0] == (
            0x12345678 if deferred else 0xffffffff)
        if reply_now:
            assert got['args'][0] == 0x12345678
        cases.append(dict(kind='native-cancel-reply-policy', origin=hex(origin),
            mask=hex(mask), request13_byte=requested, reply_before_arbitration=reply_now,
            deferred_reply_context_saved=deferred, reply_or_arbitration_executed=False))
    # A native S1 wrapper already releases reason4. Do not assume a new
    # feature exclusively owns that bit just because it sent its own set.
    got = n.run(0xa1acfe, (0xa18dd8,), [
        (UC_ARM_REG_SP, STACK + 0x8000), (UC_ARM_REG_LR, STOP | 1)])
    got = n.run(0xa1ad0e, (0x9da63a,))
    assert got['args'][0] == 4
    cases.append(dict(kind='existing-native-reason4-release', wrapper_file='0xa1acfe',
        sender_file='0x9da63a', mask=4, release_executed=False))
    # The original arbitration can clear its local active byte BEFORE
    # constructing300d. A passive zero snapshot cannot replace ordering.
    for previous, active in ((0, 0), (13, 0), (13, 1)):
        n.fixture()
        arb = OWNER + 0x278
        u.mem_write(arb + 0x10, words(previous))
        u.mem_write(arb + 0x18, bytes([active, 0, 0, 0]))
        u.mem_write(arb + 0x1c, words(0xffffffff))
        got = n.run(0x9da2c0, (0x9dbc6a, 0x9dbcca, 0x530176), [
            (UC_ARM_REG_R0, arb), (UC_ARM_REG_SP, STACK + 0x8000),
            (UC_ARM_REG_LR, STOP | 1)])
        expected = STOP if not previous else BASE + (0x9dbc6a if active else 0x9dbcca)
        assert got['address'] == expected
        if previous:
            assert u.mem_read(arb + 0x18, 1)[0] == 0
        cases.append(dict(kind='native-arbitration-to-stop-boundary', previous_request=previous,
            local_active_before=active, local_active_at_boundary=u.mem_read(arb + 0x18, 1)[0],
            boundary_file=hex(expected-BASE) if expected != STOP else 'return',
            stop_or_notification_send_executed=False))
    return cases


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    cp = a.cp.read_bytes()
    digest = hashlib.sha256(cp).hexdigest()
    if digest not in PINNED:
        raise ValueError('Unsupported complete target CP')
    result = dict(schema='OFFLINE_ORIGINAL_STOP_PROVENANCE/2', cp_sha256=digest,
        camera_io=False, cases=audit(cp), limits=[
            'Post-call slices do not model native transport/RTOS success',
            'Clearing request13 does not by itself prove CAP arbitration completed',
            'The local BLOG wrapper is not a hardware-stop acknowledgment',
            'Marker/raw-frame ordering and all-stage release remain unproven'])
    with a.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(f"Original stop provenance: {len(result['cases'])} cases; no camera I/O.")


if __name__ == '__main__':
    main()
