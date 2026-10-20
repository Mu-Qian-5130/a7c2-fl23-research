"""Pinned native UIPC wire/header fixtures on synthetic memory.

These execute original instruction slices up to external-call boundaries.
They do not open a device, allocate native memory or bind a live context.
"""

import hashlib
import struct
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import UC_ARM64_REG_SP, UC_ARM64_REG_LR
from unicorn import arm64_const as reg
from .kernel import Module, UIPC_SHA
from .memory import MEM, STACK, STOP

LIBRARY_SHA = "09ebf5980237fc473077dc844763dcb00cba423f431646e3be7c0ca49ea70ff3"


def q(value):
    return struct.pack("<Q", value)


def library(path):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != LIBRARY_SHA:
        raise ValueError("Unsupported original UIPC library")
    with path.open("rb") as f:
        elf = ELFFile(f)
        assert elf["e_machine"] == "EM_AARCH64"
        symbols = {
            s.name: (s["st_value"], s["st_size"])
            for s in elf.get_section_by_name(".dynsym").iter_symbols()
        }
        assert symbols["osal_snd_msg"] == (0x5E60, 684)
        assert symbols["u_osal_snd_msg"] == (0x3A10, 136)
        plt = elf.get_section_by_name(".plt")["sh_addr"] + 32
        reloc = elf.get_section_by_name(".rela.plt")
        dyn = elf.get_section(reloc["sh_link"])
        entries = {
            dyn.get_symbol(r["r_info_sym"]).name: plt + i * 16
            for i, r in enumerate(reloc.iter_relocations())
        }
        assert entries["ioctl"] == 0x2530 and entries["__errno_location"] == 0x26B0
        assert entries["u_osal_snd_msg"] == 0x2310
        fd_reloc = []
        for section in elf.iter_sections():
            if section["sh_type"] != "SHT_RELA":
                continue
            syms = elf.get_section(section["sh_link"])
            fd_reloc += [
                syms.get_symbol(r["r_info_sym"]).name
                for r in section.iter_relocations()
                if r["r_offset"] == 0x19FC8
            ]
        assert fd_reloc == ["uconf"]
        u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        pages = set()
        for seg in elf.iter_segments():
            if seg["p_type"] != "PT_LOAD" or not seg["p_memsz"]:
                continue
            for page in range(
                seg["p_vaddr"] & ~4095, (seg["p_vaddr"] + seg["p_memsz"] + 4095) & ~4095, 4096
            ):
                if page not in pages:
                    u.mem_map(page, 4096)
                    pages.add(page)
            u.mem_write(seg["p_vaddr"], seg.data())
    for at, n in ((MEM, 4096), (STACK, 0x10000), (STOP, 4096)):
        u.mem_map(at, n)
    # The single data relocation consumed by this prefix is explicitly
    # synthetic. No actual loaded uconf, descriptor or device is inspected.
    u.mem_write(0x19FC8, struct.pack("<Q", MEM))
    u.mem_write(MEM, struct.pack("<I", 77))
    return u, entries


def original_header(raw, native_library, payload_bytes=16, *, initial_byte=0xa5,
                    route=0x90030001, source_id=0x80020002):
    if hashlib.sha256(native_library).hexdigest() != LIBRARY_SHA:
        raise ValueError("Unsupported original UIPC library")
    # Fixture addresses belong to this emulator, not a live shared mapping.
    SHARED, SIZE = 0x60000000, 0x200000
    BLOCK, MESSAGE = SHARED + 0x1000, SHARED + 0x1040
    u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    m = Module(u, raw, UIPC_SHA, 0x10000000)
    for at, n in ((MEM, 4096), (STACK, 0x10000), (STOP, 4096), (SHARED, SIZE)):
        u.mem_map(at, n)
    A = lambda x: m.at(".text", x)
    queue = MEM + 0x400
    table = struct.unpack("<Q", bytes(u.mem_read(A(0x3518), 8)))[0]
    index = route & 0x7fff
    if index <= 63:
        u.mem_write(table + 0x10 + index * 8, q(queue))
    else:
        if (route & 0xffff8000) != 0x803f0000 or index < 0x6000:
            raise ValueError("Unsupported synthetic dynamic receive queue")
        # Separate, already-existing synthetic queue/trie. The original lookup
        # executes; no queue creation or dynamic-ID success is supplied.
        nodes = (MEM + 0x500, MEM + 0x600, MEM + 0x700)
        lookup = struct.unpack("<Q", bytes(u.mem_read(A(0x2978), 8)))[0]
        u.mem_write(lookup + 0x220 + ((index >> 9) & 63) * 8, q(nodes[0]))
        u.mem_write(nodes[0] + ((index >> 6) & 7) * 8, q(nodes[1]))
        u.mem_write(nodes[1] + ((index >> 3) & 7) * 8, q(nodes[2]))
        u.mem_write(nodes[2] + (index & 7) * 8, q(queue))
        u.mem_write(queue, b"\x08")
        u.mem_write(queue + 0x30, q(route & 0x0fffffff))
    if not 0 <= initial_byte <= 255:
        raise ValueError("Invalid synthetic pool initialization byte")
    u.mem_write(BLOCK, bytes([initial_byte]) * 128)
    boundaries = set(m.calls) | {STOP}
    seen = []

    def stop(cpu, at, size, _):
        if at in boundaries:
            seen.append(at)
            cpu.emu_stop()

    u.hook_add(UC_HOOK_CODE, stop)
    for r, v in (
        (reg.UC_ARM64_REG_X0, route),
        (reg.UC_ARM64_REG_X1, MEM + 0x300),
        (reg.UC_ARM64_REG_X2, payload_bytes),
        (reg.UC_ARM64_REG_X3, 0),
        (reg.UC_ARM64_REG_SP, STACK + 0x8000),
        (reg.UC_ARM64_REG_LR, STOP),
    ):
        u.reg_write(r, v)
    u.emu_start(A(0x3248), 0xFFFFFFFFFFFFFFFF, count=1000)
    assert seen == [A(0x32E8)] and m.calls[seen[0]] == "vpool_alloc"
    assert u.reg_read(reg.UC_ARM64_REG_X1) == 128 and u.reg_read(reg.UC_ARM64_REG_X2) == 0
    seen.clear()
    u.reg_write(reg.UC_ARM64_REG_X0, BLOCK)
    u.emu_start(A(0x32F0), STOP, count=1000)
    assert u.reg_read(reg.UC_ARM64_REG_PC) == STOP
    assert struct.unpack("<Q", bytes(u.mem_read(MEM + 0x300, 8)))[0] == MESSAGE
    before_source = bytes(u.mem_read(BLOCK, 128))
    leaf = 0x70007E20
    u.mem_map(leaf & ~4095, 4096)
    u.mem_write(leaf, native_library[0x7E20:0x7E30])
    u.reg_write(reg.UC_ARM64_REG_X0, MESSAGE)
    u.reg_write(reg.UC_ARM64_REG_X1, source_id)
    u.reg_write(reg.UC_ARM64_REG_LR, STOP)
    u.emu_start(leaf, STOP, count=5)
    assert u.reg_read(reg.UC_ARM64_REG_PC) == STOP
    u.reg_write(reg.UC_ARM64_REG_X0, MESSAGE)
    u.emu_start(leaf + 8, STOP, count=5)
    assert u.reg_read(reg.UC_ARM64_REG_PC) == STOP
    assert u.reg_read(reg.UC_ARM64_REG_X0) == source_id
    return before_source, bytes(u.mem_read(BLOCK, 128))
