"""Synthetic AArch64 initializer fixture, never a native/camera DSO loader."""
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM
from unicorn.arm64_const import UC_ARM64_REG_SP,UC_ARM64_REG_LR
import struct
from .elf import check_integer_isa
from .memory import MEM,STACK,STOP


def load(path,*,stop=STOP,bias=0x1000000):
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);pages=set()
    with path.open('rb') as stream:
        elf=ELFFile(stream)
        assert elf['e_type']=='ET_DYN' and elf['e_machine']=='EM_AARCH64' and elf.little_endian
        check_integer_isa(elf,'aarch64')
        tags=list(elf.get_section_by_name('.dynamic').iter_tags())
        assert not any(tag.entry.d_tag in ('DT_NEEDED','DT_INIT_ARRAY') for tag in tags)
        entries=[tag.entry.d_ptr for tag in tags if tag.entry.d_tag=='DT_INIT']
        assert len(entries)==1
        start=bias+entries[0]
        assert any(segment['p_type']=='PT_LOAD' and segment['p_flags']&1 and
                   segment['p_vaddr']<=entries[0]<segment['p_vaddr']+segment['p_filesz']
                   for segment in elf.iter_segments())
        for segment in elf.iter_segments():
            assert segment['p_type']!='PT_INTERP'
            if segment['p_type']!='PT_LOAD' or not segment['p_memsz']:continue
            assert segment['p_filesz']<=segment['p_memsz']
            for at in range((bias+segment['p_vaddr'])&~4095,
                            (bias+segment['p_vaddr']+segment['p_memsz']+4095)&~4095,4096):
                if at not in pages:u.mem_map(at,4096);pages.add(at)
            u.mem_write(bias+segment['p_vaddr'],segment.data())
        for section in elf.iter_sections():
            if section['sh_type']=='SHT_REL' and section['sh_flags']&2:
                assert not section.num_relocations()
            if section['sh_type']=='SHT_RELA' and section['sh_flags']&2:
                for relocation in section.iter_relocations():
                    assert relocation['r_info_type']==1027 and not relocation['r_info_sym']
                    u.mem_write(bias+relocation['r_offset'],struct.pack('<Q',bias+relocation['r_addend']))
    for at,size in ((MEM,65536),(STACK,65536),(stop,4096)):u.mem_map(at,size)
    u.reg_write(UC_ARM64_REG_SP,STACK+0x8000);u.reg_write(UC_ARM64_REG_LR,stop)
    return u,start
