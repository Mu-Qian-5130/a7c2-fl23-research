"""Exercise CP backend through actual native boundaries, never fake success.

Original deferred-ring code executes. Checked send/post/reply helpers stop
BEFORE their allocators or OS delivery. Those boundaries are not ACKs or
physical pre-capture. No USB operations or installer output are available.
"""
import argparse
import hashlib
import json
import struct
import subprocess
from pathlib import Path

from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from audit_control import SPECS
from verify_offline import image_loader, codegen_flags, MEM, STACK, STOP

OPS, VIEW, MASTER, CONTEXT, CONTROLLER, RING, EVENT, WIRE = [MEM + v for v in [0x100, 0x140, 0x200, 0xA00, 0xA40, 0xB00, 0xE00, 0xE80]]
BASE = 0x108000
SEND, POST, DEFER, REPLY = [BASE + v for v in [0x3ABC48, 0x3ADFE4, 0xA17EAE, 0x7D2A14]]


def words(*v):
    return struct.pack('<' + 'I' * len(v), *v)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--firmware-root', type=Path, required=True)
    p.add_argument('--zig', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--lto', action='store_true', help='Compare integer-only LTO size; still not installable')
    a = p.parse_args()
    cp = (a.firmware_root / 'a7c2-2.01/components/cpapp-b.bin').read_bytes()
    if hashlib.sha256(cp).hexdigest() != SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported target CP')
    a.output.mkdir(parents=True, exist_ok=False)
    sources = [Path(__file__).with_name(name) for name in ['cp_backend.c', 'cp_control_state.c', 's1_trigger.c', 'capture_gate.c']]
    dest = a.output / 'thumb-cp-backend.elf'
    cmd = [str(a.zig), 'cc', '-target', 'thumb-linux-gnueabi', *codegen_flags('thumb'),
           '-Oz', '-g', '-shared', '-fPIC', '-ffreestanding', '-fno-builtin', '-fno-stack-protector',
           '-fno-unwind-tables', '-fno-asynchronous-unwind-tables', '-nostdlib',
           '-Wl,--no-undefined,-Bsymbolic', '-o', str(dest), *map(str, sources)]
    if a.lto:
        roots = ['precapture_backend_begin', 'precapture_backend_event', 'precapture_backend_buttons',
                 'precapture_native_request', 'precapture_cp_setting', 'precapture_frame_gate']
        cmd[4:4] = ['-flto', '-fvisibility=hidden', '-ffunction-sections', '-fdata-sections',
                    '-Wl,--gc-sections,' + ','.join('-u,' + name for name in roots)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr[-3000:])
    wanted = ('precapture_backend_begin', 'precapture_backend_event', 'precapture_native_request', 'precapture_backend_buttons')
    u, symbols = image_loader(dest, 'thumb', wanted)
    # Original code at real linked addresses, with correct Thumb pointers.
    pages = set()
    for address in [SEND, POST, DEFER, REPLY]:
        page = address & ~4095
        if page not in pages:
            u.mem_map(page, 4096)
            u.mem_write(page, cp[page - BASE:page - BASE + 4096])
            pages.add(page)
    boundaries = []

    def stop(cpu, address, size, user):
        if address not in [SEND, POST, REPLY]:
            return
        regs = [cpu.reg_read(r) for r in [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3]]
        pointer, length, route = (regs[2], regs[3], regs[1]) if address == POST else regs[:3]
        assert length in [12, 16, 32]
        boundaries.append({'native_entry_va': hex(address), 'packet_hex': bytes(cpu.mem_read(pointer, length)).hex(),
                           'route': hex(route), 'native_send_executed': False,
                           'state_words': list(struct.unpack('<12I', cpu.mem_read(MEM, 48)))})
        cpu.emu_stop()

    u.hook_add(UC_HOOK_CODE, stop)

    def setup(enabled=0, desired=1, phase=1, busy=0, requested=0, cancel=0, generation=7):
        u.mem_write(MEM, words(enabled, 1, 500, phase, desired, 0x4173, 0x12345678, 0x90030001,
                              requested, generation, cancel, 0) + b'\xA5' * 16)
        u.mem_write(OPS, words(SEND | 1, POST | 1, DEFER | 1, REPLY | 1))
        u.mem_write(VIEW, words(MASTER, CONTEXT, CONTROLLER, RING, MEM + 0xF00))
        u.mem_write(MASTER, bytes(0x800))
        u.mem_write(MASTER + 0x138, words(1))
        u.mem_write(MASTER + 0x700, words(1))
        u.mem_write(CONTEXT, words(0, 0, 0, busy))
        u.mem_write(CONTROLLER, bytes(0x40))
        u.mem_write(CONTROLLER + 0x24, words(2))
        u.mem_write(RING, bytes(0x23C))
        u.mem_write(EVENT, words(0x8240, generation, 1, desired, 0x50435231, 0, 0))

    def call(name, values, boundary=None):
        before = len(boundaries)
        for register, value in zip([UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3], values):
            u.reg_write(register, value)
        u.reg_write(UC_ARM_REG_SP, STACK + 0x3000)
        u.reg_write(UC_ARM_REG_LR, STOP | 1)
        u.emu_start(symbols[name], STOP, count=2000)
        assert bytes(u.mem_read(MEM + 48, 16)) == b'\xA5' * 16
        if boundary is None:
            assert u.reg_read(UC_ARM_REG_PC) == STOP and len(boundaries) == before
            return u.reg_read(UC_ARM_REG_R0) & 0xFFFFFFFF
        assert u.reg_read(UC_ARM_REG_PC) == boundary and len(boundaries) == before + 1
        return boundaries[-1]

    # Real checked command-send boundaries, not calls returning fake success.
    for command, value in [(0x4038, 0), (0x4039, 0), (0x403D, 1), (0x403D, 0)]:
        setup()
        item = call('precapture_native_request', [OPS, command, value], SEND)
        packet = bytearray(struct.pack('<BBHI8x', 5, 0, command, 0))
        if command == 0x403D:
            struct.pack_into('<I', packet, 8, 4);packet[12] = value
        else:
            packet[8] = 13
        assert bytes.fromhex(item['packet_hex']) == bytes(packet)
        assert item['route'] == '0x90040193'
    # Native packets' meaningful field stores are pinned to the originals.
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    for at, mnemonic, operands in [(0x9DAC3E, 'movs', 'r2, #0xd'), (0x9DAC4E, 'str', 'r1, [r0, #0xc]'),
                                    (0x9DACA2, 'movs', 'r1, #0xd'), (0x9DA60E, 'strd', 'r1, r4, [r0, #4]'),
                                    (0x9DA614, 'strb', 'r1, [r0, #0xc]'), (0x9DA66A, 'strb', 'r1, [r0, #0xc]')]:
        ins = next(md.disasm(cp[at:at + 4], at))
        assert (ins.mnemonic, ins.op_str) == (mnemonic, operands)
    setup(phase=0, generation=7)
    u.mem_write(WIRE, struct.pack('<BBHII', 5, 0, 0x4173, 0x87654321, 1))
    # Fifth argument (origin) is the native incoming-message accessor result.
    u.mem_write(STACK + 0x3000, words(0x90030001))
    # begin has six arguments: state, ops, owner, wire, length, origin.
    u.mem_write(STACK + 0x3000, words(12, 0x90030001))
    item = call('precapture_backend_begin', [MEM, OPS, MEM + 0xF00, WIRE], POST)
    assert bytes.fromhex(item['packet_hex']) == words(0, 0x8240, 8, 1, 1, 0x50435231, 0, 0)
    assert item['state_words'][0] == 0 and item['state_words'][3] == 1
    setup()
    item = call('precapture_backend_event', [MEM, OPS, VIEW, EVENT], SEND)
    assert bytes.fromhex(item['packet_hex']) == struct.pack('<BBHII4B', 5, 0, 0x403D, 0, 4, 1, 0, 0, 0)
    assert item['state_words'][0] == 0 and item['state_words'][10] == 0
    setup(phase=6, cancel=1, requested=1)
    u.mem_write(EVENT + 8, words(4))
    item = call('precapture_backend_event', [MEM, OPS, VIEW, EVENT], SEND)
    assert bytes.fromhex(item['packet_hex']) == struct.pack('<BBHII4B', 5, 0, 0x403D, 0, 4, 0, 0, 0, 0)
    assert item['state_words'][0] == 1 and item['state_words'][3] == 2
    protocol_cases = 0
    # No phase2 path can commit/release: it requests a frozen owner job.
    setup(phase=4, cancel=1)
    u.mem_write(EVENT + 8, words(2))
    assert call('precapture_backend_event', [MEM, OPS, VIEW, EVENT]) == 2
    assert bytes(u.mem_read(MEM, 16)) == words(0, 1, 500, 5)
    assert bytes(u.mem_read(MEM + 40, 8)) == words(1, 0)
    protocol_cases += 1
    # ACK completion is generation/duration/desired/stage matched. Only then
    # post phase4; state.enabled and cancellation do not change at this post.
    setup(phase=5, cancel=1)
    u.mem_write(EVENT + 8, words(3, 1, 0x50435231, 0, 500))
    item = call('precapture_backend_event', [MEM, OPS, VIEW, EVENT], POST)
    assert bytes.fromhex(item['packet_hex']) == words(0, 0x8240, 7, 4, 1, 0x50435231, 0, 0)
    assert item['state_words'][0] == 0 and item['state_words'][3] == 6 and item['state_words'][10] == 1
    protocol_cases += 1
    for offset, value in [(4, 6), (12, 0), (24, 499)]:
        setup(phase=5, cancel=1)
        u.mem_write(EVENT + 8, words(3, 1, 0x50435231, 0, 500))
        u.mem_write(EVENT + offset, words(value))
        before = bytes(u.mem_read(MEM, 48))
        assert call('precapture_backend_event', [MEM, OPS, VIEW, EVENT]) == 1
        assert bytes(u.mem_read(MEM, 48)) == before
        protocol_cases += 1
    for stage, phase in [(0, 3), (1, 3), (4, 3), (6, 3), (5, 1), (5, 2), (5, 4)]:
        setup(phase=stage, cancel=1)
        u.mem_write(EVENT + 8, words(phase, 1, 0x50435231, 0, 500))
        before = bytes(u.mem_read(MEM, 48))
        assert call('precapture_backend_event', [MEM, OPS, VIEW, EVENT]) == 1
        assert bytes(u.mem_read(MEM, 48)) == before
        protocol_cases += 1
    for status in [-16, -22, -116, -5]:
        setup(phase=5, cancel=1, busy=1)
        u.mem_write(EVENT + 8, words(3, 1, 0x50435231, status & 0xffffffff, 500))
        before = bytearray(u.mem_read(MEM, 48))
        assert call('precapture_backend_event', [MEM, OPS, VIEW, EVENT]) == 0xfffffffb
        struct.pack_into('<I', before, 12, 3)
        struct.pack_into('<I', before, 44, 1)
        assert bytes(u.mem_read(MEM, 48)) == bytes(before)
        protocol_cases += 1
    generation_cases = 0
    for generation, enabled, rejected in [(0xfffffffe, 1, True),
            (0xffffffff, 0, True), (0xffffffff, 1, True), (0xfffffffe, 0, False)]:
        setup(phase=0, generation=generation)
        u.mem_write(WIRE, struct.pack('<BBHII', 5, 0, 0x4173, 0x87654321, enabled))
        u.mem_write(STACK + 0x3000, words(12, 0x90030001))
        before = bytes(u.mem_read(MEM, 48))
        if rejected:
            assert call('precapture_backend_begin', [MEM, OPS, MEM + 0xf00, WIRE]) == (-75 & 0xffffffff)
            assert bytes(u.mem_read(MEM, 48)) == before
        else:
            item = call('precapture_backend_begin', [MEM, OPS, MEM + 0xf00, WIRE], POST)
            assert bytes.fromhex(item['packet_hex']) == words(0, 0x8240, 0xffffffff, 1, 0, 0x50435231, 0, 0)
        generation_cases += 1
    reconcile_cases = 0
    for desired, requested, pressed, command in [(1, 1, 0, 0x4039),
            (1, 0, 1, 0x4038), (0, 1, 1, 0x4039)]:
        setup(phase=6, cancel=1, requested=requested, desired=desired)
        u.mem_write(EVENT + 8, words(4))
        u.mem_write(CONTROLLER + 0x24, words(2 if pressed else 0))
        before = bytes(u.mem_read(MEM, 48))
        item = call('precapture_backend_event', [MEM, OPS, VIEW, EVENT], SEND)
        assert struct.unpack_from('<H', bytes.fromhex(item['packet_hex']), 2)[0] == command
        # Not a release command; no commit or requested update before send.
        assert bytes(u.mem_read(MEM, 48)) == before
        reconcile_cases += 1
    fault_cases = 0
    for requested, desired in [(0, 0), (0, 1), (1, 0), (1, 1)]:
        setup(cancel=1, requested=requested, desired=desired)
        u.mem_write(EVENT + 8, words(99))
        before = bytearray(u.mem_read(MEM, 48))
        assert call('precapture_backend_event', [MEM, OPS, VIEW, EVENT]) == 0xfffffffb
        struct.pack_into('<I', before, 12, 3)
        struct.pack_into('<I', before, 44, 1)
        assert bytes(u.mem_read(MEM, 48)) == bytes(before)
        fault_cases += 1
    # A busy event uses the actual native deferred ring and returns normally.
    deferred = 0
    for phase, requested in [(1, 0), (2, 0), (2, 1)]:
        setup(phase=1 if phase == 1 else 4, busy=1, requested=requested)
        u.mem_write(EVENT + 8, words(phase))
        before = bytes(u.mem_read(MEM, 48))
        expected = bytes(u.mem_read(EVENT, 28))
        assert call('precapture_backend_event', [MEM, OPS, VIEW, EVENT]) == 1
        assert bytes(u.mem_read(MEM, 48)) == before
        assert bytes(u.mem_read(RING + 4, 28)) == expected
        assert bytes(u.mem_read(RING + 0x234, 8)) == words(0, 1)
        deferred += 1
    for pressed, requested, command in [(1, 0, 0x4038), (0, 1, 0x4039)]:
        setup(enabled=1, phase=0, requested=requested)
        u.mem_write(CONTROLLER + 0x24, words(2 if pressed else 0))
        item = call('precapture_backend_buttons', [MEM, OPS, VIEW], SEND)
        assert struct.unpack_from('<H', bytes.fromhex(item['packet_hex']), 2)[0] == command
        assert item['state_words'][8] == requested  # not updated before real send returns
    # Stale or unrelated messages have no outbound operation or state write.
    for offset, value in [(0, 0x8206), (4, 6), (12, 0), (16, 0)]:
        setup()
        u.mem_write(EVENT + offset, words(value))
        before = bytes(u.mem_read(MEM, 48))
        assert call('precapture_backend_event', [MEM, OPS, VIEW, EVENT]) in [0, 1]
        assert bytes(u.mem_read(MEM, 48)) == before
    from elftools.elf.elffile import ELFFile
    with dest.open('rb') as stream:
        elf = ELFFile(stream)
        layout = {s.name: s['sh_size'] for s in elf.iter_sections() if s['sh_flags'] & 2}
    report = {'mode': 'OFFLINE_CP_BACKEND_BOUNDARIES', 'camera_io': False, 'firmware_modified': False,
              'LTO': a.lto, 'ELF_allocated_sections': layout,
              'boundaries': boundaries, 'actual_native_deferred_events': deferred,
              'pending_button_reconciliation_boundaries': reconcile_cases,
              'matched_owner_protocol_cases': protocol_cases,
              'nonwrapping_generation_and_final_restore_cases': generation_cases,
              'faults_retain_cancellation_without_send_or_ACK': fault_cases,
              'successful_OS_or_sensor_stubs': False,
              'limits': ['Native send/post/reply are stopped before execution',
                         'No end-to-end ACK or physical pre-shutter image exists in these tests',
                         'S1 interception, exclusive state ownership, queue policy hook and placement remain unbound',
                         'Proposed event0x8240 must not be sent to an unmodified camera']}
    (a.output / 'cp-backend.private.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f'Native request/post/release boundaries: {len(boundaries)}; actual native deferred rings: {deferred}; no fake successful sends.')


if __name__ == '__main__':
    main()
