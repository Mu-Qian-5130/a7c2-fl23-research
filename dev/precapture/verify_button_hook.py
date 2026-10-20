"""Emulator-only post-button-update hook, with original S1 edge comparison.

No firmware image is saved. Actual native start/stop/send helpers are stop
boundaries; AF/AE postprocessing is rejoined, not simulated successful.
"""
import argparse
import hashlib
import itertools
import json
import struct
from pathlib import Path

from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R8,
    UC_ARM_REG_R9, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_CPSR)
from support.reference import SPECS
from support.cp_owner import original_owner_fixture
from audit_owner_binding import words
from trace_shutter_edges import NativeEdges
from verify_entry_hooks import BASE, ROOT, MASTER, OPS, CONTROLLER, SEND, POST, REPLY
from support.build import compile_shared
from support.elf import image_loader
from support.memory import MEM, STACK, STOP

DEBUG, EVENT = 0x1A533A4, MEM + 0x600
NATIVE_END, START, END, RECOMPUTE, DIAGNOSTIC = [BASE + at for at in
    (0x3AD5EE, 0xA1AD9A, 0xA1ADB2, 0xA1ACFE, 0xA3C57A)]


def assembly():
    return f'''.syntax unified
.thumb
.text
.global button_hook_fixture
.type button_hook_fixture,%function
.thumb_func
button_hook_fixture:
    push {{r0,r1,r2,r3,r12,lr}}
    mrs r12,apsr
    push {{r12,lr}}
    mov r2,r5
    ldr r0,={MEM:#x}
    ldr r1,={OPS:#x}
    bl precapture_target_button_event
    cmp r0,#0
    bne 1f
    pop {{r12,lr}}
    msr APSR_nzcvq,r12
    pop {{r0,r1,r2,r3,r12,lr}}
    ldrb.w r2,[r10,#0xf1]
    ldr pc,={BASE + 0x3AD309:#x}
1:
    pop {{r12,lr}}
    msr APSR_nzcvq,r12
    pop {{r0,r1,r2,r3,r12,lr}}
    ldr pc,={NATIVE_END | 1:#x}
.size button_hook_fixture,.-button_hook_fixture
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp', type=Path, required=True)
    parser.add_argument('--zig', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cp = args.cp.read_bytes()
    if hashlib.sha256(cp).hexdigest() != SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported original target')
    args.output.mkdir(parents=True, exist_ok=False)
    stub = args.output / 'emulator-only-button-fixture.S'
    stub.write_text(assembly(), encoding='ascii')
    elf = args.output / 'thumb-button-fixture.elf'
    sources = ['cp_entry_adapters.c', 'cp_task_adapter.c', 'cp_owner_binding.c',
               'cp_backend.c', 'cp_control_state.c', 's1_trigger.c', 'capture_gate.c']
    compile_shared(args.zig, 'thumb', elf,
        [stub, *[Path(__file__).with_name(s) for s in sources]])
    u, symbols = image_loader(elf, 'thumb', ('button_hook_fixture',))
    u.mem_map(BASE, (len(cp) + 4095) & ~4095)
    u.mem_write(BASE, cp)
    u.mem_map(ROOT & ~4095, 0x2000)
    u.mem_map(MASTER & ~4095, 0x2000)
    fixture = original_owner_fixture(cp, ROOT)
    ks = Ks(KS_ARCH_ARM, KS_MODE_THUMB)
    at = BASE + 0x3AD304
    assert cp[0x3AD304:0x3AD308] == bytes(ks.asm('ldrb.w r2,[r10,#0xf1]')[0])
    patch = bytes(ks.asm(f'b.w {symbols["button_hook_fixture"] & ~1:#x}', addr=at)[0])
    assert len(patch) == 4
    u.mem_write(at, patch)
    observed, inline = [], []
    def trace(cpu, address, size, user):
        if address == at:
            inline.append(cpu.reg_read(UC_ARM_REG_CPSR) & 0xF8000000)
        if address in (NATIVE_END, START, END, RECOMPUTE, DIAGNOSTIC, SEND, POST, REPLY):
            observed.append(dict(boundary=address, args=[cpu.reg_read(r) for r in
                (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)], executed=False))
            cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE, trace)
    def run(old, pressed, index, flags, enabled=0, requested=0, phase=0, fault=0, trigger=1):
        u.mem_write(ROOT, fixture)
        u.mem_write(CONTROLLER + 0x24, words(old))
        u.mem_write(DEBUG + 0xF0, bytes([0, flags]))
        u.mem_write(MASTER, bytes(0xD64))
        u.mem_write(MASTER + 0x138, words(1))
        u.mem_write(MASTER + 0x700, words(1))
        state = words(enabled, trigger, 500, phase, enabled, 0x4173, 0, 0x90030001,
                      requested, 7, 0, fault)
        u.mem_write(MEM, state + bytes([0xA5]) * 16)
        u.mem_write(OPS, words(SEND | 1, POST | 1, (BASE + 0xA17EAE) | 1, REPLY | 1))
        u.mem_write(EVENT, words(0x8205, 0, 0, pressed, index, 0, 0))
        before = bytearray(u.mem_read(ROOT, 0x600))
        mask = old | (1 << index) if pressed else old & ~(1 << index)
        struct.pack_into('<I', before, 0xDC + 0x24, mask)
        for reg, value in ((UC_ARM_REG_R4, EVENT), (UC_ARM_REG_R5, CONTROLLER),
                (UC_ARM_REG_R9, 0x40002), (UC_ARM_REG_SP, STACK + 0x3000),
                (UC_ARM_REG_LR, STOP | 1)):
            u.reg_write(reg, value)
        observed.clear();inline.clear()
        u.emu_start(BASE + 0x3AD1BB, STOP, count=3000)
        assert len(observed) == 1 and u.reg_read(UC_ARM_REG_PC) == observed[0]['boundary']
        assert bytes(u.mem_read(ROOT, 0x600)) == bytes(before)
        assert bytes(u.mem_read(MEM, 48)) == state
        assert bytes(u.mem_read(MEM + 48, 16)) == bytes([0xA5]) * 16
        assert len(inline) == 1
        return observed[0], mask
    class ExtendedEdges(NativeEdges):
        def run(self, address):
            self.stop[0xA1ACFE] = 'native-debug-recompute'
            self.stop[0xA3C57A] = 'native-diagnostic'
            return super().run(address)
    oracle = ExtendedEdges(cp)
    oracle.u.mem_map(0xA3C000, 0x1000)
    oracle.u.mem_write(0xA3C000, cp[0xA3C000:0xA3D000])
    cases = []
    for flags, old, pressed, index in itertools.product((0, 1, 0x11, 0x21, 0x41),
            (0, 2, 0x40000, 0x40002), (0, 1), (1, 18)):
        expected = oracle.edge(flags, old, pressed, index)
        item, mask = run(old, pressed, index, flags)
        label = {START: 'start-helper', END: 'stop-helper', NATIVE_END: 'none',
                 RECOMPUTE: 'native-debug-recompute', DIAGNOSTIC: 'native-diagnostic'}[item['boundary']]
        assert label == expected['request'] and mask == expected['updated_mask']
        cases.append(dict(kind='disabled-native-equivalence', flags=flags, old=old,
            pressed=pressed, index=index, boundary=hex(item['boundary']), executed=False))
    for old, pressed, index, enabled, requested, phase, fault, trigger, command in [
        (0, 1, 1, 1, 0, 0, 0, 1, 0x4038),
        (2, 0, 1, 1, 1, 0, 0, 1, 0x4039),
        (2, 0, 1, 0, 1, 0, 0, 1, 0x4039),
        (2, 1, 1, 1, 1, 0, 0, 1, None),
        (0, 0, 1, 1, 0, 0, 0, 1, None),
        (0, 1, 1, 1, 0, 1, 0, 1, None),
        (0, 1, 1, 1, 0, 0, 1, 1, None),
        (0, 1, 18, 1, 0, 0, 0, 1, None),
        (0, 1, 18, 1, 0, 0, 0, 3, 0x4038),
    ]:
        item, mask = run(old, pressed, index, 0, enabled, requested, phase, fault, trigger)
        if command is None:
            assert item['boundary'] == NATIVE_END
            assert u.reg_read(UC_ARM_REG_CPSR) & 0xF8000000 == inline[0]
        else:
            assert item['boundary'] == SEND
            packet, size, route = item['args'][:3]
            assert size == 16 and route == 0x90040193
            assert bytes(u.mem_read(packet, size)) == struct.pack('<BBHI8B', 5, 0, command, 0, 13, 0, 0, 0, 0, 0, 0, 0)
        cases.append(dict(kind='active-owner-decision', enabled=enabled, requested=requested,
            pressed=pressed, index=index, pending=phase, fault=fault, trigger=trigger,
            mask=mask, boundary=hex(item['boundary']), command=command, executed=False))
    report = dict(schema='OFFLINE_POST_BUTTON_UPDATE_HOOK_FIXTURE/1', camera_io=False,
        firmware_candidate_written=False, cases=cases,
        limits=['Only emulator RAM contains the branch substitution',
                'Native mask update executes, all native send/start/stop helpers stop before execution',
                'AF/AE postprocessing is rejoined but not executed or physically validated',
                'Actual initialized state, code placement, capture-end synchronization and installation remain unbound'])
    (args.output / 'button-hook.private.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f'{len(cases)} original/native-owner button-hook cases passed. No camera I/O.')


if __name__ == '__main__':
    main()
