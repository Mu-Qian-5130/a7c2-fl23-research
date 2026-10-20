"""Pinned AArch64 ET_REL image in synthetic emulator memory only.

Apply own-section ABS64 relocations; expose external call boundaries instead
of executing kernel APIs. This is not a live or general kernel loader.
"""

import hashlib
import io
import struct
from elftools.elf.elffile import ELFFile

UIPC_SHA = "f0eb3a32a9d339066600e012aa3e91de31419c173e3fe5c1cc44aa9188763095"
PCIE_SHA = "26f376a9025f0b56b5ede7ebabdbf5dd8a5235d6627abe2abfd1430e2af578bc"


def q(value):
    return struct.pack("<Q", value)


class Module:
    def __init__(self, u, raw, digest, base):
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("Unsupported original kernel module")
        self.u = u
        e = self.elf = ELFFile(io.BytesIO(raw))
        assert e["e_type"] == "ET_REL" and e["e_machine"] == "EM_AARCH64"
        symbols = e.get_section_by_name(".symtab")
        self.names, self.bases, self.calls, self.rel = {}, {}, {}, {}
        for i, sec in enumerate(e.iter_sections()):
            if not sec["sh_flags"] & 2 or not sec["sh_size"]:
                continue
            address = base + len(self.bases) * 0x100000
            assert sec["sh_size"] <= 0x100000
            self.names[sec.name] = address
            self.bases[i] = address
            u.mem_map(address, (sec["sh_size"] + 4095) & ~4095)
            if sec["sh_type"] != "SHT_NOBITS":
                u.mem_write(address, sec.data())
        for sec in e.iter_sections():
            if sec["sh_type"] != "SHT_RELA" or sec["sh_info"] not in self.bases:
                continue
            for r in sec.iter_relocations():
                sym = symbols.get_symbol(r["r_info_sym"])
                at = self.bases[sec["sh_info"]] + r["r_offset"]
                self.rel[at] = dict(
                    type=r["r_info_type"],
                    name=sym.name,
                    section=sym["st_shndx"],
                    addend=r["r_addend"],
                )
                if r["r_info_type"] == 257 and sym["st_shndx"] in self.bases:
                    u.mem_write(
                        at, q(self.bases[sym["st_shndx"]] + sym["st_value"] + r["r_addend"])
                    )
                elif r["r_info_type"] in (282, 283):
                    self.calls[at] = sym.name
        self.functions = {
            sym.name: (self.bases[sym["st_shndx"]] + sym["st_value"], sym["st_size"])
            for sym in symbols.iter_symbols()
            if sym["st_info"]["type"] == "STT_FUNC" and sym["st_shndx"] in self.bases
        }

    def at(self, section, offset):
        return self.names[section] + offset
