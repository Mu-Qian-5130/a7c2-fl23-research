"""Replay a pinned existing log-read selector; never connect to a camera.

Checks AdjustControl0x601/0x23 selector0 through original dispatch, path
selection and read-mode fopen boundary. Never executes fopen or supplies
an OS return value. A log route is not evidence that a crash was preserved.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1,
    UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X4,
    UC_ARM64_REG_X19, UC_ARM64_REG_X20, UC_ARM64_REG_X21,
    UC_ARM64_REG_SP, UC_ARM64_REG_PC)

SHA = '3362d4b6e03dc517b04f1eb04d4199ff16d33f6e8f1bfddce657a375778d79e7'
MEM, STACK = 0x30000000, 0x40000000


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--libsencore', type=Path, required=True)
    p.add_argument('--kernel', type=Path, help='Optional pinned original kernel for finite log-reader boundary checks')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    raw = a.libsencore.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SHA:
        raise ValueError('Unsupported source library')
    u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    for at, size in [(0xA000, 0xA000), (0x37000, 4096),
                     (0x57000, 4096), (0x6D000, 4096)]:
        u.mem_map(at, size)
        u.mem_write(at, raw[at:at + size])
    u.mem_map(MEM, 4096)
    u.mem_map(STACK, 0x4000)
    stops, visits = set(), []

    def stop(cpu, at, size, user):
        if at in stops:
            visits.append(at)
            cpu.emu_stop()

    u.hook_add(UC_HOOK_CODE, stop)

    def run(start, boundary):
        nonlocal stops
        stops = {boundary}
        old = len(visits)
        u.emu_start(start, 0xFFFFFFFF, count=300)
        assert len(visits) == old + 1 and u.reg_read(UC_ARM64_REG_PC) == boundary

    # Enter the category/command decision after the existing diagnostic
    # print. This is an explicit internal packet input, not a fake return.
    u.mem_write(MEM, bytes([1]) + bytes(0xFF))
    u.reg_write(UC_ARM64_REG_X19, MEM)
    u.reg_write(UC_ARM64_REG_X2, 0x601)
    u.reg_write(UC_ARM64_REG_X3, 0x23)
    run(0x12DD4, 0x11B50)
    assert u.reg_read(UC_ARM64_REG_X0) == MEM
    u.reg_write(UC_ARM64_REG_SP, STACK + 0x3000)
    run(0x11B50, 0x108CC)
    parent = u.reg_read(UC_ARM64_REG_X21)
    path = u.reg_read(UC_ARM64_REG_X20)
    assert bytes(u.mem_read(parent, 6)) == b'/proc\0'
    assert bytes(u.mem_read(path, 11)) == b'/proc/klog\0'
    # Separate post-diagnostic slice. No logging/allocator return is invented.
    run(0x11D2C, 0x10A98)
    assert [u.reg_read(r) for r in [UC_ARM64_REG_X0, UC_ARM64_REG_X1,
            UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X4]] == [8, parent, path, 0, 0]
    run(0x10A98, 0xAAB0)
    assert u.reg_read(UC_ARM64_REG_X0) == path
    mode = u.reg_read(UC_ARM64_REG_X1)
    mode_bytes = bytes(u.mem_read(mode, 5))
    assert mode_bytes == b'r' + b'\xff' * 4
    # Confirm the PLT symbol rather than naming a generic call fopen.
    from elftools.elf.elffile import ELFFile
    with a.libsencore.open('rb') as f:
        elf = ELFFile(f)
        rel = elf.get_section_by_name('.rela.plt')
        dyn = elf.get_section(rel['sh_link'])
        # AArch64 PLT: ldr x17,[x16,#imm*8]; page comes from adrp x16.
        page_instruction = struct.unpack_from('<I', raw, 0xAAB0)[0]
        imm = (((page_instruction >> 5) & 0x7FFFF) << 2) | ((page_instruction >> 29) & 3)
        if imm & (1 << 20):
            imm -= 1 << 21
        page = (0xAAB0 & ~4095) + (imm << 12)
        # The ldr is the second PLT instruction (0xaab4).
        load = struct.unpack_from('<I', raw, 0xAAB4)[0]
        got_address = page + ((load >> 10) & 0xFFF) * 8
        names = [dyn.get_symbol(r['r_info_sym']).name for r in rel.iter_relocations()
                 if r['r_offset'] == got_address]
        assert names == ['fopen']
    kernel_checks = None
    if a.kernel:
        kernel = a.kernel.read_bytes()
        digest = hashlib.sha256(kernel).hexdigest()
        if digest != '620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2':
            raise ValueError('Unsupported original kernel')
        base = 0xFFFFFF8008080000
        # Original proc file operations: llseek/read exist, write is NULL.
        assert struct.unpack_from('<4Q', kernel, 0x61E068) == (0, base + 0x130F00, base + 0x130FE0, 0)
        assert struct.unpack_from('<4Q', kernel, 0x61E048) == tuple(base + v for v in [0xB8358, 0xB8390, 0xB8380, 0xB83C0])
        assert struct.unpack_from('<Q', kernel, 0x61E038)[0] == base + 0x61E158
        assert struct.unpack_from('<Q', kernel, 0x61E160)[0] == base + 0xB87C8
        k = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        for at, size in [(0xB8000, 4096), (0x68B000, 4096), (0x423000, 4096)]:
            k.mem_map(at, size)
            fragment = kernel[at:at + size]
            if fragment:
                k.mem_write(at, fragment)
        k.mem_map(MEM, 4096)
        k.mem_map(STACK, 0x4000)
        from unicorn.arm64_const import UC_ARM64_REG_X6, UC_ARM64_REG_X22, UC_ARM64_REG_X23, UC_ARM64_REG_X24
        seen = []

        def stop_kernel(cpu, at, size, user):
            if at in [0xB85C8, 0x423C80]:
                seen.append(at)
                cpu.emu_stop()

        k.hook_add(UC_HOOK_CODE, stop_kernel)
        cases = []
        # Enter after native lock and hardware ring-header reads. Capacity,
        # cursor and caller length are explicit synthetic inputs; do not
        # invent a successful lock/read callback or execute hardware access.
        for capacity, position, requested in [(64, 0, 16), (64, 60, 16),
                (64, 64, 16), (64, 65, 16), (4096, 0, 8192), (0, 0, 16)]:
            k.mem_write(MEM, struct.pack('<Q', position))
            for reg, value in [(UC_ARM64_REG_X6, capacity), (UC_ARM64_REG_X3, 0),
                    (UC_ARM64_REG_X21, MEM + 0x100), (UC_ARM64_REG_X23, MEM),
                    (UC_ARM64_REG_X24, requested), (UC_ARM64_REG_SP, STACK + 0x3000)]:
                k.reg_write(reg, value)
            previous = len(seen)
            k.emu_start(0xB882C, 0xFFFFFFFF, count=60)
            expected = 0xB85C8 if position < capacity else 0x423C80
            assert len(seen) == previous + 1 and seen[-1] == expected
            length = None
            if position < capacity:
                from unicorn.arm64_const import UC_ARM64_REG_X5
                length = k.reg_read(UC_ARM64_REG_X5)
                assert length == min(capacity - position, requested)
            else:
                assert k.reg_read(UC_ARM64_REG_X22) == 0
            cases.append({'capacity_input': capacity, 'cursor_input': position,
                'requested_bytes': requested, 'bounded_copy_bytes': length,
                'boundary': hex(expected), 'copy_or_unlock_executed': False})
        kernel_checks = {'sha256': digest, 'proc_write_callback': None,
            'native_read_callback_file': '0xb87c8', 'finite_capacity_cases': cases,
            'limits': ['Ring lock, actual hardware contents and copy callback are not executed',
                       'This does not prove actual log capacity or a preserved crash record']}
    report = {'mode': 'OFFLINE_EXISTING_LOG_READ_SELECTOR', 'camera_io': False,
        'library_sha256': SHA, 'category': '0x601', 'command': '0x23', 'selector': 0,
        'internal_packet_input_state': 1, 'parent': '/proc', 'path': '/proc/klog',
        'helper_operation': 8, 'native_mode_prefix_hex': mode_bytes.hex(),
        'fopen_executed': False,
        'boundaries': [hex(v) for v in visits],
        'kernel_checks': kernel_checks,
        'limits': ['No live log request is sent by this audit',
            'Packet transport and real log contents are not established here',
            'A log read may not contain the CP failure or survive a restart',
            'Native mode storage begins r followed by an adjacent initialized -1 word; no clean r-NUL string is assumed',
            'EOF termination and actual log length require live verification']}
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(report, f, indent=2)
        f.write('\n')
    print('Original log selector reaches /proc/klog and a native read-mode prefix; stopped before fopen. No camera connection.')


if __name__ == '__main__':
    main()
