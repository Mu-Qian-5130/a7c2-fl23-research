"""Offline generated AP parameter names, not ELF symbols or function addresses.

Follows the name-array discovery documented in the owner's October23 handoff.
ELF sections supply the coordinate conversion; interior string pointers remain
valid. Nothing here opens USB or interprets a parameter ID as a Backup key.
"""
import io
import re
import struct

from elftools.elf.elffile import ELFFile

ANCHOR=b'PRM_FEATURE_MANAGER_camera_parameters'
TOKEN=re.compile(rb'[A-Za-z_][A-Za-z0-9_]+\Z')


class Names:
    def __init__(self, raw):
        self.raw=raw
        elf=ELFFile(io.BytesIO(raw))
        if not (elf.elfclass==64 and elf.little_endian and elf['e_machine']=='EM_AARCH64'
                and elf['e_type']=='ET_DYN'):
            raise ValueError('AArch64 little-endian ELF64 shared object required')
        sections={name:elf.get_section_by_name(name) for name in ('.rodata','.data.rel.ro')}
        if any(section is None for section in sections.values()):
            raise ValueError('Missing original AP name-table sections')
        self.sections={name:{key:section[key] for key in ('sh_addr','sh_offset','sh_size')}
                       for name,section in sections.items()}
        for section in self.sections.values():
            start,size=section['sh_offset'],section['sh_size']
            if start<0 or size<=0 or start+size>len(raw):raise ValueError('Section outside file')
        ro=self.sections['.rodata'];data=self.sections['.data.rel.ro']
        first=ro['sh_offset'];end=first+ro['sh_size']
        anchor_at=raw.find(ANCHOR+b'\0',first,end)
        if anchor_at<0 or raw.find(ANCHOR+b'\0',anchor_at+1,end)>=0:
            raise ValueError('Expected one generated-name anchor')
        pointer=struct.pack('<Q',ro['sh_addr']+anchor_at-first)
        begin=data['sh_offset'];limit=begin+data['sh_size'];candidates=[]
        at=raw.find(pointer,begin,limit)
        while at>=0:
            if at%8==0:
                rows=[];cursor=at
                while cursor+8<=limit:
                    address=struct.unpack_from('<Q',raw,cursor)[0]
                    text=self._string(address)
                    if text is None:break
                    rows.append(dict(index=len(rows),name=text,
                        pointer_file_offset=cursor,string_address=address,
                        string_file_offset=first+address-ro['sh_addr']))
                    cursor+=8
                if len(rows)>=1000 and sum(row['name'].startswith(('PRM_','VAL_','FUNC_'))
                                           for row in rows)>=len(rows)*0.99:
                    candidates.append((at,rows))
            at=raw.find(pointer,at+1,limit)
        if len(candidates)!=1:raise ValueError('Generated name array absent or ambiguous')
        self.array_file_offset,self.entries=candidates[0]
        self.array_address=data['sh_addr']+self.array_file_offset-begin

    def _string(self,address):
        ro=self.sections['.rodata']
        if not ro['sh_addr']<=address<ro['sh_addr']+ro['sh_size']:return None
        offset=ro['sh_offset']+address-ro['sh_addr']
        end=self.raw.find(b'\0',offset,min(offset+4096,ro['sh_offset']+ro['sh_size']))
        if end<0:return None
        token=self.raw[offset:end]
        # No preceding-NUL condition: some original pointers name suffixes.
        return token.decode('ascii') if TOKEN.fullmatch(token) else None
