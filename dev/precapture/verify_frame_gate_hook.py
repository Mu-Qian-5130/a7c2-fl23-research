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
from unicorn import UC_HOOK_MEM_WRITE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
    UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11,
    UC_ARM_REG_R12, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)
from audit_control import SPECS
from verify_capture_gate import Native
from verify_extension_layout import PINNED
from verify_offline import image_loader, codegen_flags, MEM, STACK, STOP

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

    def generate(enabled, pending, stage, fault, context, mode, flags, selection, marker):
        state = words(enabled, 1, 500, stage, pending, 0x4173, 0, 0x90030001,
                      0, 7, 0, fault)
        u.mem_write(MEM, state + bytes([0xa5]) * 16)
        params = bytearray([0x5a]) * 4096
        params[0x10:0x14] = words(context)
        params[0x160:0x164] = words(mode)
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
    for enabled, pending, stage, fault, context, mode, flags, selection, marker in itertools.product(
        (0, 1, 2), (0, 1), (0, 1, 2, 3), (0, 1), (0, 1),
        (0, 1, 0x1a, 0x21, 2), (0, 0x10), (0, 0x11, 0xff), (0, 1)):
        native = oracle_donor if enabled == 1 and not fault else oracle_target
        want = native.propagate(context, mode, enabled, flags, selection, marker)
        actual = generate(enabled, pending, stage, fault, context, mode, flags, selection, marker)
        assert actual == want
        key = 'original_donor_equivalence' if native is oracle_donor else 'original_target_equivalence'
        counts[key] += 1
    # A queued request cannot retroactively update an existing parameter object.
    # Demonstrate stale old flag, then execute the real producer and consumer
    # afresh. This test does NOT claim to deliver the required refresh event.
    lifecycle = []
    for label, enabled, pending, stage in [('disabled', 0, 0, 0),
            ('pending-enable', 0, 1, 1), ('committed-before-release', 1, 1, 2),
            ('enabled', 1, 1, 0), ('pending-disable', 1, 0, 1),
            ('disabled-before-release', 0, 0, 2)]:
        flag, marker = generate(enabled, pending, stage, 0, 0, 1, 0, 0, 1)
        assert flag == enabled and marker == (2 if enabled else 1)
        lifecycle.append(dict(stage=label, generated_flag=flag, frame_marker=marker))
    # Change only committed state while retaining the previously built object.
    generate(0, 1, 1, 0, 0, 1, 0, 0, 1)
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
    for context, mode, phase, option in itertools.product((0, 1), (1, 2), (0, 2), (0, 1)):
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
            engine.mem_write(STACK + 0x3000, words(option, 0x87654321))
            saved = {reg: 0xc0000000 + n for n, reg in enumerate((UC_ARM_REG_R4,
                UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R8,
                UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11))}
            for reg, value in {**saved, UC_ARM_REG_R0: handle, UC_ARM_REG_R1: source,
                    UC_ARM_REG_R2: option, UC_ARM_REG_R3: 0,
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
        want[0xd97] = int(context == 0)
        assert original[0xd97] == 0
        assert adapted == bytes(want)
        assert struct.unpack_from('<I', adapted, 0x160)[0] == mode
        full_cases += 1
    report = dict(schema='OFFLINE_STATE_BOUND_NATIVE_FRAME_GATE/1',
        cp_sha256=digest, camera_io=False, firmware_candidate_written=False,
        cases=counts, lifecycle=lifecycle,
        only_native_parameter_flag_and_marker_written=True,
        stale_object_requires_real_producer=True,
        entire_native_parameter_producer_cases=full_cases,
        entire_producer_only_flag_differs=True,
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
