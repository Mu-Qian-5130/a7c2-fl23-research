"""Original SPI selectors and scratch readback, independent offline slices.

Alias readback and initial selector words are explicit fixture inputs. No
real clock or external service is supplied; whole-camera behavior is untested.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn import arm_const as R
from support.reference import SPECS

BASE,MMIO,STACK,STOP=0x108000,0xf1388230,0x30000000,0x31000000


def audit(cp):
    if hashlib.sha256(cp).hexdigest()!=SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported original stock CP')
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    for page in (0x52a000,0xb71000,0xb74000):
        u.mem_map(page,4096);u.mem_write(page,cp[page-BASE:page-BASE+4096])
    for page in (STACK,STOP,0x1a76000,0xf1388000):u.mem_map(page,4096)
    targets,seen,trace=set(),[],[];selection=0;alias=0
    def boundary(cpu,address,size,user):
        if address in targets:seen.append(address);cpu.emu_stop()
    def memory_write(cpu,access,address,size,value,user):
        nonlocal selection
        if MMIO<=address<MMIO+12:
            assert size==4 and address in (MMIO+4,MMIO+8)
            trace.append(('write',address,value))
            if address==MMIO+4:selection|=value
            else:selection&=~value
    def memory_read(cpu,access,address,size,value,user):
        if MMIO<=address<MMIO+12:
            assert size==4 and address in (MMIO+4,MMIO+8)
            cpu.mem_write(address,struct.pack('<I',alias));trace.append(('read',address,alias))
    u.hook_add(UC_HOOK_CODE,boundary);u.hook_add(UC_HOOK_MEM_WRITE,memory_write);u.hook_add(UC_HOOK_MEM_READ,memory_read)
    fields=((0x52a774,16,3,4),(0x52a7c8,8,7,7),(0x52a840,4,7,7),(0x52a8a8,0,7,7))
    cases=[]
    for entry,shift,width,count in fields:
      mask=width<<shift
      for seed in (0,0x30777):
       for returned in (0,0xffffffff,0x55555555,0xaaaaaaaa):
        for token in range(count):
            alias=returned;selection=seed;trace.clear();targets.clear();targets.add(STOP);seen.clear()
            argument=token<<shift
            u.reg_write(R.UC_ARM_REG_SP,STACK+0xf00);u.reg_write(R.UC_ARM_REG_LR,STOP|1)
            u.reg_write(R.UC_ARM_REG_R0,argument)
            u.emu_start(entry|1,0xffffffff,count=250)
            assert seen==[STOP] and u.reg_read(R.UC_ARM_REG_PC)==STOP,'Missing original return'
            assert trace==[('write',MMIO+4,argument),('read',MMIO+4,returned),('write',MMIO+8,mask&~argument),('read',MMIO+8,returned)]
            assert selection==((seed&~mask)|argument)
            assert struct.unpack('<I',u.mem_read(0x1a764f4,4))[0]==returned
            cases.append(dict(case='original-selector-and-scratch',entry=hex(entry),shift=shift,token=token,seed=seed,alias_input=returned,selection=selection))
      for argument in (count<<shift,0xffffffff):
        trace.clear();seen.clear();targets.clear();targets.add(STOP)
        u.reg_write(R.UC_ARM_REG_SP,STACK+0xf00);u.reg_write(R.UC_ARM_REG_LR,STOP|1);u.reg_write(R.UC_ARM_REG_R0,argument)
        u.emu_start(entry|1,0xffffffff,count=100)
        assert seen==[STOP] and not trace
        cases.append(dict(case='original-invalid-selector',entry=hex(entry),argument=argument,MMIO_accesses=0))
    # The observed direct caller overwrites the helper return before its next service.
    for returned in (0,0xffffffff,0x55555555,0xaaaaaaaa):
        targets.clear();targets.add(0xb74534);seen.clear();trace.clear()
        for reg,value in ((R.UC_ARM_REG_R0,returned),(R.UC_ARM_REG_R5,0x75),(R.UC_ARM_REG_R4,0)):
            u.reg_write(reg,value)
        u.emu_start(0xb74531,0xffffffff,count=10)
        assert seen==[0xb74534] and u.reg_read(R.UC_ARM_REG_R0)==0x75 and u.reg_read(R.UC_ARM_REG_R1)==0
        cases.append(dict(case='observed-caller-overwrites-return',synthetic_return=returned,next_service_executed=False))
    return dict(camera_io=False,CP_sha256=hashlib.sha256(cp).hexdigest(),selector_mask='0x30777',cases=cases,
        limits=['SPI clock rates, physical alias values, timing and ready signals are unqualified',
                'Readback independence applies to these routines and the observed caller slice, not all firmware',
                'No native AP/CP receipt, exposure, retained RAW, save/cancel or physical restore is tested'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();report=audit(args.cp.read_bytes())
    with args.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print(f"{len(report['cases'])} original SPI selector/scratch contracts passed; no physical clock supplied")


if __name__=='__main__':main()
