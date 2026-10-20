"""Execute two hook fixtures with original queue/pop/size instructions.

Fixture state/ops live only at synthetic emulator addresses. No installable
placement or firmware image is produced. Queue-free, dispatch, send and reply
are stop boundaries; native metadata enqueue/pop execute, not sensor capture.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
    UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11,
    UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_CPSR)
from support.reference import SPECS
from support.cp_owner import original_owner_fixture
from audit_owner_binding import words
from support.build import compile_shared
from support.elf import image_loader
from support.memory import MEM, STACK, STOP

BASE, ROOT, MASTER = 0x108000, 0x1A52B38, 0x165A720
OPS, MESSAGE = MEM + 0x100, MEM + 0x600
RING, CONTROLLER = ROOT + 0x398, ROOT + 0xDC
SEND, POST, DEFER, REPLY = [BASE + at for at in (0x3ABC48, 0x3ADFE4, 0xA17EAE, 0x7D2A14)]
FREE, DISPATCH, ADMISSION = [BASE + at for at in (0x45D300, 0x3ABE90, 0xA18126)]
PRESERVED = (UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
             UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11)


def assembly():
    return f'''.syntax unified
.thumb
.text
.global queue_hook_fixture
.type queue_hook_fixture,%function
.thumb_func
queue_hook_fixture:
    push {{r4,r5,r6,lr}}
    mov r4,r0
    mov r5,r1
    mov r2,r0
    mov r3,r1
    ldr r0,={MEM:#x}
    ldr r1,={OPS:#x}
    bl precapture_target_queue_event
    cmp r0,#0
    beq 1f
    pop {{r4,r5,r6,pc}}
1:
    mov r0,r4
    mov r1,r5
    pop {{r4,r5,r6,lr}}
    ldr r12,={DISPATCH | 1:#x}
    bx r12
.size queue_hook_fixture,.-queue_hook_fixture
.global replay_hook_fixture
.type replay_hook_fixture,%function
.thumb_func
replay_hook_fixture:
    push {{r0,r1,r2,r3,r12,lr}}
    mrs r12,apsr
    push {{r12,lr}}
    mov r3,r1
    mov r2,r8
    ldr r0,={MEM:#x}
    ldr r1,={OPS:#x}
    bl precapture_target_replay_event
    cmp r0,#0
    bne 2f
    pop {{r12,lr}}
    msr APSR_nzcvq,r12
    pop {{r0,r1,r2,r3,r12,lr}}
    ldr.w r0,[r8]
    ldr pc,={BASE + 0xA18127:#x}
2:
    pop {{r12,lr}}
    msr APSR_nzcvq,r12
    pop {{r0,r1,r2,r3,r12,lr}}
    ldr pc,={BASE + 0xA1814F:#x}
.size replay_hook_fixture,.-replay_hook_fixture
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
    stub = args.output / 'emulator-only-entry-fixtures.S'
    stub.write_text(assembly(), encoding='ascii')
    elf = args.output / 'thumb-entry-fixtures.elf'
    sources = ['cp_entry_adapters.c', 'cp_task_adapter.c', 'cp_owner_binding.c',
               'cp_backend.c', 'cp_control_state.c', 's1_trigger.c', 'capture_gate.c']
    compile_shared(args.zig, 'thumb', elf,
        [stub, *[Path(__file__).with_name(s) for s in sources]])
    u, symbols = image_loader(elf, 'thumb', ('queue_hook_fixture', 'replay_hook_fixture'))
    u.mem_map(BASE, (len(cp) + 4095) & ~4095)
    u.mem_write(BASE, cp)
    u.mem_map(ROOT & ~4095, 0x2000)
    u.mem_map(MASTER & ~4095, 0x2000)
    fixture = original_owner_fixture(cp, ROOT)
    ks = Ks(KS_ARCH_ARM, KS_MODE_THUMB)
    assert cp[0x3AE6F4:0x3AE6F8] == bytes(ks.asm(f'bl {DISPATCH:#x}', addr=BASE + 0x3AE6F4)[0])
    assert cp[0xA18122:0xA18126] == bytes(ks.asm('ldr.w r0,[r8]')[0])
    for offset, opcode, symbol in [(0x3AE6F4, 'bl', 'queue_hook_fixture'),
                                   (0xA18122, 'b.w', 'replay_hook_fixture')]:
        patch = bytes(ks.asm(f'{opcode} {symbols[symbol] & ~1:#x}', addr=BASE + offset)[0])
        assert len(patch) == 4
        u.mem_write(BASE + offset, patch)  # Emulator-only; no image saved.
    calls, active_boundaries, actual_defer, replay_inline = [], set(), [], []
    def trace(cpu, address, size, user):
        if address == BASE + 0xA18122:
            replay_inline.append(dict(flags=cpu.reg_read(UC_ARM_REG_CPSR) & 0xF8000000,
                args=[cpu.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)]))
        if address == DEFER:
            actual_defer.append([cpu.reg_read(UC_ARM_REG_R0), cpu.reg_read(UC_ARM_REG_R1)])
        if address in active_boundaries:
            calls.append(dict(boundary=hex(address), args=[cpu.reg_read(r) for r in
                (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)], executed=False))
            cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE, trace)
    def setup(generation=6, length=32, cookie=0x50435231, busy=0, kind=0, event=0x8240, cursor=0):
        u.mem_write(ROOT, fixture)
        u.mem_write(ROOT + 0x108 + 0xC, words(busy))
        u.mem_write(RING + 0x234, words(cursor, cursor))
        u.mem_write(MASTER, bytes(0xD64))
        u.mem_write(MASTER + 0x138, words(1))
        u.mem_write(MASTER + 0x700, words(1))
        u.mem_write(MEM, words(0, 1, 500, 1, 1, 0x4173, 0x12345678, 0x90030001,
                               0, 7, 0, 0) + bytes([0xA5]) * 16)
        u.mem_write(OPS, words(SEND | 1, POST | 1, DEFER | 1, REPLY | 1))
        u.mem_write(MESSAGE - 0x18, bytes([0xA5]) * 0x80)
        u.mem_write(MESSAGE - 8, words(length))
        u.mem_write(MESSAGE, words(kind, event, generation, 1, 1, cookie, 0, 0))
        active_boundaries.clear()
        active_boundaries.update((FREE, DISPATCH, SEND, POST, REPLY))
        calls.clear()
        actual_defer.clear()
        replay_inline.clear()
    def run_queue(expected, root=ROOT):
        sp = STACK + 0x2800
        values = (0x900302D9, sp + 0x10, 0x12345678, 0x76543210, 0, root, 0x34567890, 0x456789A0)
        for reg, value in zip(PRESERVED, values):
            u.reg_write(reg, value)
        u.mem_write(sp + 0x10, words(MESSAGE))
        u.reg_write(UC_ARM_REG_SP, sp)
        u.emu_start(BASE + 0x3AE6EB, 0xFFFFFFFF, count=5000)
        assert len(calls) == 1 and u.reg_read(UC_ARM_REG_PC) == expected
        assert [u.reg_read(r) for r in PRESERVED] == list(values[:2]) + [MESSAGE] + list(values[3:])
        assert u.reg_read(UC_ARM_REG_SP) == sp
        assert bytes(u.mem_read(MEM + 48, 16)) == bytes([0xA5]) * 16
        if expected == FREE:
            assert calls[0]['args'][:2] == [0x900302D9, MESSAGE]
        elif expected == DISPATCH:
            assert calls[0]['args'][:2] == [root, MESSAGE]
        return dict(calls[0])
    cases = []
    for label, kwargs, expected in [
        ('ordinary-group0', dict(event=0x8205), DISPATCH),
        ('ordinary-group1', dict(kind=1), DISPATCH),
        ('stale-private', {}, FREE), ('bad-cookie', dict(cookie=0), FREE),
        ('truncated-private', dict(length=28), FREE), ('oversized-private', dict(length=36), FREE),
        ('short-allocation', dict(length=3), FREE), ('short-group0', dict(length=4), FREE),
        ('invalid-size', dict(length=4097), FREE), ('negative-size', dict(length=0xFFFFFC00), FREE),
    ]:
        setup(**kwargs)
        before = bytes(u.mem_read(MEM, 48))
        native_before = bytes(u.mem_read(ROOT, 0x600))
        item = run_queue(expected)
        assert bytes(u.mem_read(MEM, 48)) == before
        assert bytes(u.mem_read(ROOT, 0x600)) == native_before
        cases.append(dict(label=label, boundary=item))
    setup()
    cases.append(dict(label='wrong-root-private', boundary=run_queue(FREE, ROOT + 4)))
    # Real original enqueue and pop, including wrap. The private event is
    # stale so replay completes without any simulated successful transport.
    for cursor in (0, 7, 19):
        setup(generation=7, busy=1, cursor=cursor)
        payload = bytes(u.mem_read(MESSAGE + 4, 28))
        before_state = bytes(u.mem_read(MEM, 48))
        item = run_queue(FREE)
        assert len(actual_defer) == 1 and actual_defer[0][0] == RING
        assert bytes(u.mem_read(RING + 4 + 28 * cursor, 28)) == payload
        next_cursor = (cursor + 1) % 20
        assert bytes(u.mem_read(RING + 0x234, 8)) == words(cursor, next_cursor)
        assert bytes(u.mem_read(MEM, 48)) == before_state
        # Make the retained event stale without modifying native queue bytes.
        u.mem_write(MEM + 36, words(8))
        u.mem_write(ROOT + 0x108 + 0xC, words(0))
        calls.clear();actual_defer.clear()
        values = [0x12340000 + n for n in range(8)]
        for reg, value in zip(PRESERVED, values):
            u.reg_write(reg, value)
        u.reg_write(UC_ARM_REG_R0, CONTROLLER)
        u.reg_write(UC_ARM_REG_SP, STACK + 0x3000)
        u.reg_write(UC_ARM_REG_LR, STOP | 1)
        u.emu_start(BASE + 0xA180FD, STOP, count=5000)
        assert u.reg_read(UC_ARM_REG_PC) == STOP and not calls and not actual_defer
        assert [u.reg_read(r) for r in PRESERVED] == values
        assert u.reg_read(UC_ARM_REG_SP) == STACK + 0x3000
        assert bytes(u.mem_read(RING + 0x234, 8)) == words(next_cursor, next_cursor)
        cases.append(dict(label='native-enqueue-pop-private-replay', initial_cursor=cursor,
            native_free_boundary=item, replay_returned=True, transport_executed=False))
    # A live retained event reaches the actual cancel helper after native pop;
    # no IPC free is attempted for its stack-copy replay.
    setup(generation=7, busy=1)
    run_queue(FREE)
    u.mem_write(ROOT + 0x108 + 0xC, words(0))
    calls.clear();actual_defer.clear()
    u.reg_write(UC_ARM_REG_R0, CONTROLLER)
    u.reg_write(UC_ARM_REG_SP, STACK + 0x3000)
    u.reg_write(UC_ARM_REG_LR, STOP | 1)
    u.emu_start(BASE + 0xA180FD, STOP, count=5000)
    assert u.reg_read(UC_ARM_REG_PC) == SEND and len(calls) == 1
    assert calls[0]['args'][1:3] == [16, 0x90040193]
    assert bytes(u.mem_read(RING + 0x234, 8)) == words(1, 1)
    cases.append(dict(label='live-private-replay', boundary=dict(calls[0]), stack_event_not_freed=True))
    # Ordinary replay restores the overwritten native load and rejoins before
    # the original admission call, without executing that admission predicate.
    setup(event=0x8205)
    u.mem_write(RING + 4, bytes(u.mem_read(MESSAGE + 4, 28)))
    u.mem_write(RING + 0x238, words(1))
    active_boundaries.add(ADMISSION)
    u.reg_write(UC_ARM_REG_R0, CONTROLLER)
    u.reg_write(UC_ARM_REG_SP, STACK + 0x3000)
    u.reg_write(UC_ARM_REG_LR, STOP | 1)
    u.emu_start(BASE + 0xA180FD, STOP, count=5000)
    assert u.reg_read(UC_ARM_REG_PC) == ADMISSION and len(calls) == 1
    assert u.reg_read(UC_ARM_REG_R0) == 0xE77B40
    assert len(replay_inline) == 1
    assert u.reg_read(UC_ARM_REG_CPSR) & 0xF8000000 == replay_inline[0]['flags']
    assert [u.reg_read(r) for r in (UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)] == replay_inline[0]['args'][1:]
    assert bytes(u.mem_read(u.reg_read(UC_ARM_REG_R1), 28)) == bytes(u.mem_read(MESSAGE + 4, 28))
    assert bytes(u.mem_read(RING + 0x234, 8)) == words(1, 1)
    cases.append(dict(label='ordinary-replay-rejoins-native', boundary=dict(calls[0])))
    report = dict(schema='OFFLINE_TWO_NATIVE_ENTRY_HOOK_FIXTURES/1', camera_io=False,
        source_sha256=hashlib.sha256(cp).hexdigest(), cases=cases,
        firmware_candidate_written=False, limits=[
            'Only emulator RAM contains branch substitutions; fixture state addresses are not camera storage',
            'Native metadata enqueue/pop execute; native free/send/reply stop before execution',
            'Ordinary queue dispatch stops at its original entry; ordinary replay stops before admission',
            'No sensor exposure, actual pixel buffers, capture ACK or pre-trigger photo is established',
            'Actual hook placement/state lifecycle/cache synchronization and installation remain unverified'])
    (args.output / 'entry-hooks.private.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f'{len(cases)} two-entry native-flow cases passed. No camera I/O or installable image.')


if __name__ == '__main__':
    main()
