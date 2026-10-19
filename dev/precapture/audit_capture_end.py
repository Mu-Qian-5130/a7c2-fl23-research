"""Trace original marker3 production and idle clearing, with explicit slices.

All tasks, frame headers, pending callbacks and counters are synthetic. Native
OS enqueue/event flags, allocators and logging are stop boundaries. Outputs
may be inputs to a separate slice, never a simulated successful OS operation.
No camera access, image buffer allocation, patch or firmware candidate.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R8, UC_ARM_REG_R9,
    UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)
from audit_owner_binding import original_owner_fixture
from verify_extension_layout import PINNED

BASE, MEM, STACK, STOP = 0x108000, 0x30000000, 0x40000000, 0x20000000
ROOT, CAM, QUEUE, POOL = 0x1a52b38, 0x1a3aae0, 0x1a45c70, 0x1a444f4
DEBUG, S2, PENDING, STATS = 0x1a533a4, 0x1a3f3e0, 0x171f4c8, 0x17208f0
FRAME, PIPE, EVENT = MEM + 0x1000, MEM + 0x9000, MEM + 0xa000


def words(*v):
    return struct.pack('<' + 'I' * len(v), *v)


def audit(cp):
    u = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    u.mem_map(BASE, (len(cp) + 4095) & ~4095)
    u.mem_write(BASE, cp)
    for at, size in [(MEM, 0x20000), (STACK, 0x10000), (STOP, 4096),
            (CAM & ~4095, 4096), (S2 & ~4095, 4096), (0x1a44000, 0x2000),
            (0x1a4f000, 0x5000),
            (PENDING & ~4095, 4096), (STATS & ~4095, 4096)]:
        u.mem_map(at, size)
    stops, seen = set(), []

    def stop(cpu, at, size, user):
        if at in stops:
            seen.append((at, [cpu.reg_read(r) for r in
                (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)]))
            cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE, stop)

    def run(at, boundaries=(), args=(), registers=(), reset=True):
        nonlocal stops
        stops = {BASE + n for n in boundaries} | {STOP}
        seen.clear()
        if reset:
            u.reg_write(UC_ARM_REG_SP, STACK + 0x8000)
            u.reg_write(UC_ARM_REG_LR, STOP | 1)
        for r, v in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
            u.reg_write(r, v)
        for r, v in registers:
            u.reg_write(r, v)
        u.emu_start((BASE + at) | 1, 0xffffffff, count=20000)
        assert len(seen) == 1 and u.reg_read(UC_ARM_REG_PC) == seen[0][0]
        return seen[0]

    run(0xa05d8e)  # Native CAM task metadata constructor, no RTOS creation.
    run(0xa09cce)  # Native queue/pool constructor, including original memset.
    run(0xa09ac2, (0xa09acc,), registers=((UC_ARM_REG_R4, CAM),))
    run(0xa0c46a)  # Native stage5 descriptors, pure stores only.
    queue_initial = bytes(u.mem_read(QUEUE, 0x34))
    root_initial = original_owner_fixture(cp, ROOT)
    u.mem_write(ROOT, root_initial)
    u.mem_write(DEBUG, bytes(0x100))
    reports = []

    # The upstream raw field+208 and marker decide which callback is queued.
    for raw208, marker in ((0, 2), (0, 0), (1, 2), (0xffffffff, 2)):
        u.mem_write(FRAME, bytes(0x7000))
        u.mem_write(FRAME + 0x208, words(raw208))
        u.mem_write(FRAME + 0x66e8, words(marker))
        at, args = run(0x3883c0, (0x407f1c, 0x38832e),
                       registers=((UC_ARM_REG_R4, FRAME),))
        if raw208:
            assert at == BASE + 0x38832e
            reports.append(dict(kind='upstream-callback-skipped', raw208=raw208, marker=marker))
        else:
            assert at == BASE + 0x407f1c and args[0] == CAM
            job = bytes(u.mem_read(args[1], 20))
            callback = BASE + (0xa11fa4 if marker == 2 else 0xa11f82) + 1
            assert job == words(0xb1681f, 0, 0xb0da9b, 0, 0)
            assert args[2:] == [1, callback]
            reports.append(dict(kind='upstream-native-callback-job', raw208=raw208,
                marker=marker, callback_file=hex(callback - BASE - 1), OS_enqueue_executed=False))

    # Existing native deferred callback slot1 belongs to the S2Handler route.
    # It is not spare storage for a new feature: registering while pending
    # replaces the pointer. Do not use this to overwrite native completion.
    callback = BASE + 0xa11fa4 + 1
    for active in (0, 1):
        u.mem_write(S2, bytes([active, 0, 1, 0]))
        u.mem_write(PENDING, words(0x12345679, 0x87654321, 0x23456789))
        before = bytes(u.mem_read(PENDING, 12))
        at, _ = run(0xa05a9a, (0xa11fa4,), (1, callback))
        if active:
            assert at == STOP and bytes(u.mem_read(PENDING, 12)) == words(
                0x12345679, callback, 0x23456789)
        else:
            assert at == BASE + 0xa11fa4 and bytes(u.mem_read(PENDING, 12)) == before
        reports.append(dict(kind='native-slot1-selection', active_byte=active,
            counter16_raw=1, native_callback_entered=False,
            existing_slot_can_be_replaced=bool(active)))
    u.mem_write(PENDING + 4, words(callback))
    at, _ = run(0x36d5b8, (0xa11fa4,))
    assert at == BASE + 0xa11fa4 and bytes(u.mem_read(PENDING + 4, 4)) == words(0)
    reports.append(dict(kind='native-slot1-cleared-before-callback', callback_executed=False))

    # Original callback order: diagnostic, event-flag service, second
    # diagnostic, then a separate zero-argument CAM owner job. External calls
    # stay stopped; continuation slices do not consume their return values.
    at, args = run(0xa11fa4, (0xa3b61c,))
    assert at == BASE + 0xa3b61c and args == [4, 0xf01b, 0x4000, 0]
    at, args = run(0xa11fb8, (0x4e1834,), reset=False)
    assert at == BASE + 0x4e1834 and args[:2] == [0x35, 0x4000]
    at, _ = run(0xa11fc2, (0xa3b61c,), reset=False)
    assert at == BASE + 0xa3b61c
    at, args = run(0x36d086, (0x4e4b84,), reset=False)
    assert at == BASE + 0x4e4b84 and args[0] == 0x38 and args[2] == 28
    marker_job = bytes(u.mem_read(args[1], 28))
    assert marker_job == words(0x74ca7b, 0, BASE + 0xa058b6 + 1, 0, 0, 0, 0)
    reports.append(dict(kind='event-flag-before-marker-job', flag_id=0x35, bits=0x4000,
        marker_job_hex=marker_job.hex(), event_flag_and_OS_enqueue_executed=False))

    sp = STACK + 0x8000
    u.mem_write(sp + 4, marker_job)
    at, _ = run(0x40807c, (0x36ba24,), registers=(
        (UC_ARM_REG_R5, sp + 4), (UC_ARM_REG_SP, sp)), reset=False)
    assert at == BASE + 0x36ba24
    reports.append(dict(kind='original-marker-job-dispatch-to-allocation',
        allocator_executed=False, frame_or_pixels_allocated=False))

    # Explicit post-allocation metadata input, not a successful allocator
    # return. Execute original marker/stats writes before the next reset.
    u.mem_write(FRAME, bytes(0x7000))
    u.mem_write(STATS, bytes(24))
    u.mem_write(CAM + 0x30, words(7))  # Raw native global1a3ab10, meaning unassigned.
    at, _ = run(0xa058fc, (0xa09ace,), (FRAME,))
    assert at == BASE + 0xa09ace
    assert bytes(u.mem_read(FRAME + 0x66e8, 4)) == words(3)
    assert bytes(u.mem_read(CAM + 0x30, 4)) == words(6)
    assert bytes(u.mem_read(FRAME + 0x66f8, 24)) == bytes(24)
    reports.append(dict(kind='post-allocation-marker3-metadata-slice',
        preexisting_metadata_only=True, native_reset_executed=False))

    # Actual stage5 selector chooses descriptor1 for this marker; its phase0
    # callback shares the native final retention enqueue path, not class4
    # pixel-processing stages. Upstream pipeline scheduling remains untested.
    u.mem_write(PIPE, words(FRAME) + bytes(0x40))
    at, args = run(0x3798d4, (0xa125ca, 0xa12614), (PIPE, PIPE))
    assert args[:3] == [FRAME, 5, 1]
    descriptor = struct.unpack('<5I', u.mem_read(0x1a4fe38 + 20, 20))
    assert descriptor[2] == BASE + 0xa0b922 + 1
    at, args = run(0xa0b922, (0xa12588,), (PIPE,))
    assert at == BASE + 0xa12588 and args[:2] == [FRAME, 0x10a]
    # Explicit post-trace slice, not a fabricated successful frame recorder.
    at, args = run(0xa0dda8, (0xa09b34,), reset=False)
    assert at == BASE + 0xa09b34 and args[0] == PIPE
    at, args = run(0xa09b34, (0x4e4b84,), (PIPE,))
    assert at == BASE + 0x4e4b84 and args[0] == 0x38 and args[2] == 28
    queue_job = bytes(u.mem_read(args[1], 28))
    assert queue_job == words(0xb10e09, 0, BASE + 0xa09b6e + 1, 0, 0, PIPE, 0)
    reports.append(dict(kind='native-marker3-descriptor1-to-queue-job',
        descriptor=1, queue_job_hex=queue_job.hex(), frame_trace_executed=False,
        OS_enqueue_executed=False))
    u.mem_write(sp + 4, queue_job)
    at, _ = run(0x40807c, (0xa3b61c,), registers=(
        (UC_ARM_REG_R5, sp + 4), (UC_ARM_REG_SP, sp)), reset=False)
    assert at == BASE + 0xa3b61c
    at, args = run(0x372024, (0x3720c4,), reset=False)
    assert at == BASE + 0x3720c4 and args[:3] == [QUEUE, 4, PIPE]
    reports.append(dict(kind='native-marker3-job-dispatch-to-event4',
        event=4, native_event_handler_executed=False, image_release_executed=False))

    # Whole original8200 producer, including pure memset/owner getter. The
    # callback's own trigger/order is outside this slice; post stays stopped.
    at, args = run(0xa18a4a, (0x3adfe4,), (11, 22, 33))
    assert at == BASE + 0x3adfe4 and args[0] == 0x1a52b34
    assert args[1] == 0x900302d9 and args[3] == 32
    idle_wire = bytes(u.mem_read(args[2], 32))
    assert idle_wire == words(0, 0x8200, 0, 0, 11, 22, 33, 0)
    u.mem_write(EVENT, idle_wire[4:])
    reports.append(dict(kind='original8200-producer', wire_hex=idle_wire.hex(),
        native_post_executed=False, producer_trigger_order_unproven=True))

    # Original matched8200 context-clear slice. Nonempty synthetic metadata
    # shows clearing the S1 word does not itself drain it. These pre-existing
    # headers/nodes have no allocated pixels and are never recorded/released.
    # This is NOT proof that the real producer/scheduler permits this order.
    idle_cases = []
    for busy in (1, 2):
        for queue_state in (0, 1, 2):
            u.mem_write(ROOT, root_initial)
            u.mem_write(ROOT + 0x108 + 12, words(busy))
            run(0xa09cce)
            u.mem_write(QUEUE, queue_initial)
            if queue_state:
                node = POOL + 12
                held, holder = MEM + 0xb000, MEM + 0x13000
                # Independent fixture only; not native frame/class creation.
                u.mem_write(held, bytes(0x7000))
                u.mem_write(held + 0x66e8, words(2))
                u.mem_write(held + 0xbb4, words(4))
                u.mem_write(holder, words(held))
                u.mem_write(POOL, words(POOL + 24, 499, 500))
                u.mem_write(node, words(QUEUE + 4, QUEUE + 4, holder))
                u.mem_write(QUEUE + 4, words(node, node, 1))
                u.mem_write(QUEUE + 20, words(1, 2))  # Count policy, retain up to2.
                u.mem_write(QUEUE + 28, words(queue_state))
                u.mem_write(QUEUE + 0x2c, bytes([int(queue_state == 2)]))
            before = bytes(u.mem_read(0x1a44000, 0x2000))
            at, _ = run(0x3ac162, (0x3ac17c,), (0x8200,), registers=(
                (UC_ARM_REG_R9, ROOT + 0xdc), (UC_ARM_REG_R8, EVENT)))
            assert at == BASE + 0x3ac17c
            assert bytes(u.mem_read(ROOT + 0x108 + 12, 4)) == words(0)
            assert bytes(u.mem_read(0x1a44000, 0x2000)) == before
            idle_cases.append(dict(context_before=busy, queue_state=queue_state,
                queue_count=int(queue_state != 0), context_after=0, queue_unchanged=True))
    return dict(native_slices=reports, independent_context_clear_cases=idle_cases,
        limits=['No real task delivery/order, OS calls, logging, allocator or pixel operation executed',
            'Marker3 provenance is conditional on raw field208 and marker2; their UI semantics are unassigned',
            'S1 idle clearing and empty/idle retention are distinct facts',
            'The synthetic ordering examples do not prove a physical scheduling race',
            'The native pending callback slot must not be overwritten for a new feature',
            'Producer-to-idle-message ordering, pixel capacity and safe startup placement remain unproven'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    cp = a.cp.read_bytes()
    digest = hashlib.sha256(cp).hexdigest()
    if digest not in PINNED:
        raise ValueError('Unsupported complete target CP')
    report = dict(schema='OFFLINE_NATIVE_MARKER3_AND_IDLE_SLICES/1', cp_sha256=digest,
        camera_io=False, firmware_candidate_written=False, **audit(cp))
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(report, f, indent=2)
    print(f"Original marker3 slices: {len(report['native_slices'])}; independent idle clears: {len(report['independent_context_clear_cases'])}. No camera I/O.")


if __name__ == '__main__':
    main()
