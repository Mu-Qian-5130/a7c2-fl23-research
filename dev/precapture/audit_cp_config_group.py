"""Original stock CP configuration-group admission, offline source slices.

This does not execute a complete command parser or any initialization callback.
Every original external service is an unexecuted boundary. Whole-guest runs
separately establish the original TOMCO parser's loaded group value.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn import arm_const as R
from support.reference import SPECS

BASE, TABLE, DATA, STACK, STOP = 0x108000, 0xeb55c4, 0x30000000, 0x30010000, 0x31000000
GROUP = 0x1a9e53c
TOMCO_SHA='02b202a9b4fbf7bdcbe93d032bfe475a21859019a3c02d1766ac133a779650d3'


def audit(cp):
    if hashlib.sha256(cp).hexdigest()!=SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported original stock CP')
    u=Uc(UC_ARCH_ARM,UC_MODE_ARM)
    for address,size in ((0x634000,4096),(0xeb5000,0x1000),(GROUP&~4095,4096),
                         (DATA,4096),(STACK,4096),(STOP,4096)):
        u.mem_map(address,size)
        if address in (0x634000,0xeb5000):u.mem_write(address,cp[address-BASE:address-BASE+size])
    stops,seen=set(),[]
    def boundary(cpu,address,size,user):
        if address in stops:seen.append(address);cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE,boundary)
    def run(entry,targets,inputs=()):
        stops.clear();stops.update(targets);seen.clear()
        for register,value in inputs:u.reg_write(register,value)
        u.emu_start(entry,0xffffffff,count=100)
        assert len(seen)==1 and u.reg_read(R.UC_ARM_REG_PC)==seen[0], 'Missing original boundary'
        return seen[0]
    records=[]
    for index in range(14):
        flags,arg,entry,mask,enabled=struct.unpack_from('<5I',cp,TABLE-BASE+index*20)
        ptr=struct.unpack_from('<I',cp,0xeb56e0-BASE+index*4)[0]
        name=cp[ptr-BASE:ptr-BASE+100].split(b'\0')[0].decode('ascii')
        records.append(dict(index=index,name=name,entry=hex(entry),group_mask=mask))
    cases=[];selected={}
    for group in (0,1,2,3,31,32,255,256,258,0xffffffff):
        u.mem_write(DATA,struct.pack('<I',group));admitted=[]
        for row in records:
            before=bytes(u.mem_read(0xeb5000,4096))
            at=run(0x6349b8,(0x6349d4,0x634da8),((R.UC_ARM_REG_R11,row['index']),
                (R.UC_ARM_REG_R6,DATA),(R.UC_ARM_REG_R7,TABLE)))
            # ARM register-shift semantics, including the low-byte shift field.
            shift=group&255
            bit=1<<shift if shift<32 else 0
            expected=bool(row['group_mask']&bit)
            assert (at==0x6349d4)==expected
            assert bytes(u.mem_read(0xeb5000,4096))==before
            assert bytes(u.mem_read(DATA,4))==struct.pack('<I',group)
            if expected:admitted.append(row['name'])
            cases.append(dict(case='group-mask-admission',group=group,index=row['index'],
                              admitted=expected,callback_executed=False))
        selected[str(group)]=admitted
    assert selected['0']==['TOPPERS_KERNEL']
    assert len(selected['1'])==11 and len(selected['2'])==14
    assert {'PCIDMA_INIT','OSAL_UIPC_INIT','PCIEIF_INIT'}.issubset(selected['2'])
    # Handler first stops BEFORE its original keyword-comparison service.
    u.mem_write(DATA,b'usrrtn_cfggrp\0'+bytes(32))
    u.mem_write(DATA+128,b'2\0')
    assert run(0x634790,(0x6347a0,),((R.UC_ARM_REG_R0,DATA),(R.UC_ARM_REG_R1,DATA+128),
        (R.UC_ARM_REG_SP,STACK+0x800),(R.UC_ARM_REG_LR,STOP)))==0x6347a0
    assert u.reg_read(R.UC_ARM_REG_R2)==14
    assert bytes(u.mem_read(u.reg_read(R.UC_ARM_REG_R1),14))==b'usrrtn_cfggrp\0'
    cases.append(dict(case='keyword-comparison-boundary',comparison_executed=False))
    # Independent post-comparison inputs, never an injected successful service.
    for status in (0,1,0xffffffff):
        u.mem_write(STACK+0x800,struct.pack('<2I',0x12345678,STOP))
        at=run(0x6347a4,(0x6347c0,STOP),((R.UC_ARM_REG_R0,status),
            (R.UC_ARM_REG_R4,DATA+128),(R.UC_ARM_REG_SP,STACK+0x800)))
        assert at==(0x6347c0 if status==0 else STOP)
        cases.append(dict(case='post-keyword-result',synthetic_status=status,
                          numeric_conversion_executed=False))
    for value in (0,1,2,31,32,256,0xffffffff):
        u.mem_write(GROUP,b'\xa5'*4)
        u.mem_write(STACK+0x800,struct.pack('<2I',0x12345678,STOP))
        assert run(0x6347c4,(STOP,),((R.UC_ARM_REG_R0,value),(R.UC_ARM_REG_SP,STACK+0x800)))==STOP
        assert bytes(u.mem_read(GROUP,4))==struct.pack('<I',value)
        assert u.reg_read(R.UC_ARM_REG_R0)==1
        cases.append(dict(case='post-numeric-result-store',synthetic_value=value,
                          conversion_executed=False,range_check_present=False))
    return dict(cases=cases,records=records,selected=selected,
        limits=['No full tokenizer, numeric conversion or initialization callback executes here',
                'Register-shift wrap cases do not authorize arbitrary configuration values',
                'Original group2 selection does not establish its peripheral initialization or AP readiness'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp',type=Path,required=True)
    parser.add_argument('--tomco',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();cp=args.cp.read_bytes();tomco=args.tomco.read_bytes()
    if len(tomco)!=741 or hashlib.sha256(tomco).hexdigest()!=TOMCO_SHA:
        raise ValueError('Unsupported original stock TOMCO configuration')
    assert tomco.startswith(b'[TOMCO]\nusrrtn_cfggrp=2\n')
    report=dict(schema='OFFLINE_CP_CONFIG_GROUP_ADMISSION/1',camera_io=False,
        CP_sha256=hashlib.sha256(cp).hexdigest(),TOMCO_sha256=TOMCO_SHA,**audit(cp))
    files=[Path(__file__),Path(__file__).with_name('support')/'reference.py']
    report['sources']={str(f.relative_to(Path(__file__).parent)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    with args.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print(f"{len(report['cases'])} original group/handler contracts; group0 admits1 entry, group2 admits14; no callback success supplied.")


if __name__=='__main__':
    main()
