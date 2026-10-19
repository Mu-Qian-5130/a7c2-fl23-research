"""Original AP no-reply route and UIPC retry slices; no IPC/camera access.

Stops before every ioctl/TLS/lock/service. Explicit post-call inputs classify
original control flow; no actual call is mocked successful. This is NOT a
bounded trigger, worker, kernel audit or authorization to send a command.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2,
    UC_ARM64_REG_X22, UC_ARM64_REG_X29, UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC)

AP_SHA = '690b5f17f21cba5c7cd937e6feb0f6967ea2793c0b4ca6fc1fffdcaa1ed0d761'
UIPC_SHA = '09ebf5980237fc473077dc844763dcb00cba423f431646e3be7c0ca49ea70ff3'
MEM, STACK, STOP = 0x30000000, 0x40000000, 0x20000000


def library(path):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != UIPC_SHA:
        raise ValueError('Unsupported original UIPC library')
    with path.open('rb') as f:
        elf = ELFFile(f)
        assert elf['e_machine'] == 'EM_AARCH64'
        symbols = {s.name: (s['st_value'], s['st_size'])
            for s in elf.get_section_by_name('.dynsym').iter_symbols()}
        assert symbols['osal_snd_msg'] == (0x5e60, 684)
        assert symbols['u_osal_snd_msg'] == (0x3a10, 136)
        plt = elf.get_section_by_name('.plt')['sh_addr'] + 32
        reloc = elf.get_section_by_name('.rela.plt')
        dyn = elf.get_section(reloc['sh_link'])
        entries = {dyn.get_symbol(r['r_info_sym']).name: plt+i*16
            for i, r in enumerate(reloc.iter_relocations())}
        assert entries['ioctl'] == 0x2530 and entries['__errno_location'] == 0x26b0
        assert entries['u_osal_snd_msg'] == 0x2310
        fd_reloc = []
        for section in elf.iter_sections():
            if section['sh_type'] != 'SHT_RELA':
                continue
            syms = elf.get_section(section['sh_link'])
            fd_reloc += [syms.get_symbol(r['r_info_sym']).name for r in section.iter_relocations()
                if r['r_offset'] == 0x19fc8]
        assert fd_reloc == ['uconf']
        u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        pages = set()
        for seg in elf.iter_segments():
            if seg['p_type'] != 'PT_LOAD' or not seg['p_memsz']:
                continue
            for page in range(seg['p_vaddr'] & ~4095,
                    (seg['p_vaddr']+seg['p_memsz']+4095) & ~4095, 4096):
                if page not in pages:
                    u.mem_map(page, 4096);pages.add(page)
            u.mem_write(seg['p_vaddr'], seg.data())
    for at, n in ((MEM, 4096), (STACK, 0x10000), (STOP, 4096)):
        u.mem_map(at, n)
    # The single data relocation consumed by this prefix is explicitly
    # synthetic. No actual loaded uconf, descriptor or device is inspected.
    u.mem_write(0x19fc8, struct.pack('<Q', MEM))
    u.mem_write(MEM, struct.pack('<I', 77))
    return u, entries


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ap', type=Path, required=True)
    p.add_argument('--uipc', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    ap = a.ap.read_bytes()
    if hashlib.sha256(ap).hexdigest() != AP_SHA:
        raise ValueError('Unsupported complete current AP')
    u, entries = library(a.uipc)
    boundaries = {STOP, entries['ioctl'], entries['__errno_location'], entries['u_osal_snd_msg']}
    seen = []
    def stop(cpu, at, n, _):
        if at in boundaries:
            seen.append(at);cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE, stop)
    def run(entry):
        seen.clear()
        u.emu_start(entry, 0xffffffffffffffff, count=500)
        assert len(seen) == 1 and u.reg_read(UC_ARM64_REG_PC) == seen[0]
        return seen[0]
    def setup():
        u.reg_write(UC_ARM64_REG_X0, 0x90030001)
        u.reg_write(UC_ARM64_REG_X1, MEM+128)
        u.reg_write(UC_ARM64_REG_SP, STACK+0x8000)
        u.reg_write(UC_ARM64_REG_LR, STOP)
    setup()
    assert run(0x5e60) == entries['u_osal_snd_msg']
    assert u.reg_read(UC_ARM64_REG_X0) == 0x90030001
    assert u.reg_read(UC_ARM64_REG_X1) == MEM+128
    routes = []
    for value in (0, -22, -1024, -1021, -1):
        setup()
        assert run(0x3a10) == entries['ioctl']
        req = u.reg_read(UC_ARM64_REG_X2)
        assert u.reg_read(UC_ARM64_REG_X0) == 77
        assert u.reg_read(UC_ARM64_REG_X1) & 0xffffffff == 0x80000004
        assert struct.unpack('<I4xQ', bytes(u.mem_read(req, 16))) == (0x90030001, MEM+128)
        # Independent post-ioctl slice. The operation above never ran.
        u.reg_write(UC_ARM64_REG_X0, value & ((1 << 64)-1))
        target = run(0x3a4c)
        assert target == (entries['ioctl'] if value == -1021 else
            entries['__errno_location'] if value == -1 else STOP)
        if target == STOP:
            assert u.reg_read(UC_ARM64_REG_X0) & 0xffffffff == value & 0xffffffff
            assert u.reg_read(UC_ARM64_REG_SP) == STACK+0x8000
        else:
            assert u.reg_read(UC_ARM64_REG_SP) == STACK+0x7fc0
        routes.append(dict(explicit_post_ioctl_input=value, boundary=hex(target), ioctl_executed=False))
    errno_routes = []
    for errno in (22, 1021):
        setup();assert run(0x3a10) == entries['ioctl']
        u.mem_write(MEM+64, struct.pack('<I', errno))
        u.reg_write(UC_ARM64_REG_X0, MEM+64)
        # Independent after-TLS-pointer slice, not a successful TLS call.
        target = run(0x3a8c)
        assert target == (entries['ioctl'] if errno == 1021 else STOP)
        errno_routes.append(dict(explicit_errno=errno, boundary=hex(target), TLS_executed=False))
    # Demonstrate repeated native retry edges, WITHOUT performing even one
    # ioctl. This is not a trace of real camera errors or timing.
    setup();assert run(0x3a10) == entries['ioctl']
    req = u.reg_read(UC_ARM64_REG_X2)
    saved = bytes(u.mem_read(STACK+0x7fc0, 64))
    for _ in range(32):
        u.reg_write(UC_ARM64_REG_X0, (-1021) & ((1 << 64)-1))
        assert run(0x3a4c) == entries['ioctl']
        assert u.reg_read(UC_ARM64_REG_SP) == STACK+0x7fc0
        assert u.reg_read(UC_ARM64_REG_X2) == req
        assert bytes(u.mem_read(STACK+0x7fc0, 64)) == saved
    # Existing native no-reply path skips its future-get branch. Its mutex
    # unlock and destructor are still NOT executed or assumed bounded.
    v = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    v.mem_map(0x3535000, 4096);v.mem_write(0x3535000, ap[0x3535000:0x3536000])
    v.mem_map(STACK, 4096)
    v.reg_write(UC_ARM64_REG_X22, 0)
    v.reg_write(UC_ARM64_REG_X29, STACK+0x800)
    v.emu_start(0x3535af8, 0x3535b2c, count=4)
    assert v.reg_read(UC_ARM64_REG_PC) == 0x3535b2c
    assert v.reg_read(UC_ARM64_REG_X0) == STACK+0x870
    report = dict(schema='OFFLINE_AP_DIAGNOSTIC_ROUTE_BOUNDARIES/1', camera_io=False,
        ap_sha256=AP_SHA, uipc_sha256=UIPC_SHA,
        route='0x90030001', native_route='osal_snd_msg -> u_osal_snd_msg -> ioctl',
        synthetic_uconf_fd=77, ioctl_command='0x80000004', post_ioctl_cases=routes,
        post_errno_cases=errno_routes, repeated_independent_retry_edges=32,
        retry_status=-1021, library_retry_has_no_counter_or_deadline=True,
        AP_no_reply_branch_skips_future_get=True,
        actual_ioctl_or_native_send_executed=False, kernel_wait_contract_audited=False,
        limits=['All descriptor, errno and return values are explicit synthetic slice inputs',
            'No real IPC, USB, loaded-library mutation, worker or firmware candidate',
            'No-reply skips a CP response wait but does not bound locks, allocation, ioctl or library retries',
            'Kernel ioctl may have additional waits; library control flow alone cannot prove a safe bounded trigger',
            'Do not directly invoke this sender from a temporary worker based on these results'])
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(report, f, indent=2);f.write('\n')
    print('Original AP/UIPC: no-reply skips future-get; 5+2 post-call cases /32 retry edges; no native ioctl/send executed. Bounded trigger NOT established.')


if __name__ == '__main__':
    main()
