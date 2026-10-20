"""Original S2 callback registration/refcount and 8200 producer contracts.

Synthetic metadata only. Stop before callbacks, post, logging and other OS or
hardware services. This is not a scheduling proof, image buffer count, frame
allocation, captured photo, firmware patch or camera operation.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6,
    UC_ARM_REG_SP, UC_ARM_REG_LR)
from audit_capture_transition import NativeCapture, BASE, OWNER, STACK, STOP, DEBUG, words
from support.cp_mapping import PINNED

S2, FUNCTOR, PROFILE = 0x1a3f3e0, OWNER + 0x4000, OWNER + 0x5000
PENDING, CURRENT, GLOBAL_MODE = 0x171f4c8, 0x1a3ab04, 0x1a3ab38
CB = 0x36e894


def audit(cp):
    n = NativeCapture(cp)
    u = n.u
    for at in (S2 & ~4095, PENDING & ~4095, CURRENT & ~4095):
        u.mem_map(at, 4096)
    # Original producer builds the slot3 functor. Stop at registration.
    got = n.run(0x36e84a, (0xa07e7a,), [(UC_ARM_REG_SP, STACK + 0x8000),
        (UC_ARM_REG_LR, STOP | 1)])
    assert got['args'][0] == S2 and got['args'][1] == 3 and got['args'][3] == 0
    descriptor = bytes(u.mem_read(got['args'][2], 20))
    assert descriptor == words(0x637075, 0, BASE + CB + 1, 0, 0)
    u.mem_write(FUNCTOR, descriptor)
    cases = []

    def reset():
        u.mem_write(S2, bytes(0x88))
        u.mem_write(PENDING, bytes(12))
        u.mem_write(DEBUG, bytes(0x100))

    def register(expect_callback=False):
        inputs = [(r, v) for r, v in zip((UC_ARM_REG_R0, UC_ARM_REG_R1,
            UC_ARM_REG_R2, UC_ARM_REG_R3), (S2, 3, FUNCTOR, 0))]
        inputs += [(UC_ARM_REG_SP, STACK + 0x8000), (UC_ARM_REG_LR, STOP | 1)]
        return n.run(0xa07e7a, (CB,) if expect_callback else (), inputs)

    def drop(expect_callback=False):
        return n.run(0x371a04, (CB,) if expect_callback else (), [
            (UC_ARM_REG_R0, S2), (UC_ARM_REG_SP, STACK + 0x8000),
            (UC_ARM_REG_LR, STOP | 1)])

    reset()
    got = register(True)
    assert got['address'] == BASE + CB and got['args'][0] == 0
    assert bytes(u.mem_read(S2, 4)) == bytes(4)
    cases.append(dict(kind='register-at-zero-immediate-callback-entry', callback_executed=False))

    for refs in (1, 2, 3):
        reset()
        for i in range(refs):
            n.call(0xa07e3c, [S2])
            assert struct.unpack('<H', u.mem_read(S2 + 2, 2))[0] == i + 1
        register()
        assert bytes(u.mem_read(S2 + 3 * 24 + 8, 20)) == descriptor
        for remaining in range(refs - 1, -1, -1):
            got = drop(remaining == 0)
            assert struct.unpack('<H', u.mem_read(S2 + 2, 2))[0] == remaining
            assert got['address'] == (BASE + CB if not remaining else STOP)
        cases.append(dict(kind='native-count-reaches-zero-before-slot3-entry',
            refs=refs, callback_executed=False, count_is_not_pixel_capacity=True))

    reset()
    n.call(0xa07e22, [S2])
    n.call(0xa07e3c, [S2])
    register()
    assert bytes(u.mem_read(S2, 4)) == bytes([1, 0, 2, 0])
    # Clearing the active byte drops only its one native reference. Slot3
    # does not execute while the independent pre-existing reference remains.
    n.call(0xa07e4c, [S2])
    assert bytes(u.mem_read(S2, 4)) == bytes([0, 0, 1, 0])
    n.call(0xa07e76, [S2])
    assert u.reg_read(UC_ARM_REG_R0) == 0
    got = drop(True)
    assert got['address'] == BASE + CB and bytes(u.mem_read(S2, 4)) == bytes(4)
    cases.append(dict(kind='active-clear-is-not-zero-reference', callback_executed=False))

    # The actual finish-request path checks the separate native pending slot
    # before it clears the active reference. Stop at notification send, then
    # use an explicit post-send slice; its return value is not consumed.
    reset()
    n.call(0xa07e22, [S2])
    register()
    got = n.run(0x36d59c, (0x9da6ea,), [(UC_ARM_REG_SP, STACK + 0x8000),
        (UC_ARM_REG_LR, STOP | 1)])
    assert got['address'] == BASE + 0x9da6ea and got['args'][0] == 0x1000
    got = n.run(0x36d5d2, (CB,))
    assert got['address'] == BASE + CB
    assert bytes(u.mem_read(S2, 4)) == bytes(4)
    assert bytes(u.mem_read(PENDING + 4, 4)) == words(0)
    cases.append(dict(kind='finish-request-zero-reference-callback-with-no-pending-marker',
        notification_send_executed=False, physical_order_of_other_jobs_unproven=True))

    # Explicit later registration input: the mode1 helper uses its byte, not
    # refcount or cached-frame state. This is not a demonstrated real race.
    got = n.run(0xa05a9a, (0xa11fa4,), [(UC_ARM_REG_R0, 1),
        (UC_ARM_REG_R1, BASE + 0xa11fa4 + 1), (UC_ARM_REG_SP, STACK + 0x8000),
        (UC_ARM_REG_LR, STOP | 1)])
    assert got['address'] == BASE + 0xa11fa4
    cases.append(dict(kind='mode1-later-registration-can-still-enter-marker-callback',
        callback_executed=False, scheduling_race_not_established=True))

    messages = []
    for raw_mode, raw_flag, global_mode in ((0, 0, 0), (0, 0, 6),
            (1, 0, 0), (1, 1, 0), (6, 1, 0)):
        reset()
        u.mem_write(PROFILE, bytes(0x1000))
        u.mem_write(PROFILE + 8, words(raw_mode))
        u.mem_write(PROFILE + 0xd8b, bytes([raw_flag]))
        u.mem_write(CURRENT, words(0x12345678))
        u.mem_write(GLOBAL_MODE, words(global_mode))
        got = n.run(0x36e8f6, (0x3adfe4,), [(UC_ARM_REG_R4, PROFILE),
            (UC_ARM_REG_R5, DEBUG), (UC_ARM_REG_R6, CURRENT),
            (UC_ARM_REG_SP, STACK + 0x8000), (UC_ARM_REG_LR, STOP | 1)])
        assert got['address'] == BASE + 0x3adfe4
        assert got['args'][0:2] == [0x1a52b34, 0x900302d9]
        wire = bytes(u.mem_read(got['args'][2], 32))
        arg1 = int(raw_mode == 0)
        arg2 = int(global_mode == 6) if not raw_mode else int(raw_mode != 6 and raw_flag != 0)
        assert wire == words(0, 0x8200, 0, 0, 0x12345678, arg1, arg2, 0)
        messages.append(dict(raw_parameter_word8=raw_mode, raw_d8b=raw_flag,
            raw_global_mode=global_mode, wire_hex=wire.hex(), post_executed=False))
    return dict(callback_registration_descriptor_hex=descriptor.hex(), count_cases=cases,
        explicit_postdependency_8200_messages=messages,
        limits=['All references/flags/profiles are independent synthetic metadata, never RAW buffers',
            'Slot3 entry is a native zero-reference callback, not proof that marker3 event4 ran',
            'The callback setup/zero-count examples do not prove a physical scheduler interleaving',
            'The body prefix of36e894 before36e8f6 has unexecuted configuration dependencies',
            'Actual source ownership, terminal processing, physical retention/save and safe loading remain unproven'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    cp = a.cp.read_bytes()
    digest = hashlib.sha256(cp).hexdigest()
    if digest not in PINNED:
        raise ValueError('Unsupported complete CP')
    result = dict(schema='OFFLINE_NATIVE_S2_ZERO_REFERENCE_AND_8200/1', cp_sha256=digest,
        camera_io=False, firmware_candidate_written=False, **audit(cp))
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, indent=2)
    print(f"Native S2 contracts: {len(result['count_cases'])}; explicit8200 messages: {len(result['explicit_postdependency_8200_messages'])}. No camera I/O.")


if __name__ == '__main__':
    main()
