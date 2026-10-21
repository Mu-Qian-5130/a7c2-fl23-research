"""Original selector0x93 command/inverse sequences, pinned offline slices.

Readback words are explicit inputs. A zero software return does not confirm
hardware clock/reset state, sensor readiness or any physical capture action.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn import arm_const as R
from support.reference import SPECS

BASE,IO,STACK,STOP=0x108000,0xf5400000,0x30000000,0x31000000


def audit(cp):
    if hashlib.sha256(cp).hexdigest()!=SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported original stock CP')
    descriptor=struct.unpack_from('<5I',cp,0xe936a0-BASE+0x93*20)
    assert descriptor==(0x5d0,0x5e0,0xff8,0xdd0,0xff8)
    targets={0x52b4f8:0x52b50c+2*struct.unpack_from('<H',cp,0x52b50c-BASE+(0x93-1)*2)[0],
             0x52cc9c:0x52ccb0+2*struct.unpack_from('<H',cp,0x52ccb0-BASE+(0x93-1)*2)[0]}
    assert targets=={0x52b4f8:0x52ca00,0x52cc9c:0x52e18c}
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    for address,size in ((0x52b000,0x4000),(0xb71000,4096)):
        u.mem_map(address,size);u.mem_write(address,cp[address-BASE:address-BASE+size])
    for address,size in ((IO,0x10000),(STACK,4096),(STOP,4096),(0x1a76000,4096)):u.mem_map(address,size)
    seen,writes,reads=[],[],[];readback=0
    def boundary(cpu,address,size,user):
        if address==STOP:seen.append(address);cpu.emu_stop()
    def write(cpu,access,address,size,value,user):
        if IO<=address<IO+0x10000:writes.append((address,size,value))
    def read(cpu,access,address,size,value,user):
        if IO<=address<IO+0x10000:
            cpu.mem_write(address,struct.pack('<I',readback));reads.append((address,size))
    u.hook_add(UC_HOOK_CODE,boundary);u.hook_add(UC_HOOK_MEM_WRITE,write);u.hook_add(UC_HOOK_MEM_READ,read)
    def run(entry,argument):
        seen.clear();writes.clear();reads.clear()
        u.reg_write(R.UC_ARM_REG_SP,STACK+0xf00);u.reg_write(R.UC_ARM_REG_LR,STOP|1);u.reg_write(R.UC_ARM_REG_R0,argument)
        u.emu_start(entry|1,0xffffffff,count=500)
        assert seen==[STOP] and u.reg_read(R.UC_ARM_REG_PC)==STOP,'Missing original command return'
    first=(1,4,0x10,0x100,0x400,0x1000,0x4000);second=(1,4,0x10,0x40);third=(1,0x10)
    setting=[(IO+0x5d4,4,v) for v in first]+[(IO+0x5e4,4,v) for v in second]+[(IO+0xdd4,4,v) for v in third]
    inverse=[(IO+0xdd0,4,v) for v in third]+[(IO+0x5d0,4,v) for v in first]+[(IO+0x5e0,4,v) for v in second]
    cases=[]
    for entry,expected in ((0x52b4f8,setting),(0x52cc9c,inverse)):
      for word in (0,0xffffffff,0x55555555,0xaaaaaaaa):
        readback=word;run(entry,0x93)
        assert writes==expected and reads==[(a,s) for a,s,v in expected]
        assert u.reg_read(R.UC_ARM_REG_R0)==0
        assert struct.unpack('<I',u.mem_read(0x1a764f4,4))[0]==word
        cases.append(dict(case='original-command-sequence',entry=hex(entry),readback_input=word,writes=[dict(address=hex(a),size=s,value=v) for a,s,v in writes],software_return=0,hardware_success_qualified=False))
      for argument in (0,0x99,0xffffffff):
        run(entry,argument)
        assert not writes and not reads and u.reg_read(R.UC_ARM_REG_R0)==0xfffffff7
        cases.append(dict(case='original-dispatch-range-guard',entry=hex(entry),argument=argument,MMIO_accesses=0,result='-9'))
    cases.extend([dict(case='original-ID93-descriptor',words=[hex(v) for v in descriptor]),dict(case='original-TBH-dispatch',targets={hex(k):hex(v) for k,v in targets.items()})])
    return dict(camera_io=False,CP_sha256=hashlib.sha256(cp).hexdigest(),selector='0x93',cases=cases,
        requested_masks={'0x5d0':'0x5515','0x5e0':'0x55','0xdd0':'0x11'},
        limits=['Logical set/clear roles are inferred from paired command sequences; physical effects are unqualified',
                'Original zero returns occur for every tested readback input and do not prove hardware success',
                'No real clock/reset, peer, sensor, exposure, retained RAW, save/cancel or restoration is tested'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();report=audit(args.cp.read_bytes())
    with args.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print(f"{len(report['cases'])} original domain0x93 sequence/descriptor/dispatch contracts passed; hardware success unqualified")


if __name__=='__main__':main()
