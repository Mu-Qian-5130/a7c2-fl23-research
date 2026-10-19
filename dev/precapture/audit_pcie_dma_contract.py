"""Offline native PCI packet slices, not a live memory-reading utility.

Pins the private A7C II kernel module. Relocatable ELF addresses are section
offsets. External calls are identified by relocations and stopped BEFORE
execution. Entry slices after semaphore/address-translation boundaries take
explicit synthetic inputs, not invented successful kernel return values.
"""
import argparse
import hashlib
import io
import json
import struct
from pathlib import Path

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1,
    UC_ARM64_REG_X2, UC_ARM64_REG_X19, UC_ARM64_REG_X20, UC_ARM64_REG_X21,
    UC_ARM64_REG_X22, UC_ARM64_REG_X23, UC_ARM64_REG_X29,
    UC_ARM64_REG_SP, UC_ARM64_REG_PC)

SHA = '26f376a9025f0b56b5ede7ebabdbf5dd8a5235d6627abe2abfd1430e2af578bc'
CODE, MEM, STACK = 0x10000000, 0x30000000, 0x40000000


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pcie-if', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    raw = a.pcie_if.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SHA:
        raise ValueError('Unsupported exact original pcie-if module')
    elf = ELFFile(io.BytesIO(raw))
    assert elf['e_type'] == 'ET_REL' and elf['e_machine'] == 'EM_AARCH64'
    text = elf.get_section_by_name('.text').data()
    symbols = elf.get_section_by_name('.symtab')
    rel = {r['r_offset']: dict(type=r['r_info_type'],
        name=symbols.get_symbol(r['r_info_sym']).name, addend=r['r_addend'])
        for r in elf.get_section_by_name('.rela.text').iter_relocations()}
    for at, name in [(0x4254, 'pcieif_sem_lock'), (0x4270, 'pcieif_start_dma_multi'),
                     (0x4278, 'pcieif_wait_exec'), (0x4078, 'arch_va_to_phys'),
                     (0x4138, '__udif_cache_ctrl'), (0x416c, 'pcidma_transfer_async'),
                     (0x41cc, 'printk'), (0x4b84, 'pcieif_wait_exec_timeout')]:
        assert rel[at]['type'] == 283 and rel[at]['name'] == name
    defined_functions = {s.name: (s['st_value'], s['st_size']) for s in symbols.iter_symbols()
                         if s['st_info']['type'] == 'STT_FUNC' and s['st_shndx'] != 'SHN_UNDEF'}
    assert defined_functions['pcieif_dma_execute'] == (0x4228, 120)
    assert defined_functions['pcieif_start_dma_multi'] == (0x4050, 420)
    u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    u.mem_map(CODE, 0x10000)
    u.mem_write(CODE, text)
    u.mem_map(MEM, 0x10000)
    u.mem_map(STACK, 0x10000)
    stop_at, observed = set(), []
    def stop(cpu, address, size, user):
        if address in stop_at:
            observed.append(address)
            cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE, stop)
    def run(start, stops):
        nonlocal stop_at
        stop_at = {CODE + n for n in stops}
        observed.clear()
        u.emu_start(CODE + start, 0xffffffffffffffff, count=500)
        assert len(observed) == 1 and u.reg_read(UC_ARM64_REG_PC) == observed[0]
        return observed[0] - CODE
    packets = []
    for flag in (0, 1, 2):
        # Pure local portion AFTER original semaphore lock; no lock executes.
        # These inputs do not establish either endpoint's address-space type.
        first, second, length = 0x1122334455667788, 0x8877665544332211, 0x1234
        u.mem_write(STACK, bytes([0xa5]) * 0x10000)
        for reg, value in ((UC_ARM64_REG_X20, flag), (UC_ARM64_REG_X23, first),
                (UC_ARM64_REG_X22, second), (UC_ARM64_REG_X21, length),
                (UC_ARM64_REG_X29, STACK + 0x8000), (UC_ARM64_REG_SP, STACK + 0x8000)):
            u.reg_write(reg, value)
        assert run(0x4258, (0x4270,)) == 0x4270
        packet = bytes(u.mem_read(STACK + 0x8048, 24))
        endpoints = (first, second) if flag else (second, first)
        assert packet == struct.pack('<QQI', *endpoints, length) + bytes([0xa5]) * 4
        assert [u.reg_read(r) for r in (UC_ARM64_REG_X0, UC_ARM64_REG_X1,
                UC_ARM64_REG_X2)] == [STACK + 0x8048, 1, flag]
        packets.append(dict(flag=flag, packet_endpoints=[hex(v) for v in endpoints],
            bytes=length, stopped_before='pcieif_start_dma_multi',
            native_flag_supported=flag in (0, 1)))
    descriptors = []
    for count in (0, 1, 2, 3, 4):
        # Pure slice AFTER arch_va_to_phys. x22 is a synthetic physical input,
        # not a fake translation return. Stop before cache control/printk or
        # before the zero-count null store, rather than allowing that store.
        u.mem_write(MEM, bytes([0xa5]) * 0x10000)
        records = [(0x0123456700001000 + i * 4096,
                    0x89abcdef00002000 + i * 4096, 4096 + i) for i in range(3)]
        for i, record in enumerate(records):
            u.mem_write(MEM + 0x1000 + i * 24, struct.pack('<QQII', *record, 0))
        context, physical = MEM + 0x2000, 0x123400002000
        for reg, value in ((UC_ARM64_REG_X20, MEM + 0x1000),
                (UC_ARM64_REG_X21, context), (UC_ARM64_REG_X22, physical),
                (UC_ARM64_REG_X23, count), (UC_ARM64_REG_SP, STACK + 0x8000)):
            u.reg_write(reg, value)
        boundary = run(0x4080, (0x4138, 0x41cc, 0x4110) if not count else (0x4138, 0x41cc))
        if not count:
            assert boundary == 0x4110
            # Original x5=0: the next original STR would write address zero.
            from unicorn.arm64_const import UC_ARM64_REG_X5
            assert u.reg_read(UC_ARM64_REG_X5) == 0
            assert bytes(u.mem_read(context, 0x100)) == bytes([0xa5]) * 0x100
        elif count > 3:
            assert boundary == 0x41cc  # Before log/clamping; no fake log return.
        else:
            assert boundary == 0x4138
            expected = bytearray([0xa5]) * 0x60
            for i, (left, right, size) in enumerate(records[:count]):
                struct.pack_into('<6I', expected, i * 24, 9 if i == count - 1 else 1,
                    size, left & 0xffffffff, left >> 32, right & 0xffffffff, right >> 32)
            struct.pack_into('<6I', expected, count * 24, 6, 0,
                             physical & 0xffffffff, physical >> 32, 0, 0)
            assert bytes(u.mem_read(context + 0x40, 0x60)) == bytes(expected)
            assert [u.reg_read(r) for r in (UC_ARM64_REG_X0, UC_ARM64_REG_X1,
                    UC_ARM64_REG_X2)] == [context + 0x40, 0x60, 1]
        descriptors.append(dict(count=count, boundary_text_offset=hex(boundary),
            hardware_or_external_call_executed=False,
            zero_count_would_write_null=count == 0))
    # The ordinary wait actually enters the timeout helper with timeout ZERO.
    # Check its resulting wait budget BEFORE any lock or scheduler executes.
    u.reg_write(UC_ARM64_REG_X0, MEM)
    u.reg_write(UC_ARM64_REG_SP, STACK + 0x8000)
    assert run(0x4b78, (0x4b84,)) == 0x4b84
    assert u.reg_read(UC_ARM64_REG_X1) == 0
    waits = []
    for timeout in (0, 1, 10):
        u.reg_write(UC_ARM64_REG_X0, MEM)
        u.reg_write(UC_ARM64_REG_X1, timeout)
        u.reg_write(UC_ARM64_REG_SP, STACK + 0x8000)
        assert run(0x49d8, (0x4a10, 0x4ac0)) == (0x4a10 if not timeout else 0x4ac0)
        ticks = u.reg_read(UC_ARM64_REG_X20)
        assert ticks == (0x7fffffffffffffff if not timeout else timeout * 100)
        waits.append(dict(timeout_argument=timeout, native_wait_ticks=hex(ticks),
            stopped_before='spin_lock_irqsave', scheduler_executed=False))
    report = dict(schema='OFFLINE_NATIVE_PCIE_DMA_CONTRACT/1',
        module_sha256=SHA, camera_io=False, packets=packets, descriptors=descriptors, waits=waits,
        identified_wait_calls=[dict(text_offset=hex(at), **rel[at]) for at in
            (0x4254, 0x4278, 0x4078, 0x4138, 0x416c)],
        callable_user_endpoint_established=False,
        limits=['Relocatable ELF BL immediates are not resolved function addresses',
            'The count4 diagnostic pointers remain unresolved and are not dereferenced before stopping',
            'No semaphore, DMA, mapping, cache, callback or completion wait executes',
            'Endpoint order is verified; safe CP physical source translation is not',
            'The single-transfer wrapper reaches timeout helper with zero: effectively indefinite wait',
            'Zero descriptor count reaches an original null destination store; do not call it',
            'No safe arbitrary CP memory-read API or live operation is supplied'])
    with a.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print('Three packets, five descriptor paths and three wait budgets checked; no kernel or camera operation.')


if __name__ == '__main__':
    main()
