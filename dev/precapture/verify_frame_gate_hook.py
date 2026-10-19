"""Execute a state-bound gate in the original parameter producer/consumer.

Emulator-only BL substitution, no changed CP image is emitted. Independent
objects/state and debug inputs are synthetic. Original pure gate leaves run;
no OS, sensor, frame allocation, send, refresh or cancellation is simulated.
"""
import argparse
import hashlib
import itertools
import json
import struct
import subprocess
from pathlib import Path

from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB
from unicorn import UC_HOOK_MEM_WRITE, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
    UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11,
    UC_ARM_REG_R12, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)
from audit_control import SPECS
from verify_capture_gate import Native
from verify_extension_layout import PINNED
from verify_offline import image_loader, codegen_flags, MEM, STACK, STOP
from audit_owner_binding import original_owner_fixture

BASE, PRIVATE, FRAME, DEBUG = 0x108000, MEM + 0x1000, MEM + 0x11000, 0x1a533a4
PRODUCER, CALL, PRODUCER_END = [BASE + n for n in (0xa06126, 0xa0612a, 0xa06132)]
CONSUMER, CONSUMER_END = [BASE + n for n in (0x36d8ae, 0x36d8be)]


def words(*v):
    return struct.pack('<' + 'I' * len(v), *v)


def assembly():
    return f'''.syntax unified
.thumb
.text
.global frame_gate_hook_fixture
.type frame_gate_hook_fixture,%function
.thumb_func
frame_gate_hook_fixture:
    push {{r1,r2,r3,r4,r12,lr}}
    mov r2,r0
    ldr r1,[r4,#0x10]
    ldrb.w r3,[r4,#0xd9c]
    ldr r0,={MEM:#x}
    bl precapture_target_frame_gate
    pop {{r1,r2,r3,r4,r12,lr}}
    bx lr
.size frame_gate_hook_fixture,.-frame_gate_hook_fixture
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp', type=Path, required=True)
    p.add_argument('--donor', type=Path, required=True)
    p.add_argument('--zig', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    cp, donor = a.cp.read_bytes(), a.donor.read_bytes()
    digest = hashlib.sha256(cp).hexdigest()
    if digest not in PINNED:
        raise ValueError('Unsupported complete target CP')
    if hashlib.sha256(donor).hexdigest() != SPECS['a1ii-4.00']['sha256']:
        raise ValueError('Unsupported complete donor CP')
    a.output.mkdir(parents=True, exist_ok=False)
    stub = a.output / 'emulator-only-frame-gate-fixture.S'
    stub.write_text(assembly(), encoding='ascii')
    elf = a.output / 'thumb-frame-gate-fixture.elf'
    command = [str(a.zig), 'cc', '-target', 'thumb-linux-gnueabi',
        *codegen_flags('thumb'), '-Oz', '-g', '-shared', '-fPIC', '-ffreestanding',
        '-fno-builtin', '-fno-stack-protector', '-fno-unwind-tables',
        '-fno-asynchronous-unwind-tables', '-nostdlib', '-Wl,--no-undefined,-Bsymbolic',
        '-o', str(elf), str(stub),
        str(Path(__file__).with_name('cp_frame_gate_adapter.c')),
        str(Path(__file__).with_name('capture_gate.c'))]
    build = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if build.returncode:
        raise RuntimeError(build.stderr[-2500:])
    u, symbols = image_loader(elf, 'thumb', ('frame_gate_hook_fixture',))
    u.mem_map(BASE, (len(cp) + 4095) & ~4095)
    u.mem_write(BASE, cp)
    u.mem_map(DEBUG & ~4095, 4096)
    u.mem_map(PRIVATE, 0x20000)
    ks = Ks(KS_ARCH_ARM, KS_MODE_THUMB)
    assert cp[CALL - BASE:CALL - BASE + 4] == bytes(ks.asm(
        f'bl {BASE + 0xa2f0fa:#x}', addr=CALL)[0])
    patched = bytes(ks.asm(f'bl {symbols["frame_gate_hook_fixture"] & ~1:#x}', addr=CALL)[0])
    assert len(patched) == 4
    u.mem_write(CALL, patched)
    oracle_target, oracle_donor = Native(cp, False), Native(donor, True)
    observed_writes = []
    def writes(cpu, access, address, size, value, user):
        if MEM <= address < PRIVATE + 0x20000 or DEBUG <= address < DEBUG + 0x100:
            observed_writes.append((address, size, value))
    u.hook_add(UC_HOOK_MEM_WRITE, writes)

    def generate(enabled, pending, stage, fault, context, mode, flags, selection, marker,
                 subtype=13, generation=7):
        state = words(enabled, 1, 500, stage, pending, 0x4173, 0, 0x90030001,
                      0, generation, 0, fault)
        u.mem_write(MEM, state + bytes([0xa5]) * 16)
        params = bytearray([0x5a]) * 4096
        params[0x10:0x14] = words(context)
        params[0x160:0x164] = words(mode)
        params[0xd9c] = subtype
        u.mem_write(PRIVATE, bytes(params))
        original_frame = bytearray([0xa5]) * 0x6800
        original_frame[0x66e8:0x66ec] = words(marker)
        u.mem_write(FRAME, bytes(original_frame))
        u.mem_write(DEBUG, bytes(0x100))
        u.mem_write(DEBUG + 0xf0, bytes([flags, selection]))
        observed_writes.clear()
        preserved = {UC_ARM_REG_R1: 0x11111111, UC_ARM_REG_R2: 0x22222222,
            UC_ARM_REG_R3: 0x33333333, UC_ARM_REG_R4: PRIVATE,
            UC_ARM_REG_R12: 0xcccccccc}
        for reg, value in {**preserved, UC_ARM_REG_SP: STACK + 0x3000,
                           UC_ARM_REG_LR: STOP | 1}.items():
            u.reg_write(reg, value)
        u.emu_start(PRODUCER | 1, PRODUCER_END, count=400)
        assert u.reg_read(UC_ARM_REG_PC) == PRODUCER_END
        flag = u.reg_read(UC_ARM_REG_R0)
        assert flag in (0, 1)
        params[0xd97] = flag
        assert bytes(u.mem_read(PRIVATE, 4096)) == bytes(params)
        for reg, value in preserved.items():
            assert u.reg_read(reg) == value
        assert u.reg_read(UC_ARM_REG_SP) == STACK + 0x3000
        assert u.reg_read(UC_ARM_REG_LR) == (CALL + 4) | 1
        assert observed_writes == [(PRIVATE + 0xd97, 1, flag)]
        observed_writes.clear()
        u.reg_write(UC_ARM_REG_R4, FRAME)
        u.reg_write(UC_ARM_REG_R5, PRIVATE + 8)  # Actual getter ABI, not private base.
        u.reg_write(UC_ARM_REG_R2, marker)
        u.emu_start(CONSUMER | 1, CONSUMER_END, count=30)
        assert u.reg_read(UC_ARM_REG_PC) == CONSUMER_END
        wanted_marker = 2 if flag else marker
        original_frame[0x66e8:0x66ec] = words(wanted_marker)
        assert bytes(u.mem_read(FRAME, 0x6800)) == bytes(original_frame)
        assert bytes(u.mem_read(MEM, 64)) == state + bytes([0xa5]) * 16
        assert bytes(u.mem_read(DEBUG + 0xf0, 2)) == bytes([flags, selection])
        assert observed_writes == [(FRAME + 0x66e8, 4, wanted_marker)]
        return flag, wanted_marker

    counts = dict(original_target_equivalence=0, original_donor_equivalence=0)
    for enabled, pending, stage, fault, context, mode, flags, selection, marker, subtype, generation in itertools.product(
        (0, 1, 2), (0, 1), (0, 1, 2, 3), (0, 1), (0, 1),
        (0, 1, 0x1a, 0x21, 2), (0, 0x10), (0, 0x11, 0xff), (0, 1), (1, 13), (0, 7)):
        special = subtype == 13 and (enabled == 1 or generation != 0)
        native = oracle_donor if special else oracle_target
        want = native.propagate(context, mode, 1 if special else 0, flags, selection, marker)
        actual = generate(enabled, pending, stage, fault, context, mode, flags, selection, marker,
                          subtype, generation)
        assert actual == want
        key = 'original_donor_equivalence' if native is oracle_donor else 'original_target_equivalence'
        counts[key] += 1
    # A queued request cannot retroactively update an existing parameter object.
    # Demonstrate stale old flag, then execute the real producer and consumer
    # afresh. This test does NOT claim to deliver the required refresh event.
    lifecycle = []
    for label, enabled, pending, stage, generation in [('fresh-disabled', 0, 0, 0, 0),
            ('pending-enable', 0, 1, 1, 1), ('committed-before-release', 1, 1, 2, 1),
            ('enabled', 1, 1, 0, 1), ('pending-disable', 1, 0, 1, 1),
            ('disabled-late-request', 0, 0, 0, 1)]:
        for subtype in (1, 13):
            flag, marker = generate(enabled, pending, stage, 0, 0, 1, 0, 0, 1, subtype, generation)
            special = int(subtype == 13 and (enabled == 1 or generation))
            assert flag == special and marker == (2 if special else 1)
            lifecycle.append(dict(stage=label, subtype=subtype, generated_flag=flag, frame_marker=marker))
    # Change only committed state while retaining the previously built object.
    generate(0, 1, 1, 0, 0, 1, 0, 0, 1, 13, 0)
    u.mem_write(MEM, words(1))
    u.mem_write(MEM + 12, words(2))
    assert u.mem_read(PRIVATE + 0xd97, 1)[0] == 0
    u.reg_write(UC_ARM_REG_R4, FRAME)
    u.reg_write(UC_ARM_REG_R5, PRIVATE + 8)
    u.reg_write(UC_ARM_REG_R2, 1)
    u.emu_start(CONSUMER | 1, CONSUMER_END, count=30)
    assert u.reg_read(UC_ARM_REG_PC) == CONSUMER_END
    assert struct.unpack('<I', u.mem_read(FRAME + 0x66e8, 4))[0] == 1
    assert generate(1, 1, 2, 0, 0, 1, 0, 0, 1) == (1, 2)
    # Execute the WHOLE original producer, including its original ARM memcpy
    # and pure mode filter, on pre-existing synthetic owned objects. The
    # source master snapshot and all native derived flags remain intact.
    baseline, _ = image_loader(elf, 'thumb', ('frame_gate_hook_fixture',))
    baseline.mem_map(BASE, (len(cp) + 4095) & ~4095)
    baseline.mem_write(BASE, cp)
    baseline.mem_map(DEBUG & ~4095, 4096)
    baseline.mem_map(PRIVATE, 0x20000)
    actual_private, source, handle = 0x171f4d8, PRIVATE + 0x1d000, 0x12345678
    for engine in (u, baseline):
        engine.mem_map(actual_private & ~4095, 0x2000)
    full_cases = 0
    for context, mode, phase, subtype in itertools.product((0, 1), (1, 2), (0, 2), (1, 13)):
        results = []
        for engine in (baseline, u):
            state = words(1, 1, 500, phase, 1, 0x4173, 0, 0x90030001, 0, 7, 0, 0)
            engine.mem_write(MEM, state)
            original_private = bytearray([0x5a]) * 0x1000
            original_private[:4] = words(handle)
            original_private[0x10:0x14] = words(context)
            engine.mem_write(actual_private, bytes(original_private))
            snapshot = bytearray(0xd64)
            snapshot[0x138:0x13c] = words(mode)  # original copy+0x28 => private+0x160
            engine.mem_write(source, bytes(snapshot))
            engine.mem_write(DEBUG, bytes(0x100))
            engine.mem_write(STACK + 0x3000, words(subtype, 0x87654321))
            saved = {reg: 0xc0000000 + n for n, reg in enumerate((UC_ARM_REG_R4,
                UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R8,
                UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11))}
            for reg, value in {**saved, UC_ARM_REG_R0: handle, UC_ARM_REG_R1: source,
                    UC_ARM_REG_R2: 0, UC_ARM_REG_R3: 0,
                    UC_ARM_REG_SP: STACK + 0x3000, UC_ARM_REG_LR: STOP | 1}.items():
                engine.reg_write(reg, value)
            engine.emu_start((BASE + 0xa06074) | 1, STOP, count=5000)
            assert engine.reg_read(UC_ARM_REG_PC) == STOP
            assert engine.reg_read(UC_ARM_REG_SP) == STACK + 0x3000
            for reg, value in saved.items():
                assert engine.reg_read(reg) == value
            assert bytes(engine.mem_read(source, len(snapshot))) == bytes(snapshot)
            assert bytes(engine.mem_read(MEM, 48)) == state
            results.append(bytes(engine.mem_read(actual_private, 0x1000)))
        original, adapted = results
        want = bytearray(original)
        want[0xd97] = int(context == 0 and subtype == 13)
        assert original[0xd97] == 0
        assert adapted == bytes(want)
        assert struct.unpack_from('<I', adapted, 0x160)[0] == mode
        full_cases += 1
    # Follow the original capture prepare routine's real singleton acquisition
    # before its producer call. Opaque context/subtype/timestamp are explicit
    # message inputs; camera-wide configuration objects remain synthetic.
    master, config = 0x165a720, 0x173efe8
    drive, shot = PRIVATE + 0x1e000, PRIVATE + 0x1f000
    prepare_stops, prepare_visits = set(), []
    def prepare_trace(cpu, at, size, user):
        if at in (BASE + 0xa05e6e, BASE + 0xa06074):
            prepare_visits.append(at)
        if at in prepare_stops:
            cpu.emu_stop()
    for engine in (baseline, u):
        engine.mem_map(master & ~4095, 0x2000)
        engine.mem_map(config & ~4095, 0x2000)
        engine.hook_add(UC_HOOK_CODE, prepare_trace)
        # Earlier full-producer cases already populated translated blocks.
        # Rebuild them so the newly added entry/stop hook is observed there.
        engine.ctl_remove_cache(BASE, BASE + len(cp))
    prepare_cases, parameter_reuse_cases = 0, 0
    for enabled, phase, mode, subtype in itertools.product((0, 1), (0, 2), (1, 2), (1, 13)):
        results = []
        for engine in (baseline, u):
            state = words(enabled, 1, 500, phase, enabled, 0x4173, 0, 0x90030001,
                          0, 7, 0, 0)
            engine.mem_write(MEM, state)
            # This free singleton must be acquired by original a05e6e. Do not
            # pre-fill its handle/flag to bypass the native ownership check.
            engine.mem_write(actual_private, bytes(0x1000))
            snapshot = bytearray(0xd64)
            snapshot[0x138:0x13c] = words(mode)
            engine.mem_write(master, bytes(snapshot))
            engine.mem_write(config, bytes(64))
            engine.mem_write(config + 0x10, words(shot))
            engine.mem_write(config + 0x1c, words(drive))
            engine.mem_write(drive, bytes(0x200))
            engine.mem_write(shot, bytes(0x200))
            engine.mem_write(DEBUG, bytes(0x100))
            prepare_visits.clear()
            # First stop is original diagnostic emission. No fake successful
            # logger return or image/job allocation occurs.
            prepare_stops = {BASE + 0xa18dc4, BASE + 0xa3c57a}
            for reg, value in ((UC_ARM_REG_R0, 0), (UC_ARM_REG_R1, handle),
                    (UC_ARM_REG_R2, subtype), (UC_ARM_REG_R3, 0x89abcdef),
                    (UC_ARM_REG_SP, STACK + 0x3000), (UC_ARM_REG_LR, STOP | 1)):
                engine.reg_write(reg, value)
            engine.emu_start((BASE + 0xa19be0) | 1, STOP, count=3000)
            assert engine.reg_read(UC_ARM_REG_PC) == BASE + 0xa18dc4
            assert prepare_visits == [BASE + 0xa05e6e]
            assert bytes(engine.mem_read(actual_private, 8)) == words(handle, 1)
            assert bytes(engine.mem_read(actual_private + 0x10, 4)) == words(0)
            assert engine.mem_read(actual_private + 0xd97, 1)[0] == 0
            # Separate post-diagnostic entry: its return value is unused and
            # overwritten by the original master getter immediately. Only the
            # established native callee-saved prepare context is retained.
            prepare_stops = {BASE + 0xa19c40, BASE + 0xa18dc4, BASE + 0xa3c57a}
            engine.emu_start((BASE + 0xa19c16) | 1, STOP, count=6000)
            assert engine.reg_read(UC_ARM_REG_PC) == BASE + 0xa19c40
            assert prepare_visits == [BASE + 0xa05e6e, BASE + 0xa06074], prepare_visits
            assert bytes(engine.mem_read(master, 0xd64)) == bytes(snapshot)
            assert bytes(engine.mem_read(MEM, 48)) == state
            results.append(bytes(engine.mem_read(actual_private, 0x1000)))
            # Release only this synthetic RESERVED parameter singleton (state1),
            # using its genuine acquired handle. This is not a RAW/image free.
            held = bytearray(engine.mem_read(actual_private, 0x1000))
            prepare_stops = {STOP, BASE + 0xa3c57a, BASE + 0xa18dc4}
            for reg, value in ((UC_ARM_REG_R0, handle), (UC_ARM_REG_SP, STACK + 0x3000),
                               (UC_ARM_REG_LR, STOP | 1)):
                engine.reg_write(reg, value)
            engine.emu_start((BASE + 0xa05fea) | 1, STOP, count=100)
            assert engine.reg_read(UC_ARM_REG_PC) == STOP
            held[4:8] = words(0)
            assert bytes(engine.mem_read(actual_private, 0x1000)) == bytes(held)
            # Original acquire clears the old derived flag; the subsequent
            # original producer must regenerate it for this new context.
            next_handle = handle + 1
            for reg, value in ((UC_ARM_REG_R0, next_handle), (UC_ARM_REG_R1, 0),
                    (UC_ARM_REG_R2, 0), (UC_ARM_REG_SP, STACK + 0x3000),
                    (UC_ARM_REG_LR, STOP | 1)):
                engine.reg_write(reg, value)
            engine.emu_start((BASE + 0xa05e6e) | 1, STOP, count=200)
            assert engine.reg_read(UC_ARM_REG_PC) == STOP
            assert bytes(engine.mem_read(actual_private, 8)) == words(next_handle, 1)
            assert engine.mem_read(actual_private + 0xd97, 1)[0] == 0
            engine.mem_write(STACK + 0x3000, words(subtype, 0x89abcdef))
            for reg, value in ((UC_ARM_REG_R0, next_handle), (UC_ARM_REG_R1, master),
                    (UC_ARM_REG_R2, 0), (UC_ARM_REG_R3, 0),
                    (UC_ARM_REG_SP, STACK + 0x3000), (UC_ARM_REG_LR, STOP | 1)):
                engine.reg_write(reg, value)
            engine.emu_start((BASE + 0xa06074) | 1, STOP, count=5000)
            assert engine.reg_read(UC_ARM_REG_PC) == STOP
            assert engine.mem_read(actual_private + 0xd97, 1)[0] == (int(subtype == 13) if engine is u else 0)
            assert bytes(engine.mem_read(MEM, 48)) == state
            parameter_reuse_cases += 1
        original, adapted = results
        expected = bytearray(original)
        expected[0xd97] = int(subtype == 13)  # Generation7 also covers late disabled requests.
        assert original[0xd97] == 0 and adapted == bytes(expected)
        assert adapted[:8] == words(handle, 1)
        assert adapted[0xd9c] == subtype
        prepare_cases += 1
    busy_parameter_cases = 0
    for engine in (baseline, u):
        held = bytearray(engine.mem_read(actual_private, 0x1000))
        held[:8] = words(0x76543210, 1)
        engine.mem_write(actual_private, bytes(held))
        prepare_visits.clear()
        prepare_stops = {BASE + 0xa3c57a, BASE + 0xa18dc4}
        for reg, value in ((UC_ARM_REG_R0, 0), (UC_ARM_REG_R1, handle),
                (UC_ARM_REG_R2, 13), (UC_ARM_REG_R3, 0),
                (UC_ARM_REG_SP, STACK + 0x3000), (UC_ARM_REG_LR, STOP | 1)):
            engine.reg_write(reg, value)
        engine.emu_start((BASE + 0xa19be0) | 1, STOP, count=3000)
        assert engine.reg_read(UC_ARM_REG_PC) == BASE + 0xa3c57a
        assert prepare_visits == [BASE + 0xa05e6e]
        assert bytes(engine.mem_read(actual_private, 0x1000)) == bytes(held)
        busy_parameter_cases += 1
    # Original request constructor -> event0x100 -> S1 -> native prepare args.
    # This proves the byte's provenance; it is not inferred from the current
    # arbiter value or a user-visible drive/shutter mode.
    root, controller, wire, event_copy = 0x1a52b38, 0x1a52c14, MEM + 0x600, MEM + 0x800
    u.mem_map(root & ~4095, 4096)  # Following debug page is already mapped.
    u.mem_write(root, original_owner_fixture(cp, root))
    provenance_stops = set()
    def provenance_trace(cpu, at, size, user):
        if at in provenance_stops:
            cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE, provenance_trace)
    u.ctl_remove_cache(BASE, BASE + len(cp))
    def part(start, end, inputs=()):
        nonlocal provenance_stops
        provenance_stops = {BASE + end}
        for reg, value in inputs:
            u.reg_write(reg, value)
        u.emu_start((BASE + start) | 1, STOP, count=2000)
        assert u.reg_read(UC_ARM_REG_PC) == BASE + end
    provenance_cases = 0
    for subtype, token, origin in itertools.product((1, 2, 13), (0, 0x12345678),
                                                   (0x90030001, 0x90040193)):
        timestamp = 0x89abcdef
        # Explicit pre-existing packet buffer for the post-allocation stores;
        # no allocator result or transport success is manufactured.
        u.mem_write(wire, bytes(24))
        u.mem_write(STACK + 0x3000 + 0x14, words(wire))
        part(0x9dbc20, 0x9dbc32, ((UC_ARM_REG_R4, timestamp), (UC_ARM_REG_R5, token),
            (UC_ARM_REG_R6, subtype), (UC_ARM_REG_SP, STACK + 0x3000)))
        assert bytes(u.mem_read(wire, 16)) == bytes([2, 0, 0x0c, 0x30]) + words(token, subtype, timestamp)
        # The real bridge posts8202, then100. Each post is a boundary.
        part(0x3ae064, 0x3adfe4, ((UC_ARM_REG_R0, wire), (UC_ARM_REG_R1, origin),
            (UC_ARM_REG_SP, STACK + 0x3000), (UC_ARM_REG_LR, STOP | 1)))
        posted = u.reg_read(UC_ARM_REG_R2)
        assert bytes(u.mem_read(posted, 16)) == words(0, 0x8202, token, origin)
        part(0x3ae16a, 0x3adfe4)  # Explicit post-first-send slice; return unused.
        posted = u.reg_read(UC_ARM_REG_R2)
        encoded = bytes(u.mem_read(posted, 32))
        assert encoded == words(0, 0x100, token, origin, subtype, timestamp, 0, 0)
        u.mem_write(event_copy, encoded)
        part(0x3accf0, 0xa186ba, ((UC_ARM_REG_R0, controller),
            (UC_ARM_REG_R1, event_copy + 4), (UC_ARM_REG_SP, STACK + 0x3000),
            (UC_ARM_REG_LR, STOP | 1)))
        assert u.reg_read(UC_ARM_REG_R0) == controller
        assert u.reg_read(UC_ARM_REG_R1) == event_copy + 4
        # Explicit slice after native busy/admission actions, not a fake
        # successful sensor/context transition.
        part(0xa18720, 0xa19be0, ((UC_ARM_REG_R4, controller),
            (UC_ARM_REG_R5, event_copy + 4), (UC_ARM_REG_SP, STACK + 0x3000)))
        assert [u.reg_read(reg) for reg in (UC_ARM_REG_R0, UC_ARM_REG_R1,
                UC_ARM_REG_R2, UC_ARM_REG_R3)] == [root + 0x108, token, subtype, timestamp]
        provenance_cases += 1
    report = dict(schema='OFFLINE_STATE_BOUND_NATIVE_FRAME_GATE/1',
        cp_sha256=digest, camera_io=False, firmware_candidate_written=False,
        cases=counts, lifecycle=lifecycle,
        only_native_parameter_flag_and_marker_written=True,
        stale_object_requires_real_producer=True,
        entire_native_parameter_producer_cases=full_cases,
        entire_producer_only_flag_differs=True,
        native_acquire_then_producer_cases=prepare_cases,
        native_acquisition_executed_without_fabricated_handle=True,
        acquisition_diagnostic_emission_omitted_explicitly=True,
        native_reserved_parameter_release_reacquire_producer_cases=parameter_reuse_cases,
        busy_singleton_reaches_original_diagnostic_before_change=busy_parameter_cases,
        native_capture_message_to_prepare_subtype_cases=provenance_cases,
        ordinary_requests_preserve_native_routing_while_enabled=True,
        late_request13_retains_donor_gate_decision_after_disable_or_fault=True,
        limits=['State address and code placement are emulator-only',
            'State lifetime, cross-task synchronization and native refresh delivery remain unbound',
            'No sensor, RAW storage, cancellation, capture start or save executed',
            'A cached parameter flag is not repaired by merely committing the enabled word',
            'Stage2 must see committed enabled before native cancellation release',
            'Instruction verification is not camera boot or physical capture acceptance'])
    (a.output / 'frame-gate-hook.private.json').write_text(
        json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'lifecycle'}, indent=2))


if __name__ == '__main__':
    main()
