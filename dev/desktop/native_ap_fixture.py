"""Read an explicitly provided ELF for bounded native instruction diagnostics."""
from pathlib import Path
import struct
from types import SimpleNamespace
from elftools.elf.elffile import ELFFile

def load(source):
    path=Path(source);raw=path.read_bytes()
    with path.open('rb')as stream:
        elf=ELFFile(stream)
        if elf['e_machine']!='EM_AARCH64':raise ValueError('AArch64 AP required')
        segments=[(s['p_offset'],s['p_vaddr'],s['p_filesz']) for s in elf.iter_segments() if s['p_type']=='PT_LOAD']
        rel={at:add for at,info,add in struct.iter_unpack('<QQq',elf.get_section_by_name('.rela.dyn').data()) if info&0xffffffff==1027}
    def offset(address):
        for at,va,size in segments:
            if va<=address<va+size:return address-va+at
        raise ValueError('Address has no original file-backed mapping: '+hex(address))
    return SimpleNamespace(SOURCE=path,raw=raw,rel=rel,offset=offset)
