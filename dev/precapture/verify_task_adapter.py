"""Exercise task-entry adaptation against original native owner layout.

This does not install the required manager hook. Real send/reply/defer
operations are stop boundaries, never successful transport mocks.
"""
import argparse
import hashlib
import json
import struct
import subprocess
from pathlib import Path

from unicorn import UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)
from support.reference import SPECS
from audit_owner_binding import original_owner_fixture, words
from support.elf import image_loader, codegen_flags
from support.memory import MEM, STACK, STOP

ROOT, MASTER = 0x1A52B38, 0x165A720
OPS, EVENT = MEM + 0x100, MEM + 0x400
SEND, POST, DEFER, REPLY = [0x108000 + at for at in (0x3ABC48, 0x3ADFE4, 0xA17EAE, 0x7D2A14)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp', type=Path, required=True)
    parser.add_argument('--zig', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cp = args.cp.read_bytes()
    if hashlib.sha256(cp).hexdigest() != SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported original CP')
    fixture = original_owner_fixture(cp, ROOT)
    args.output.mkdir(parents=True, exist_ok=False)
    elf = args.output / 'thumb-task-adapter.elf'
    sources = ['cp_task_adapter.c', 'cp_owner_binding.c', 'cp_backend.c',
               'cp_control_state.c', 's1_trigger.c', 'capture_gate.c']
    command = [str(args.zig), 'cc', '-target', 'thumb-linux-gnueabi',
        *codegen_flags('thumb'), '-Oz', '-g', '-shared', '-fPIC', '-ffreestanding',
        '-fno-builtin', '-fno-stack-protector', '-fno-unwind-tables',
        '-fno-asynchronous-unwind-tables', '-nostdlib', '-Wl,--no-undefined,-Bsymbolic',
        '-o', str(elf), *[str(Path(__file__).with_name(s)) for s in sources]]
    build = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if build.returncode:
        raise RuntimeError(build.stderr[-2500:])
    u, symbols = image_loader(elf, 'thumb', ('precapture_target_task_event',))
    u.mem_map(ROOT & ~4095, 0x2000)
    u.mem_map(MASTER & ~4095, 0x2000)
    for at in (SEND, POST, DEFER, REPLY):
        page = at & ~4095
        u.mem_map(page, 4096)
        u.mem_write(page, cp[page - 0x108000:page - 0x108000 + 4096])
    boundaries = []
    def stop(cpu, address, size, user):
        if address in (SEND, POST, DEFER, REPLY):
            boundaries.append(dict(address=hex(address),
                args=[cpu.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)],
                native_operation_executed=False))
            cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE, stop)
    def setup(event=0x8240, generation=7, phase=1, desired=1, cookie=0x50435231):
        u.mem_write(MEM, words(0, 1, 500, 1, 1, 0x4173, 0x12345678, 0x90030001,
                               0, 7, 0, 0) + bytes([0xA5]) * 16)
        u.mem_write(OPS, words(SEND | 1, POST | 1, DEFER | 1, REPLY | 1))
        u.mem_write(EVENT, words(event, generation, phase, desired, cookie, 0, 0))
        u.mem_write(ROOT, fixture)
        u.mem_write(MASTER, bytes(0xD64))
        u.mem_write(MASTER + 0x138, words(1))
        u.mem_write(MASTER + 0x700, words(1))
    def call(length=28, manager=ROOT + 0x98, state=MEM, event=EVENT, expected=None):
        count = len(boundaries)
        native_before = bytes(u.mem_read(ROOT, 0x600))
        for reg, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3),
                              (state, OPS, manager, event)):
            u.reg_write(reg, value)
        u.mem_write(STACK + 0x3000, words(length))
        u.reg_write(UC_ARM_REG_SP, STACK + 0x3000)
        u.reg_write(UC_ARM_REG_LR, STOP | 1)
        u.emu_start(symbols['precapture_target_task_event'], STOP, count=3000)
        assert bytes(u.mem_read(MEM + 48, 16)) == bytes([0xA5]) * 16
        assert bytes(u.mem_read(ROOT, 0x600)) == native_before
        if expected is None:
            assert u.reg_read(UC_ARM_REG_PC) == STOP and len(boundaries) == count
            return u.reg_read(UC_ARM_REG_R0) & 0xFFFFFFFF
        assert u.reg_read(UC_ARM_REG_PC) == expected and len(boundaries) == count + 1
        return boundaries[-1]
    passed = []
    for code in (0x100, 0x8205, 0x8206, 0x8300):
        setup(event=code)
        before = bytes(u.mem_read(MEM, 0x500))
        assert call(length=4) == 0
        assert bytes(u.mem_read(MEM, 0x500)) == before
        assert bytes(u.mem_read(ROOT, 0x600)) == fixture
        passed.append('ordinary-forward-' + hex(code))
    for label, length, manager, state, event in [
        ('short', 4, ROOT + 0x98, MEM, EVENT),
        ('truncated', 24, ROOT + 0x98, MEM, EVENT),
        ('oversized', 32, ROOT + 0x98, MEM, EVENT),
        ('wrong-owner', 28, ROOT + 0xAC, MEM, EVENT),
        ('null-state', 28, ROOT + 0x98, 0, EVENT),
        ('null-event', 28, ROOT + 0x98, MEM, 0),
        ('unaligned-event', 28, ROOT + 0x98, MEM, EVENT + 1),
    ]:
        setup()
        before = bytes(u.mem_read(MEM, 0x500))
        assert call(length, manager, state, event) == 0xFFFFFFEA
        assert bytes(u.mem_read(MEM, 0x500)) == before
        passed.append(label)
    for label, value, offset, expected in [('cookie', 0, EVENT + 16, -22),
            ('native-layout', 0, ROOT + 0x98, -95)]:
        setup()
        u.mem_write(offset, words(value))
        before = bytes(u.mem_read(MEM, 0x500))
        native_before = bytes(u.mem_read(ROOT, 0x600))
        assert call() == expected & 0xFFFFFFFF
        assert bytes(u.mem_read(MEM, 0x500)) == before
        assert bytes(u.mem_read(ROOT, 0x600)) == native_before
        passed.append(label)
    for label, generation, desired in [('stale-generation', 6, 1), ('stale-request', 7, 0)]:
        setup(generation=generation, desired=desired)
        before = bytes(u.mem_read(MEM, 48))
        assert call() == 1
        assert bytes(u.mem_read(MEM, 48)) == before
        passed.append(label)
    setup()
    first = call(expected=SEND)
    packet, length, route = first['args'][:3]
    assert route == 0x90040193 and length == 16
    assert bytes(u.mem_read(packet, length)) == struct.pack('<BBHII4B', 5, 0, 0x403D, 0, 4, 1, 0, 0, 0)
    passed.append('new-event-native-cancel-boundary')
    setup()
    u.mem_write(ROOT + 0x108 + 0xC, words(1))
    before = bytes(u.mem_read(ROOT, 0x600))
    # A busy event must use the S1 ring through the actual defer entry,
    # not the other controller's otherwise-valid deferred queue.
    item = call(expected=DEFER)
    assert item['args'][:2] == [ROOT + 0x398, EVENT]
    assert bytes(u.mem_read(ROOT, 0x600)) == before
    passed.append('busy-native-defer-boundary')
    setup(phase=2)
    u.mem_write(MEM + 12, words(4))
    u.mem_write(MEM + 40, words(1))
    assert call() == 2
    assert bytes(u.mem_read(MEM, 16)) == words(0, 1, 500, 5)
    passed.append('owner-job-action-preserved-for-runtime-dispatch')
    report = dict(schema='OFFLINE_TARGET_TASK_ADAPTER/1', camera_io=False,
        passed=passed, boundary_calls=boundaries,
        limits=['Manager interception is not installed', 'All OS send/defer calls stop before execution',
                'No sensor operation, ACK, frame retention or physical pre-capture is simulated'])
    (args.output / 'task-adapter.private.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f'{len(passed)} task-adapter checks passed; native operations stop before execution. No camera I/O.')


if __name__ == '__main__':
    main()
