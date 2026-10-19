"""Bind native formal-recording reference decisions to independent state.

Emulator-only fixture: no modified firmware is emitted, no enqueue executes,
no RAW image or SD file exists. Original native callbacks/duplicate guards
run only to their actual enqueue boundary or unchanged native continuation.
"""
import argparse
import hashlib
import itertools
import json
import struct
import subprocess
from pathlib import Path

from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R8, UC_ARM_REG_R9,
    UC_ARM_REG_R10, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)
from audit_owner_binding import original_owner_fixture
from trace_shutter_edges import NativeEdges
from verify_entry_hooks import BASE, ROOT, CONTROLLER
from verify_extension_layout import PINNED
from verify_offline import image_loader, codegen_flags, MEM, STACK, STOP

DEBUG = 0x1a533a4
CONTEXT = ROOT + 0x108
ENQUEUE, END, AT = [BASE + n for n in (0x407f1c, 0x3ad576, 0x3ad55a)]


def words(*v):
    return struct.pack('<' + 'I' * len(v), *v)


def assembly():
    return f'''.syntax unified
.thumb
.text
.global reference_hook_fixture
.type reference_hook_fixture,%function
.thumb_func
reference_hook_fixture:
    push {{r1,r2,r3,r4,r12,lr}}
    ldrb.w r1,[r0,#0xf1]
    mov r2,r6
    ldr r3,[r5,#0xc]
    ldrb r3,[r3,#0x2d]
    ldr r0,={MEM:#x}
    bl precapture_target_reference_flags
    pop {{r1,r2,r3,r4,r12,lr}}
    ldr pc,={BASE + 0x3ad55f:#x}
.size reference_hook_fixture,.-reference_hook_fixture
'''


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
    stub = a.output / 'emulator-only-reference-fixture.S'
    stub.write_text(assembly(), encoding='ascii')
    elf = a.output / 'thumb-reference-fixture.elf'
    command = [str(a.zig), 'cc', '-target', 'thumb-linux-gnueabi',
        *codegen_flags('thumb'), '-Oz', '-g', '-shared', '-fPIC', '-ffreestanding',
        '-fno-builtin', '-fno-stack-protector', '-fno-unwind-tables',
        '-fno-asynchronous-unwind-tables', '-nostdlib', '-Wl,--no-undefined,-Bsymbolic',
        '-o', str(elf), str(stub), str(Path(__file__).with_name('cp_frame_gate_adapter.c')),
        str(Path(__file__).with_name('capture_gate.c'))]
    build = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if build.returncode:
        raise RuntimeError(build.stderr[-2500:])
    u, symbols = image_loader(elf, 'thumb', ('reference_hook_fixture',))
    u.mem_map(BASE, (len(cp) + 4095) & ~4095)
    u.mem_write(BASE, cp)
    u.mem_map(ROOT & ~4095, 0x2000)
    fixture = original_owner_fixture(cp, ROOT)
    ks = Ks(KS_ARCH_ARM, KS_MODE_THUMB)
    assert cp[AT - BASE:AT - BASE + 4] == bytes(ks.asm('ldrb.w r0,[r0,#0xf1]')[0])
    patch = bytes(ks.asm(f'b.w {symbols["reference_hook_fixture"] & ~1:#x}', addr=AT)[0])
    assert len(patch) == 4
    u.mem_write(AT, patch)
    oracle = NativeEdges(cp)
    boundaries = []
    def trace(cpu, at, size, user):
        if at not in (ENQUEUE, END):
            return
        args = [cpu.reg_read(r) for r in
                (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)]
        boundaries.append(dict(boundary=at, args=args,
            callback=struct.unpack('<I', cpu.mem_read(args[1] + 8, 4))[0]
                if at == ENQUEUE else None))
        cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE, trace)
    counts = dict(native_forwarded=0, enabled_reference=0, fault_or_transition_drain=0,
                  native_duplicate_suppressed=0, subtype13_skipped=0)
    for enabled, stage, fault, flags, active, pressed, subtype in itertools.product(
        (0, 1), (0, 1, 2, 3), (0, 1), (0, 1, 0x11, 0x80), (0, 1), (0, 1), (1, 2, 13)):
        state = words(enabled, 1, 500, stage, 1, 0x4173, 0, 0x90030001, 0, 7, 0, fault)
        u.mem_write(MEM, state + bytes([0xa5]) * 16)
        u.mem_write(ROOT, fixture)
        u.mem_write(CONTEXT + 0x2d, bytes([active]))
        u.mem_write(DEBUG + 0xf0, bytes([0, flags]))
        before = bytes(u.mem_read(ROOT, 0x600))
        sequence, timestamp = 0x12345678, 0x89abcdef
        for reg, value in ((UC_ARM_REG_R5, CONTROLLER), (UC_ARM_REG_R6, pressed),
                (UC_ARM_REG_R8, sequence), (UC_ARM_REG_R9, subtype),
                (UC_ARM_REG_R10, timestamp), (UC_ARM_REG_SP, STACK + 0x3000),
                (UC_ARM_REG_LR, STOP | 1)):
            u.reg_write(reg, value)
        boundaries.clear()
        u.emu_start((BASE + 0x3ad54c) | 1, STOP, count=700)
        assert len(boundaries) == 1 and u.reg_read(UC_ARM_REG_PC) == boundaries[0]['boundary']
        changed_gate = (enabled == 1 and not fault) or (
            not pressed and active and (fault or stage in (1, 2)))
        effective_flags = flags | int(changed_gate)
        original = oracle.reference(effective_flags, active, pressed, subtype, sequence, timestamp)
        got = boundaries[0]
        expected_enqueue = original['request'] == 'enqueue-reference'
        assert (got['boundary'] == ENQUEUE) == expected_enqueue
        assert bytes(u.mem_read(ROOT, 0x600)) == before
        assert bytes(u.mem_read(MEM, 64)) == state + bytes([0xa5]) * 16
        assert u.mem_read(DEBUG + 0xf1, 1)[0] == flags
        if expected_enqueue:
            assert got['args'][0] == 0x1a3aae0
            assert got['callback'] == int(original['callback_va'], 16)
            assert got['args'][2:] == [sequence, timestamp if pressed else 0]
            assert got['callback'] == (0x474fad if pressed else 0x475015)
        if subtype == 13:
            assert not expected_enqueue
            counts['subtype13_skipped'] += 1
        elif pressed == active:
            assert not expected_enqueue
            counts['native_duplicate_suppressed'] += 1
        if not changed_gate:
            counts['native_forwarded'] += 1
        elif not fault and enabled:
            counts['enabled_reference'] += 1
        else:
            assert not pressed and active
            counts['fault_or_transition_drain'] += 1
    report = dict(schema='OFFLINE_STATE_BOUND_NATIVE_RECORDING_REFERENCE/1',
        cp_sha256=digest, camera_io=False, firmware_candidate_written=False,
        counts=counts, native_enqueue_executed=False, native_flags_unchanged=True,
        native_owner_and_state_unchanged_before_enqueue=True,
        limits=['Code/state placement and hook exist only in emulator RAM',
            'Opening reference callback is not evidence of pre-trigger pixels or saved photos',
            'Actual callback delivery, context lifetime, capture-end and cancellation remain unverified',
            'Fault/pending drain only permits the existing native stop callback; it does not fake delivery',
            'No OS success, parameter changes or image storage are fabricated'])
    (a.output / 'reference-hook.private.json').write_text(
        json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
