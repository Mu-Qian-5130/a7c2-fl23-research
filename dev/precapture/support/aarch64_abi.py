"""Compile target fcntl.h constants, without executing the generated ELF.

Production constants are checked by independent target-header static asserts.
This catches host-architecture flags accidentally copied into AArch64 code.
"""
import io
import struct
import subprocess
from pathlib import Path
from elftools.elf.elffile import ELFFile

FIELDS=('readonly','writeonly','create','exclusive','directory','nofollow','cloexec','direct')


def open_flags(zig,folder,*,header_directory=None):
    folder=Path(folder);folder.mkdir(exist_ok=False)
    source=folder/'target-open-flags.c';elf=folder/'NOT-EXECUTABLE-open-flags.elf'
    header=Path(header_directory) if header_directory is not None else Path(__file__).resolve().parents[1]
    source.write_text('''#define _GNU_SOURCE 1
#include <fcntl.h>
#include "ap_linux_aarch64.h"
_Static_assert(AP_A64_O_RDONLY==O_RDONLY,"readonly ABI");
_Static_assert(AP_A64_O_WRONLY==O_WRONLY,"write ABI");
_Static_assert(AP_A64_O_CREAT==O_CREAT,"create ABI");
_Static_assert(AP_A64_O_EXCL==O_EXCL,"exclusive ABI");
_Static_assert(AP_A64_O_DIRECTORY==O_DIRECTORY,"AArch64 directory ABI");
_Static_assert(AP_A64_O_NOFOLLOW==O_NOFOLLOW,"AArch64 nofollow ABI");
_Static_assert(AP_A64_O_CLOEXEC==O_CLOEXEC,"cloexec ABI");
_Static_assert(AP_A64_O_DIRECT==O_DIRECT,"AArch64 direct-IO ABI");
const unsigned int precapture_aarch64_open_flags[]={O_RDONLY,O_WRONLY,O_CREAT,O_EXCL,O_DIRECTORY,O_NOFOLLOW,O_CLOEXEC,O_DIRECT};
''',encoding='ascii')
    # -lc selects Zig's target libc headers; -c prevents any linking/runtime.
    command=[str(zig),'cc','-target','aarch64-linux-gnu','-lc','-c','-ffreestanding',
        '-I',str(header),'-o',str(elf),str(source)]
    result=subprocess.run(command,capture_output=True,text=True,timeout=120)
    if result.returncode:raise RuntimeError(result.stderr[-2500:])
    image=ELFFile(io.BytesIO(elf.read_bytes()))
    assert image['e_machine']=='EM_AARCH64' and image['e_type']=='ET_REL'
    assert image.get_section_by_name('.dynamic') is None
    symbol=next(s for s in image.get_section_by_name('.symtab').iter_symbols() if s.name=='precapture_aarch64_open_flags')
    assert symbol['st_info']['type']=='STT_OBJECT' and symbol['st_size']==32
    section=image.get_section(symbol['st_shndx']);offset=symbol['st_value']-section['sh_addr']
    values=struct.unpack('<8I',section.data()[offset:offset+32])
    output=dict(zip(FIELDS,values))
    output['read_flags']=output['readonly']|output['nofollow']|output['cloexec']
    output['directory_flags']=output['read_flags']|output['directory']
    output['exclusive_flags']=output['writeonly']|output['create']|output['exclusive']|output['nofollow']|output['cloexec']
    assert output['directory_flags']&output['direct']==0
    return output
