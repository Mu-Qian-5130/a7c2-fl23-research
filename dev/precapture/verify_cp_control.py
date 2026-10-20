"""Compare independent CP control state with bounded original instructions.

All inputs are synthetic. Original origin, busy and getter leaf functions
execute; scheduler, cancellation, release and reply delivery never execute.
No camera access, modified firmware output, or successful OS stubs exist.
"""
import argparse
import hashlib
import itertools
import json
import struct
import subprocess
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import (
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
    UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6,
    UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC,
)
from unicorn.arm64_const import (
    UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3,
    UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC,
)
from support.reference import SPECS
from support.elf import image_loader, codegen_flags
from support.memory import MEM, STACK, STOP

MASTER = 0x1502EC8
PENDING = 0x1743180
DEBUG = 0x19386AC
PACKET = MEM + 0x100
CONTEXT = MEM + 0x200


def words(*values):
    return struct.pack('<' + 'I' * len(values), *values)


class Native:
    def __init__(self, donor, target):
        self.u = u = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        # Code executes at file coordinates: relative BLs remain valid.
        # Absolute native data addresses are mapped separately below.
        pages = set()
        for at, length in [(0x277418, 0xD8), (0xB7AEE0, 8),
                           (0xAAE7EC, 10), (0x843B5A, 10),
                           (0x3F6EEC, 0x72), (0x843AC2, 0x46)]:
            for page in range(at & ~4095, (at + length + 4095) & ~4095, 4096):
                if page not in pages:
                    u.mem_map(page, 4096)
                    u.mem_write(page, donor[page:page + 4096])
                    pages.add(page)
        # Replay target leaves independently at their own file addresses.
        for at, length in [(0xAE402A, 6), (0xA1A030, 10)]:
            page = at & ~4095
            u.mem_map(page, 4096)
            u.mem_write(page, target[page:page + 4096])
        for at, size in [(MASTER & ~4095, 8192), (PENDING & ~4095, 4096),
                         (DEBUG & ~4095, 4096), (MEM, 4096),
                         (STACK, 0x4000), (STOP, 4096)]:
            u.mem_map(at, size)
        self.boundary = None

        def stop_before_external(cpu, address, size, user):
            if address in {0xAAD30E, 0xAAC5EE, 0xAAF58A, 0x8432C4}:
                self.boundary = address
                cpu.emu_stop()

        # Hook all mapped code, and also map external entry pages so the
        # code hook can stop BEFORE fetching/executing their instructions.
        for at in [0xAAD30E, 0xAAC5EE, 0xAAF58A, 0x8432C4]:
            page = at & ~4095
            if page not in pages:
                u.mem_map(page, 4096)
                pages.add(page)
        u.hook_add(UC_HOOK_CODE, stop_before_external)

    def run(self, start, end=STOP, boundary=None):
        self.boundary = None
        self.u.reg_write(UC_ARM_REG_SP, STACK + 0x3000)
        self.u.reg_write(UC_ARM_REG_LR, STOP | 1)
        self.u.emu_start(start | 1, end, count=200)
        if boundary is not None:
            assert self.boundary == boundary, 'Native external boundary not reached'
        else:
            assert self.u.reg_read(UC_ARM_REG_PC) == end, 'Native slice did not finish'

    def setting(self, packet):
        self.u.mem_write(PACKET, packet)
        self.u.reg_write(UC_ARM_REG_R0, PACKET)
        self.run(0x277418, 0x277438)  # stop before optional trace
        return bytes(self.u.mem_read(MASTER + 0x13C, 8))

    def pending(self, packet, origin):
        u = self.u
        u.mem_write(PACKET - 12, words(origin))
        u.mem_write(PACKET, packet)
        u.mem_write(PENDING, bytes([0xA5]) * 16)
        u.reg_write(UC_ARM_REG_R4, PACKET)
        self.run(0x2774B4, boundary=0xAAD30E)
        value = bytes(u.mem_read(PENDING, 16))
        return (value[0], struct.unpack_from('<H', value, 4)[0],
                *struct.unpack_from('<II', value, 8)), u.reg_read(UC_ARM_REG_R0)

    def leaf(self, start, pointer):
        self.u.reg_write(UC_ARM_REG_R0, pointer)
        self.run(start)
        return self.u.reg_read(UC_ARM_REG_R0)

    def apply(self, enabled, busy):
        u = self.u
        controller, event = MEM + 0x300, MEM + 0x400
        u.mem_write(MASTER + 0x138, words(0xA5A5A5A5))
        u.mem_write(DEBUG + 0xF0, b'\0')
        u.mem_write(CONTEXT + 12, words(busy))
        u.mem_write(controller + 12, words(CONTEXT))
        u.mem_write(controller + 0x14, words(0x12345678))
        u.mem_write(event + 12, words(enabled))
        u.reg_write(UC_ARM_REG_R4, event)
        u.reg_write(UC_ARM_REG_R5, controller)
        self.run(0x3F6EEC, boundary=0xAAC5EE if busy else 0xAAF58A)
        return struct.unpack('<I', u.mem_read(MASTER + 0x138, 4))[0]

    def reply_boundary(self):
        self.u.mem_write(STACK + 0x2FC0, bytes(64))
        self.run(0x843AC2, boundary=0x8432C4)
        pointer, length, route = [self.u.reg_read(r) for r in
                                 [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2]]
        assert length == 12
        return bytes(self.u.mem_read(pointer, length)), route


def call(u, symbol, arch, values):
    if arch == 'thumb':
        regs = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3]
        sp, lr, pc = UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
    else:
        regs = [UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3]
        sp, lr, pc = UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC
    for reg, value in zip(regs, values):
        u.reg_write(reg, value)
    u.reg_write(sp, STACK + 0x3000)
    u.reg_write(lr, STOP | (arch == 'thumb'))
    u.emu_start(symbol, STOP, count=1000)
    assert u.reg_read(pc) == STOP
    return u.reg_read(regs[0]) & 0xFFFFFFFF


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware-root', type=Path, required=True)
    parser.add_argument('--zig', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    blobs = {}
    for model, spec in SPECS.items():
        data = (args.firmware_root / model / 'components/cpapp-b.bin').read_bytes()
        if hashlib.sha256(data).hexdigest() != spec['sha256']:
            raise ValueError('Unsupported original CP fingerprint')
        blobs[model] = data
    native = Native(blobs['a1ii-4.00'], blobs['a7c2-2.01'])
    args.output.mkdir(parents=True, exist_ok=False)
    symbols_wanted = ('precapture_cp_setting', 'precapture_cp_begin', 'precapture_cp_apply_if_idle')
    counts = {'setting': 0, 'pending_and_commit': 0, 'invalid_or_stage_guard': 0, 'native_reply_boundary': 0}
    for arch, triple in [('thumb', 'thumb-linux-gnueabi'), ('aarch64', 'aarch64-linux-gnu')]:
        dest = args.output / (arch + '-cp-control.elf')
        command = [str(args.zig), 'cc', '-target', triple, '-O2', '-shared', '-fPIC',
                   '-ffreestanding', '-fno-builtin', '-fno-stack-protector',
                   '-fno-unwind-tables', '-fno-asynchronous-unwind-tables',
                   '-nostdlib', '-Wl,--no-undefined,-Bsymbolic', '-o', str(dest),
                   str(Path(__file__).with_name('cp_control_state.c'))]
        command[4:4] = codegen_flags(arch)
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stderr[-2000:])
        u, symbols = image_loader(dest, arch, symbols_wanted)

        def execute(name, packet=b'', stage=0, busy=0, origin=0x90030001, length=None):
            initial = words(0xA5A5A5A5, 0, 0, stage, 0, 0, 0, 0) + b'\xA5' * 32
            u.mem_write(MEM, initial)
            u.mem_write(PACKET, packet)
            u.mem_write(CONTEXT, words(0, 0, 0, busy) + b'\xA5' * 16)
            values = [MEM, CONTEXT] if name.endswith('idle') else [MEM, PACKET, len(packet) if length is None else length, origin]
            status = call(u, symbols[name], arch, values)
            state = bytes(u.mem_read(MEM, 64))
            assert state[32:] == initial[32:]
            assert bytes(u.mem_read(PACKET, len(packet))) == packet
            assert bytes(u.mem_read(CONTEXT, 32)) == words(0, 0, 0, busy) + b'\xA5' * 16
            return status, state, initial

        for trigger, duration in [(0, 0), *itertools.product(range(1, 4), [5, 10, 500, 1000])]:
            packet = struct.pack('<BBHIII', 5, 0, 0x4172, 0x12345678, trigger, duration)
            status, state, initial = execute(symbols_wanted[0], packet)
            assert status == 1 and state[4:12] == native.setting(packet)
            assert state[:4] == initial[:4] and state[12:] == initial[12:]
            counts['setting'] += 1
        for enabled, context, origin in itertools.product([0, 1], [0, 0xFEDCBA98], [0x90030001, 0x81234567]):
            packet = struct.pack('<BBHII', 5, 0, 0x4173, context, enabled)
            pending, desired = native.pending(packet, origin)
            status, state, initial = execute(symbols_wanted[1], packet, origin=origin)
            fields = struct.unpack('<8I', state[:32])
            assert status == 1 and fields[0] == 0xA5A5A5A5
            assert fields[3:] == (1, desired, pending[1], pending[2], pending[3])
            assert pending[0] == 1
            native.u.mem_write(PACKET - 12, words(origin))
            assert native.leaf(0xAE402A, PACKET) == origin
            reply, reply_origin = native.reply_boundary()
            assert reply == struct.pack('<BBHII', 1, 0, 0x4173, context, 0xF000)
            assert reply_origin == origin
            counts['native_reply_boundary'] += 1
            for busy in [0, 1, 2, 0xFFFFFFFF]:
                # Explicit independent input AFTER the owner's matched ACK.
                # These leaf tests do not deliver that ACK or a native job.
                u.mem_write(MEM + 12, words(6))
                u.mem_write(CONTEXT + 12, words(busy))
                before = bytes(u.mem_read(MEM, 64))
                result = call(u, symbols[symbols_wanted[2]], arch, [MEM, CONTEXT])
                native_enabled = native.apply(enabled, busy)
                actual = bytes(u.mem_read(MEM, 64))
                if busy:
                    assert result == 0xFFFFFFF0 and actual == before
                else:
                    expected = bytearray(before)
                    expected[:4] = words(native_enabled)
                    expected[12:16] = words(2)
                    assert result == 1 and actual == bytes(expected)
                native.u.mem_write(CONTEXT + 12, words(busy))
                assert native.leaf(0xA1A030, CONTEXT) == int(busy != 0)
                counts['pending_and_commit'] += 1
                u.mem_write(MEM, state)  # independent synthetic input for next busy case
        good_setting = struct.pack('<BBHIII', 5, 0, 0x4172, 0, 1, 500)
        good_begin = struct.pack('<BBHII', 5, 0, 0x4173, 0, 1)
        invalid = [(symbols_wanted[0], b'', 0), (symbols_wanted[1], b'', 0),
                   (symbols_wanted[0], good_setting[:-1], 0),
                   (symbols_wanted[1], good_begin[:-1], 0),
                   (symbols_wanted[0], b'\x04' + good_setting[1:], 0),
                   (symbols_wanted[1], good_begin[:2] + b'\x72' + good_begin[3:], 0),
                   (symbols_wanted[0], good_setting[:8] + words(4, 500), 0),
                   (symbols_wanted[0], good_setting[:8] + words(1, 1001), 0),
                   (symbols_wanted[0], good_setting[:8] + words(1, 4), 0),
                   (symbols_wanted[0], good_setting[:8] + words(0, 5), 0),
                   (symbols_wanted[1], good_begin[:8] + words(2), 0),
                   *[(symbols_wanted[1], good_begin, stage) for stage in [1, 2, 3, 4, 5, 6]],
                   *[(symbols_wanted[2], b'', stage) for stage in [0, 1, 2, 3, 4, 5]]]
        for name, packet, stage in invalid:
            status, state, initial = execute(name, packet, stage)
            assert status in {0xFFFFFFEA, 0xFFFFFFF0} and state == initial
            counts['invalid_or_stage_guard'] += 1
    report = {'mode': 'OFFLINE_CP_STATE_BOUNDARIES_ONLY', 'camera_io': False,
              'firmware_modified': False, 'checks': counts,
              'source_sha256': hashlib.sha256(Path(__file__).with_name('cp_control_state.c').read_bytes()).hexdigest(),
              'external_operations_executed': False,
              'limits': ['Caller-owned state is not allocated or bound on camera',
                         'Real owner serialization and deferred events remain unbound',
                         'Native busy branch stops before requeue; idle before release',
                         'Native reply builder stops before send; no successful reply delivered',
                         'No stage2-to-idle transition or camera runtime hook exists']}
    (args.output / 'cp-control.private.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
