"""Pinned original A7C II kernel slices for child setup; no native APIs execute.

Recovered kallsyms offsets are cross-checked against the binary syscall table.
Kernel code is relocated into synthetic Unicorn memory only. Open/mmap/locks,
current-task reads, reference counts, allocation and execution stop beforehand.
This does not retroactively identify the actual child EINVAL source.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from types import SimpleNamespace

from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM
from unicorn import arm64_const as R
from support.boundaries import BoundaryRunner

SHA='620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
NATIVE_BASE=0xffffff8008080000
CODE,MEM,STACK,STOP=0x10000000,0x30000000,0x40000000,0x50000000
CALL_TABLE=0x432000
SYSCALLS={52:0x10a2a8,56:0x10ab98,61:0x11f1f0,93:0x24850,220:0x1fa98,221:0x113ab0,281:0x113af0}


def audit(raw):
    if hashlib.sha256(raw).hexdigest()!=SHA:raise ValueError('Exact original Sony kernel required')
    assert raw[56:60]==b'ARMd' and struct.unpack_from('<Q',raw,8)[0]==0x80000
    checks=[]
    for nr,offset in SYSCALLS.items():
        value=struct.unpack_from('<Q',raw,CALL_TABLE+8*nr)[0]
        assert value==NATIVE_BASE+offset
        checks.append(dict(number=nr,original_entry_offset=hex(offset),table_matches=True))
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    u.mem_map(CODE,(len(raw)+4095)&~4095);u.mem_write(CODE,raw)
    for at,size in ((MEM,0x10000),(STACK,0x10000),(STOP,4096)):u.mem_map(at,size)
    A=lambda n:CODE+n
    calls={A(0x113b28):'getname_flags',A(0x111d18):'do_filp_open',
           A(0x158b20):'vm_mmap',A(0x158b58):'vm_mmap'}
    runner=BoundaryRunner(u,[SimpleNamespace(calls=calls)],stop=STOP,stack=STACK)

    path=MEM+0x1000;argv=MEM+0x2000;env=MEM+0x3000
    u.mem_write(path,b'\0')
    exec_flags=[]
    for flags in (0,0x1000):
        # sys_execveat takes five arguments; supply x4 explicitly to run.
        got=runner.run(A(0x113af0),inputs=[(R.UC_ARM64_REG_X0,22),(R.UC_ARM64_REG_X1,path),
            (R.UC_ARM64_REG_X2,argv),(R.UC_ARM64_REG_X3,env),(R.UC_ARM64_REG_X4,flags),
            (R.UC_ARM64_REG_SP,STACK+0x8000),(R.UC_ARM64_REG_LR,STOP)])
        assert got['at']==A(0x113b28) and got['args'][:3]==[path,0x4000 if flags else 0,0]
        exec_flags.append(dict(flags=hex(flags),lookup_empty=bool(flags&0x1000),getname_executed=False))
    for flags in (0,0x100,0x1000,0x1100,1,0x2000):
        got=runner.call(A(0x111cc0),(22,path,flags))
        accepted=not(flags&~0x1100)
        assert got['at']==(A(0x111d18) if accepted else STOP)
        if not accepted:assert got['args'][0]==(-22&((1<<64)-1))
        exec_flags.append(dict(flags=hex(flags),passes_flag_mask=accepted,open_executed=False))

    callback=MEM+0x4000
    dir_cases=[]
    for name_length,available in ((1,4096),(10,4096),(1,0),(10,24)):
        u.mem_write(callback,bytes(64));u.mem_write(callback+0x20,struct.pack('<I',available))
        got=runner.run(A(0x11ee40),(A(0x11ee58),A(0x11ee28)),inputs=[
            (R.UC_ARM64_REG_X19,callback),(R.UC_ARM64_REG_X22,name_length+27)])
        fits=((name_length+27)&~7)<=available
        assert got['at']==A(0x11ee58 if fits else 0x11ee28)
        assert struct.unpack('<i',bytes(u.mem_read(callback+0x24,4)))[0]==-22
        dir_cases.append(dict(name_length=name_length,available=available,record_fits=fits,
                              result_field_at_pre_copy=-22,user_copy_executed=False))

    # get_task_mm's original body reads task+2d8, excludes PF_KTHREAD, then
    # takes its reference. Stop before the reference or unlock call.
    task=MEM+0x5000;mm=MEM+0x7000;mm_cases=[]
    for pointer,kthread in ((0,False),(mm,False),(mm,True)):
        u.mem_write(task+0x2d8,struct.pack('<Q',pointer));u.mem_write(task+0x34,struct.pack('<I',0x200000 if kthread else 0))
        got=runner.run(A(0x1d338),(A(0x1d348),A(0x1d364)),inputs=[(R.UC_ARM64_REG_X20,task)])
        takes_ref=bool(pointer) and not kthread
        assert got['at']==A(0x1d348 if takes_ref else 0x1d364)
        if takes_ref:assert u.reg_read(R.UC_ARM64_REG_X19)==mm
        mm_cases.append(dict(synthetic_mm_present=bool(pointer),kernel_thread=kthread,
            reaches_mm_reference=takes_ref,atomic_or_lock_executed=False))
    for flags in (17,0x111):
        got=runner.run(A(0x1e71c),(A(0x1ea08),A(0x1e720)),inputs=[(R.UC_ARM64_REG_X28,flags)])
        shared=bool(flags&0x100)
        assert got['at']==A(0x1e720 if shared else 0x1ea08)
        mm_cases.append(dict(clone_flags=hex(flags),shares_mm_branch=shared,
            new_mm_path=not shared,allocation_or_mm_copy_executed=False))
    return dict(schema='OFFLINE_CHILD_KERNEL_BOUNDARIES/1',camera_io=False,kernel_sha256=SHA,
        syscall_table=checks,exec_flag_slices=exec_flags,directory_error_slices=dir_cases,mm_binding_slices=mm_cases,
        limits=['Cached original kernel, not a fresh live-kernel identity',
            'Native symbol names were recovered offline and syscall entry offsets independently cross-checked',
            'All process/path/buffer/flags/mm inputs are synthetic; no kernel or device call executed',
            'Supports execveat/AT_EMPTY_PATH but does not establish successful static ELF execution',
            'The prior combined EINVAL result cannot distinguish open/getdents/close/exec failure',
            'An inherited UIPC FD retains old mm ownership; a post-exec process needs a fresh verified context',
            'No child process, new firmware, CP message or real pre-capture is produced'])


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--kernel',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();report=audit(a.kernel.read_bytes())
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    count=sum(len(report[k]) for k in ('syscall_table','exec_flag_slices','directory_error_slices','mm_binding_slices'))
    print(f'{count} original kernel syscall/exec/directory/mm slices; no native API or camera execution.')
if __name__=='__main__':main()
