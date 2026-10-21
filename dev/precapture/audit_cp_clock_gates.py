"""Original CP clock-gate helper writes, exact-source offline slices.

Alias words and Boolean arguments are explicit slice inputs. No physical
clock effect, GPIO/peer readiness or native service success is supplied.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn import arm_const as R
from support.reference import SPECS

BASE,STACK,STOP=0x108000,0x30000000,0x31000000
GATES=((0xb740e2,0x70,22),(0xb740fa,0x70,21),(0xb74112,0x70,20),
       (0xb7412a,0x70,19),(0xb74142,0x70,18),(0xb7415a,0x70,17),
       (0xb74172,0x70,16),(0xb7418a,0x70,15),(0xb741a2,0x70,14),
       (0xb741ba,0x70,13),(0xb741d2,0x70,12),(0xb741ea,0x70,11),
       (0xb74202,0x70,10),(0xb7421c,0x70,8),(0xb74234,0x70,7),
       (0xb74248,0x70,6),(0xb7425c,0x70,5),(0xb74270,0x70,1),
       (0xb74284,0x70,0),(0xb74298,0,8))


def audit(cp):
    if hashlib.sha256(cp).hexdigest()!=SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported original stock CP')
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    for page in (0xb71000,0xb74000):
        u.mem_map(page,4096);u.mem_write(page,cp[page-BASE:page-BASE+4096])
    for page in (STACK,STOP,0x1a76000,0xf1388000):u.mem_map(page,4096)
    seen,writes,reads=[],[],[];alias=0
    def boundary(cpu,address,size,user):
        if address==STOP:seen.append(address);cpu.emu_stop()
    def write(cpu,access,address,size,value,user):
        if 0xf1388000<=address<0xf1389000:writes.append((address,size,value))
    def read(cpu,access,address,size,value,user):
        if 0xf1388000<=address<0xf1389000:
            cpu.mem_write(address,struct.pack('<I',alias));reads.append((address,size))
    u.hook_add(UC_HOOK_CODE,boundary);u.hook_add(UC_HOOK_MEM_WRITE,write);u.hook_add(UC_HOOK_MEM_READ,read)
    cases=[];masks={0:0,0x70:0}
    for entry,offset,bit in GATES:
        masks[offset]|=1<<bit
        for argument in (0,1,2,0xffffffff):
          for word in (0,0xffffffff):
            alias=word;seen.clear();writes.clear();reads.clear()
            u.reg_write(R.UC_ARM_REG_SP,STACK+0xf00);u.reg_write(R.UC_ARM_REG_LR,STOP|1);u.reg_write(R.UC_ARM_REG_R0,argument)
            u.emu_start(entry|1,0xffffffff,count=80)
            assert seen==[STOP] and u.reg_read(R.UC_ARM_REG_PC)==STOP,'Missing original return'
            address=0xf1388000+offset+(4 if argument==1 else 8)
            assert writes==[(address,4,1<<bit)] and reads==[(address,4)]
            assert struct.unpack('<I',u.mem_read(0x1a764f4,4))[0]==word
            cases.append(dict(entry=hex(entry),offset=hex(offset),bit=bit,argument=argument,alias_input=word,operation='SET' if argument==1 else 'CLR',hardware_effect_qualified=False))
    assert masks=={0:0x100,0x70:0x7ffde3}
    for word in (0,0xffffffff):
        alias=word;seen.clear();writes.clear();reads.clear()
        u.reg_write(R.UC_ARM_REG_SP,STACK+0xf00);u.reg_write(R.UC_ARM_REG_LR,STOP|1)
        u.emu_start(0xb7454b,0xffffffff,count=150)
        assert seen==[STOP] and u.reg_read(R.UC_ARM_REG_PC)==STOP
        bits=(24,23,22,7,19)
        assert writes==[(0xf1388074,4,1<<bit) for bit in bits]
        assert reads==[(0xf1388074,4)]*5
        cases.append(dict(entry='0xb7454a',operation='original-startup-SET-sequence',bits=list(bits),alias_input=word,hardware_effect_qualified=False))
        for bit in bits:masks[0x70]|=1<<bit
    assert masks[0x70]==0x1fffde3
    return dict(camera_io=False,CP_sha256=hashlib.sha256(cp).hexdigest(),gate_masks={hex(k):hex(v) for k,v in masks.items()},cases=cases,
        limits=['Only original software register operations and scratch/return words are checked',
                'Physical domains, rates, lock behavior, peer readiness and full boot remain unqualified',
                'No exposure, retained RAW, save/cancel or physical camera restoration is tested'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();report=audit(args.cp.read_bytes())
    with args.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print(f"{len(report['cases'])} original clock-gate contracts passed; physical clock effects not supplied")


if __name__=='__main__':main()
