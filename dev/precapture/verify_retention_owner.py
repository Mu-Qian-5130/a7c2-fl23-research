"""Native retention-task ABI and owner-local policy lease, offline only.

Original constructors, packet copies and callback dispatch slices execute.
RTOS send/receive, logging and sensor operations never execute or return a
fabricated success. Lease storage and jobs are synthetic, not installed.
"""
import argparse
import hashlib
import itertools
import json
import struct
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R5, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)
from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1,
    UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC)
from support.cp_mapping import PINNED
from support.build import compile_shared
from support.elf import image_loader
from support.memory import MEM, STACK, STOP

BASE, QUEUE, POOL, OWNER = 0x108000, 0x1a45c70, 0x1a444f4, 0x1a3aae0
DEBUG, OWNER_PTR = 0x1a533a4, 0x1a45ca4


def words(*v):
    return struct.pack('<' + 'I' * len(v), *v)


def native_audit(cp):
    u = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    u.mem_map(BASE, (len(cp) + 4095) & ~4095)
    u.mem_write(BASE, cp)
    for at, size in [(0x1a44000, 0x2000), (OWNER & ~4095, 4096),
                     (DEBUG & ~4095, 4096), (MEM, 4096), (STACK, 0x4000), (STOP, 4096)]:
        u.mem_map(at, size)
    stops, seen = set(), []

    def stop(cpu, at, size, user):
        if at in stops:
            seen.append(at)
            cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE, stop)

    def run(at, args=(), boundaries=(STOP,), setup=True):
        nonlocal stops
        stops = set(boundaries)
        seen.clear()
        if setup:
            u.reg_write(UC_ARM_REG_SP, STACK + 0x3000)
            u.reg_write(UC_ARM_REG_LR, STOP | 1)
        for reg, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
            u.reg_write(reg, value)
        u.emu_start(at | 1, 0xffffffff, count=10000)
        assert len(seen) == 1 and u.reg_read(UC_ARM_REG_PC) == seen[0]
        return seen[0]

    # Actual constructor including original pure memset, no modeled allocator.
    u.mem_write(0x1a44000, bytes([0xa5]) * 0x2000)
    run(BASE + 0xa09cce)
    q = bytes(u.mem_read(QUEUE, 0x34))
    # The two alignment bytes after the26-byte policy/state clear are padding,
    # not initialized fields. Preserve them in all subsequent comparisons.
    assert struct.unpack('<13I', q) == (0xe75730, QUEUE + 4, QUEUE + 4, 0, POOL, 0, 0, 0, 0, 0, 0, 0xa5a50000, 0), q.hex()
    assert struct.unpack('<3I', u.mem_read(POOL, 12)) == (POOL + 12, 500, 500)
    run(BASE + 0xa05d8e)
    assert struct.unpack('<3I', u.mem_read(OWNER + 0x14, 12))[:2] == (0x88, 0x38)
    # The constructor's callback resolves to the actual generic queue loop.
    assert struct.unpack('<I', u.mem_read(OWNER + 8, 4))[0] == BASE + 0x408020 + 1

    config_cases = 0
    for state, count, f2, f3 in itertools.product((0, 1, 2), (0, 1), (0, 1, 2), (0, 1, 2, 100, 255)):
        initial = bytearray(q)
        struct.pack_into('<I', initial, 12, count)
        struct.pack_into('<I', initial, 28, state)
        u.mem_write(QUEUE, bytes(initial))
        u.mem_write(DEBUG + 0xf2, bytes([f2, f3]))
        end = run(BASE + 0xa09b28, boundaries=(STOP, BASE + 0xa3c57a))
        expected = bytearray(initial)
        if state:
            assert end == BASE + 0xa3c57a
        else:
            assert end == STOP
            struct.pack_into('<2I', expected, 20, 0 if f2 == 1 else 1, f3 * 10 if f2 == 1 else f3)
        assert bytes(u.mem_read(QUEUE, len(q))) == bytes(expected)
        config_cases += 1

    # Table selection, callback and state-commit are three explicit slices.
    # A callback does NOT run successfully by assumption, and logging is not
    # executed. In particular, committed state0 alone does not mean drained.
    transitions = [
        [(1, 0xa09d78), (1, 0xa09d78), (1, 0xa09d96)],
        [(2, 0xa09dd6), (2, 0xa09dd6), (2, 0xa09d78)],
        [(2, 0xa09e10), (2, 0xa09e10), (2, 0xa09e22)],
        [(0, 0xa09e24), (1, 0xa09e22), (1, 0xa09e3c)],
        [(0, 0xa09e60), (0, 0xa09e60), (0, 0xa09e7e)],
    ]
    transition_cases = 0
    for event, row in enumerate(transitions):
        for state, (next_state, callback) in enumerate(row):
            raw = struct.unpack_from('<2I', cp, 0xe75740 - BASE + event * 24 + state * 8)
            assert raw == (next_state, BASE + callback + 1)
            initial = bytearray(q)
            struct.pack_into('<I', initial, 28, state)
            u.mem_write(QUEUE, bytes(initial))
            u.mem_write(DEBUG, bytes(0x100))
            sp = STACK + 0x3000
            u.mem_write(sp, words(0x89abcdef))
            run(BASE + 0x3720c4, (QUEUE, event, MEM + 0x300, 0x12345678),
                (BASE + 0xa3b61c,))
            run(BASE + 0x3720fc, boundaries=(BASE + callback,), setup=False)
            assert [u.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1,
                UC_ARM_REG_R2, UC_ARM_REG_R3)] == [QUEUE, MEM + 0x300, 0x12345678, 0x89abcdef]
            assert bytes(u.mem_read(QUEUE, len(q))) == bytes(initial)
            # This is after-callback metadata commit only, NOT completion of
            # the stopped callback, dequeuer, image release or sensor phase.
            run(BASE + 0x37212e, boundaries=(BASE + 0xa09efc,), setup=False)
            expected = bytearray(initial)
            struct.pack_into('<I', expected, 28, next_state)
            assert bytes(u.mem_read(QUEUE, len(q))) == bytes(expected)
            transition_cases += 1
    for count in (0, 1):
        initial = bytearray(q)
        struct.pack_into('<I', initial, 12, count)
        u.mem_write(QUEUE, bytes(initial))
        end = run(BASE + 0xa09efc, (QUEUE, 0), (STOP, BASE + 0x372418))
        assert end == (BASE + 0x372418 if count else STOP)
        assert bytes(u.mem_read(QUEUE, len(q))) == bytes(initial)

    # Original config producer -> original callback enqueue -> RTOS boundary.
    u.mem_write(OWNER_PTR, words(OWNER))
    run(BASE + 0xa09aee, boundaries=(BASE + 0x4e4b84,))
    assert u.reg_read(UC_ARM_REG_R0) == 0x38 and u.reg_read(UC_ARM_REG_R2) == 28
    packet = bytes(u.mem_read(u.reg_read(UC_ARM_REG_R1), 28))
    assert packet == words(0x74ca7b, 0, BASE + 0xa09b28 + 1, 0, 0, 0, 0)
    # Explicit return-only slices establish convention, without executing send.
    run(BASE + 0x407f68, setup=False)
    assert u.reg_read(UC_ARM_REG_R0) == 1
    run(BASE + 0xa09aee, boundaries=(BASE + 0x4e4b84,))
    run(BASE + 0x407faa, setup=False)
    assert u.reg_read(UC_ARM_REG_R0) == 0

    # Dispatch only AFTER receive/housekeeping. Wire values are frozen, not
    # loaded from a mutable backend at dispatch time. No OS receive is faked.
    dispatch_cases = 0
    for generation, duration in itertools.product((1, 7, 0xfffffffe), (0, 5, 500, 1000)):
        sp = STACK + 0x3000
        job = words(BASE + 0x6fddcc + 1, 0, STOP | 1, 0, 0, generation, duration)
        u.mem_write(sp + 4, job)
        u.reg_write(UC_ARM_REG_SP, sp)
        u.reg_write(UC_ARM_REG_R5, sp + 4)
        run(BASE + 0x40807c, setup=False)
        assert [u.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1)] == [generation, duration]
        dispatch_cases += 1
    # Original zero-argument config callback uses the same receive slice.
    u.mem_write(QUEUE, q)
    u.mem_write(DEBUG + 0xf2, bytes([1, 50]))
    u.mem_write(sp + 4, packet)
    u.reg_write(UC_ARM_REG_SP, sp)
    u.reg_write(UC_ARM_REG_R5, sp + 4)
    u.reg_write(UC_ARM_REG_LR, STOP | 1)
    run(BASE + 0x40807c, boundaries=(BASE + 0x408096,), setup=False)
    expected = bytearray(q)
    struct.pack_into('<2I', expected, 20, 0, 500)
    assert bytes(u.mem_read(QUEUE, len(q))) == bytes(expected)
    return dict(constructor_queue_hex=q.hex(), metadata_nodes=500,
        native_configuration_cases=config_cases, native_frozen_argument_dispatch_cases=dispatch_cases,
        native_state_callback_selection_and_commit_slices=transition_cases,
        native_idle_state_still_requires_drain_cases=2,
        native_config_packet_hex=packet.hex(), callback_enqueue_success_value=1,
        callback_enqueue_failure_value=0, OS_send_receive_executed=False,
        pixel_capacity_established=False)


def lease_audit(zig, output):
    reports = {}
    for arch, target in [('thumb', 'thumb-linux-gnueabi'), ('aarch64', 'aarch64-linux-gnu')]:
        elf = output / (arch + '-retention-lease.elf')
        compile_shared(zig, arch, elf,
            [Path(__file__).with_name('cp_retention_lease.c')])
        u, symbols = image_loader(elf, arch, ('precapture_retention_owner_apply',))
        q, state = MEM + 0x100, MEM + 0x200
        regs = ((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3) if arch == 'thumb'
            else (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3))
        spreg, lrreg, pcreg = ((UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC) if arch == 'thumb'
            else (UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC))
        cases = 0

        def setup(policy=1, limit=0):
            u.mem_write(MEM, bytes([0xa5]) * 0x400)
            u.mem_write(q, words(0xe75730, q + 4, q + 4, 0, POOL, policy, limit, 0, 91, 92, 93, 94, 95))
            u.mem_write(state, bytes(16))

        def call(gen, duration, expected, pointers=None):
            nonlocal cases
            before_q = bytes(u.mem_read(q, 0x34))
            before_s = bytes(u.mem_read(state, 16))
            before_mem = bytes(u.mem_read(MEM, 0x400))
            args = (state, q, gen, duration) if pointers is None else (*pointers, gen, duration)
            for reg, value in zip(regs, args):
                u.reg_write(reg, value)
            u.reg_write(spreg, STACK + 0x3000)
            u.reg_write(lrreg, STOP | (arch == 'thumb'))
            u.emu_start(symbols['precapture_retention_owner_apply'], STOP, count=600)
            assert u.reg_read(pcreg) == STOP
            assert u.reg_read(regs[0]) & 0xffffffff == expected & 0xffffffff, (arch, gen, duration, expected)
            after_q = bytes(u.mem_read(q, 0x34))
            after_mem = bytes(u.mem_read(MEM, 0x400))
            for i, (old, new) in enumerate(zip(before_mem, after_mem)):
                if old != new:
                    assert q + 20 <= MEM + i < q + 28 or state <= MEM + i < state + 16
            assert after_q[:20] == before_q[:20] and after_q[28:] == before_q[28:]
            if expected < 0:
                assert after_q == before_q and bytes(u.mem_read(state, 16)) == before_s
                assert after_mem == before_mem
            cases += 1

        # Configurations match the original target time policy, while restore
        # exactly reproduces the saved policy/limit for both native policies.
        for policy, limit, duration in itertools.product((0, 1), (0, 1, 50, 255, 2550), (5, 10, 500, 1000)):
            setup(policy, limit)
            original = bytes(u.mem_read(q, 0x34))
            call(1, duration, 1)
            assert bytes(u.mem_read(q + 20, 8)) == words(0, duration)
            assert bytes(u.mem_read(state, 16)) == words(1, policy, limit, duration)
            call(1, duration, 1)  # repeated job preserves original backup
            call(1, 0, -116)
            call(2, 100, 1)
            assert bytes(u.mem_read(state, 16)) == words(2, policy, limit, 100)
            call(1, duration, -116)  # delayed older enable cannot take over
            call(3, 0, 1)
            assert bytes(u.mem_read(q, 0x34)) == original
            assert bytes(u.mem_read(state, 16)) == words(3, 0, 0, 0)
            call(3, 0, 1)
            call(2, 100, -116)  # restore ACK cannot be followed by old enable
        # Both initial configuration and restoration refuse nonidle/nonempty,
        # broken sentinel/anchor, or an externally changed owned policy.
        mutations = [(0, 0, -22), (4, q + 8, -16), (8, q + 8, -16),
            (12, 1, -16), (16, 0, -22), (20, 2, -22), (28, 1, -16), (28, 2, -16)]
        for active in (False, True):
            for offset, value, error in mutations:
                setup()
                if active:
                    call(1, 500, 1)
                u.mem_write(q + offset, words(value))
                call(2, 0 if active else 500, error)
        for offset, value in [(20, 1), (24, 999)]:
            setup()
            call(1, 500, 1)
            u.mem_write(q + offset, words(value))
            call(2, 0, -116)
            call(1, 500, -116)
        for gen, duration in [(0, 500), (1, 1), (1, 4), (1, 1001), (0xffffffff, 500)]:
            setup()
            call(gen, duration, -22)
        for ptrs in [(0, q), (state, 0), (state + 1, q), (state, q + 1)]:
            setup()
            call(1, 500, -22, ptrs)
        for index, value in [(1, 1), (2, 1), (3, 1), (3, 4), (3, 500), (3, 1001), (3, 0xffffffff)]:
            setup()
            u.mem_write(state + index * 4, words(value))
            call(1, 500, -22)
        setup()
        call(0xfffffffe, 500, 1)
        call(0xffffffff, 0, 1)
        call(1, 500, -116)  # no generation-wrap takeover
        reports[arch] = dict(owner_local_cases=cases, exact_restore=True,
            rejected_jobs_mutate_nothing=True, delayed_jobs_rejected=True)
    return reports


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp', type=Path, required=True)
    p.add_argument('--zig', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    cp = a.cp.read_bytes()
    digest = hashlib.sha256(cp).hexdigest()
    if digest not in PINNED:
        raise ValueError('Unsupported complete target CP')
    a.output.mkdir(parents=True, exist_ok=False)
    report = dict(schema='OFFLINE_RETENTION_OWNER_LEASE/1', cp_sha256=digest,
        camera_io=False, firmware_candidate_written=False, native=native_audit(cp),
        lease=lease_audit(a.zig, a.output), limits=[
            'Lease is16 bytes; runtime ABI2 reserves it but has no real startup binding',
            'Caller must be the retention owner; no callback or cross-task ACK is installed',
            'A local configuration return is not cancellation-release or capture success',
            'Native requested-stop, queue quiescence and generation-matched ACK remain unbound',
            '500 metadata nodes does not establish RAW pixel capacity',
            'No sensor, pixel retention, full-press save or physical restoration executed'])
    (a.output / 'retention-owner.private.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
