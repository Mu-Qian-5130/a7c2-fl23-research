"""Original PLL programming and lock-poll contracts, offline only.

Register seeds, alias words and lock words are explicit slice inputs.
No oscillator, lock response, delay service or clock-rate change is supplied.
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
CFG_MASK=0x043fff1f


def audit(cp):
    if hashlib.sha256(cp).hexdigest()!=SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported original stock CP')
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    for page in (0xb74000,0xb71000,0x52a000,0xe94000):
        u.mem_map(page,4096);u.mem_write(page,cp[page-BASE:page-BASE+4096])
    for page in (STACK,STOP,0x1a76000,0xf1388000):u.mem_map(page,4096)
    stops,seen,writes=set(),[],[];alias=0;selection=0
    def boundary(cpu,address,size,user):
        if address in stops:seen.append(address);cpu.emu_stop()
    def io_write(cpu,access,address,size,value,user):
        nonlocal selection
        if 0xf1388000<=address<0xf1389000:
            assert size==4;writes.append((address,value))
            if address==0xf1388204:selection|=value
            elif address==0xf1388208:selection&=~value
    def io_read(cpu,access,address,size,value,user):
        if address in (0xf1388204,0xf1388208,0xf1388074,0xf1388078):cpu.mem_write(address,struct.pack('<I',alias))
    u.hook_add(UC_HOOK_CODE,boundary);u.hook_add(UC_HOOK_MEM_WRITE,io_write);u.hook_add(UC_HOOK_MEM_READ,io_read)
    def run(entry,target,inputs=(),count=500):
        stops.clear();stops.add(target);seen.clear();writes.clear()
        u.reg_write(R.UC_ARM_REG_SP,STACK+0xf00);u.reg_write(R.UC_ARM_REG_LR,STOP|1)
        for reg,value in inputs:u.reg_write(reg,value)
        u.emu_start(entry|1,0xffffffff,count=count)
        assert seen==[target] and u.reg_read(R.UC_ARM_REG_PC)==target,'Missing original boundary'
        return list(writes)
    def table(address):return struct.unpack_from('<I',cp,address-BASE)[0]
    cases=[];programs=[]
    for preset in range(3):
      selector=table(0xe949dc+preset*4)
      assert not selector&~0xfd13
      for mode in (0,1):
       expected_cfg=[table(0xe948ec+slot*0x18+preset*8+mode*4)&CFG_MASK for slot in range(5)]
       expected_div=[table(0xe94964+off+preset*8+mode*4)&0x7fe for off in (0x18,0x48)]
       programs.append(dict(preset=preset,mode=mode,selector=selector,coefficients=expected_cfg,dividers=expected_div))
       for seed in (0,0xfbc000e0,0xffffffff):
        for returned in (0,0xffffffff):
            alias=returned;selection=0xfd13
            for off in (0,4,8,12,16,0x50,0x58):u.mem_write(0xf1388100+off,struct.pack('<I',seed))
            actual=run(0xb74860,STOP,((R.UC_ARM_REG_R0,preset),(R.UC_ARM_REG_R1,mode)))
            assert len(actual)==9
            assert actual[:2]==[(0xf1388204,selector),(0xf1388208,0xfd13&~selector)]
            assert selection==selector
            cfg=[struct.unpack('<I',u.mem_read(0xf1388100+4*slot,4))[0] for slot in range(5)]
            div=[struct.unpack('<I',u.mem_read(0xf1388100+off,4))[0] for off in (0x50,0x58)]
            assert cfg==[(seed&~CFG_MASK)|word for word in expected_cfg]
            assert div==[(seed&~0x7fe)|word for word in expected_div]
            cases.append(dict(case='original-PLL-programming',preset=preset,mode=mode,seed=seed,alias_input=returned,clock_or_lock_qualified=False))
    for preset,mode in ((3,0),(0,2),(0xffffffff,1),(1,0xffffffff)):
        assert run(0xb74860,STOP,((R.UC_ARM_REG_R0,preset),(R.UC_ARM_REG_R1,mode)))==[]
        cases.append(dict(case='original-PLL-argument-guard',preset=preset,mode=mode,MMIO_writes=0))
    for slot in range(5):
      for entry,bit,set_bit in ((0x52a1fc,0x10000000,True),(0x52a244,0x10000000,False),(0x52a28c,0x08000000,False)):
        seed=0x18012300;address=0xf1388100+4*slot
        u.mem_write(address,struct.pack('<I',seed))
        actual=run(entry,STOP,((R.UC_ARM_REG_R0,slot),))
        expected=seed|bit if set_bit else seed&~bit
        assert actual==[(address,expected)]
        cases.append(dict(case='original-PLL-control-bit',slot=slot,entry=hex(entry),bit=hex(bit),set=set_bit,hardware_effect_qualified=False))
    polls=((0xb74b02,0xb74b08,0xb74b0a,0xf1388100,0),
           (0xb74bfe,0xb74c04,0xb74c06,0xf1388104,0),
           (0xb74c62,0xb74c68,0xb74c6a,0xf1388104,4),
           (0xb74d46,0xb74d4c,0xb74d4e,0xf138810c,0),
           (0xb74da6,0xb74dac,0xb74dae,0xf138810c,4))
    for entry,branch,after,r4,offset in polls:
      for word in (0,0x18000000,0x01000000,0xffffffff):
        u.mem_write(r4+offset,struct.pack('<I',word))
        assert run(entry,branch,((R.UC_ARM_REG_R4,r4),))==[]
        target=after if word&0x1000000 else entry
        assert run(branch,target)==[]
        cases.append(dict(case='original-lock-poll',entry=hex(entry),synthetic_word=word,leaves_poll=target==after,hardware_lock_supplied=False))
    u.mem_write(0xf1388100,struct.pack('<I',0x10000000))
    assert run(0xb74afa,0xb74b02,((R.UC_ARM_REG_R4,0xf1388100),))==[(0xf1388100,0x18000000)]
    cases.append(dict(case='original-start-write-does-not-set-lock',start_bit=27,lock_bit=24))
    for state in (0,1):
      for returned in (0,0xffffffff):
        alias=returned
        actual=run(0xb740e2,STOP,((R.UC_ARM_REG_R0,state),))
        assert actual==[(0xf1388074 if state else 0xf1388078,0x400000)]
        assert struct.unpack('<I',u.mem_read(0x1a764f4,4))[0]==returned
        cases.append(dict(case='original-PLL0-logic-gate',state=state,alias_input=returned,bit=22,physical_effect_qualified=False))
    return dict(camera_io=False,CP_sha256=hashlib.sha256(cp).hexdigest(),programs=programs,cases=cases,
        coefficient_mask=hex(CFG_MASK),divider_mask='0x7fe',selector_mask='0xfd13',
        limits=['Original tables in this report are private source data, not a deployment image',
                'Seeds and lock words are synthetic inputs; no lock, rate, power or timing is proved',
                'No native peer, exposure, retained RAW, save/cancel or physical restore is tested'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();report=audit(args.cp.read_bytes())
    with args.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print(f"{len(report['cases'])} original PLL programming/control/lock-poll contracts passed; hardware lock not supplied")


if __name__=='__main__':main()
