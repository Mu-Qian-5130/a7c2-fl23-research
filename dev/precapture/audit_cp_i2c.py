"""Pinned original CP I2C descriptors and instruction slices, offline only.

External clock/reset/disable services are unexecuted boundaries. FIFO words
and table arguments are explicit slice inputs, not native device evidence.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE
from unicorn import arm_const as R
from support.reference import SPECS

BASE=0x108000
DATA,STACK=0x30000000,0x30010000


def audit(cp):
    if hashlib.sha256(cp).hexdigest()!=SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported original stock CP')
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    for page in (0xbf7000,0xbef000,0xbe9000,0x55d000,0x55e000,0xea0000,0xea2000,0x11d8000):
        u.mem_map(page,4096);u.mem_write(page,cp[page-BASE:page-BASE+4096])
    for page in (DATA,STACK,0x1a7e000):u.mem_map(page,4096)
    u.mem_map(0x4000000,4096)
    for port in range(5):u.mem_map(0xf1012000+port*4096,4096)
    stops,seen=set(),[]
    def boundary(cpu,address,size,user):
        if address in stops:seen.append(address);cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE,boundary)
    def run(entry,target,inputs):
        stops.clear();stops.add(target);seen.clear()
        u.reg_write(R.UC_ARM_REG_SP,STACK+0xf00)
        for reg,value in inputs:u.reg_write(reg,value)
        u.emu_start(entry|1,0xffffffff,count=80)
        assert seen==[target] and u.reg_read(R.UC_ARM_REG_PC)==target,'Missing original boundary'
    records,cases=[],[]
    for port in range(5):
        base,irq=struct.unpack_from('<I',cp,0x11d8470-BASE+4*port)[0],struct.unpack_from('<I',cp,0x11d8484-BASE+4*port)[0]
        clock_id=struct.unpack_from('<I',cp,0xea2a88-BASE+4*port)[0]
        reset_id=struct.unpack_from('<I',cp,0xea2a9c-BASE+4*port)[0]
        clock=struct.unpack_from('<3I',cp,0xea087c-BASE+clock_id*12)
        reset=struct.unpack_from('<3I',cp,0xea0c9c-BASE+reset_id*12)
        assert (base,irq,clock_id,reset_id)==(0xf1012000+port*4096,429+port,13+port,14+port)
        assert clock==(clock_id,0x50,18+port) and reset==(reset_id,0x350,24+port)
        records.append(dict(port=port,base=hex(base),IRQ=irq,clock_id=clock_id,reset_id=reset_id,
            clock_SET=hex(0xf1388004+clock[1]),clock_bit=clock[2],
            reset_CLR=hex(0xf1388008+reset[1]),reset_bit=reset[2]))
        run(0xbf799a,0xbef400,((R.UC_ARM_REG_R0,port),(R.UC_ARM_REG_R1,0)))
        assert u.reg_read(R.UC_ARM_REG_R0)==clock_id
        cases.append(dict(case='original-clock-ID-lookup',port=port,external_service_executed=False))
        run(0xbf7a40,0xbef516,((R.UC_ARM_REG_R0,port),))
        assert u.reg_read(R.UC_ARM_REG_R0)==reset_id
        cases.append(dict(case='original-reset-ID-lookup',port=port,external_service_executed=False))
        for tx,rx in ((1,1),(16,16),(32,8),(256,256)):
            word=((tx-1)<<16)|((rx-1)<<8)
            u.mem_write(base+0xf4,struct.pack('<I',word))
            run(0xbf79f8,0xbf7a10,((R.UC_ARM_REG_R0,base),(R.UC_ARM_REG_R2,1),
                (R.UC_ARM_REG_R4,port),(R.UC_ARM_REG_R5,0),(R.UC_ARM_REG_R6,DATA)))
            assert struct.unpack('<2I',u.mem_read(DATA+0x10,8))==(tx,rx)
            cases.append(dict(case='original-dynamic-FIFO-decode',port=port,TX=tx,RX=rx,synthetic_parameter_word=True,disable_service_executed=False))
    # Stop before the original consumer dereferences a missing table.
    u.mem_write(0x1a7e868,b'\0'*4)
    run(0xbe9a0a,0xbe9a14,((R.UC_ARM_REG_R0,0x92009e),))
    assert u.reg_read(R.UC_ARM_REG_R1)==0 and u.reg_read(R.UC_ARM_REG_R0)==0x92009e
    cases.append(dict(case='missing-table-consumer',dereference_executed=False,R1=0))
    # Only establish who stores the pointer, before any header validation.
    run(0x55e014,0x55e02e,((R.UC_ARM_REG_R0,DATA),))
    assert struct.unpack('<I',u.mem_read(0x1a7e868,4))[0]==DATA
    cases.append(dict(case='original-table-pointer-store',header_read_or_validation_executed=False,synthetic_argument=True))
    # All-zero table input is deliberately invalid; never admit a dummy header.
    run(0x55df9c,0x55e008,((R.UC_ARM_REG_R0,0x4000000),))
    assert struct.unpack('<I',u.mem_read(0x1a7e85c,4))[0]==0x4000000
    cases.append(dict(case='invalid-primary-table-header',all_zero_fixture=True,accepted=False))
    run(0x55e008,0x55e00c,())
    assert u.reg_read(R.UC_ARM_REG_R0)==0xffffffff
    cases.append(dict(case='original-invalid-table-error',result='0xffffffff'))
    run(0x55dce8,0x55dd0c,((R.UC_ARM_REG_R0,0xffffffff),))
    cases.append(dict(case='missing-secondary-table-branch',binding_executed=False,explicit_error_input=True))
    run(0x55dce8,0x55dcf0,((R.UC_ARM_REG_R0,0),))
    assert u.reg_read(R.UC_ARM_REG_R0)==0x4000000
    cases.append(dict(case='secondary-table-provider-boundary',provider_executed=False,synthetic_branch_input=True))
    return dict(camera_io=False,source_sha256=hashlib.sha256(cp).hexdigest(),records=records,cases=cases,
        limits=['Instruction slices do not initialize a controller or validate physical clock/reset values',
                'No native table/peer/pixels, AP/CP receipt, capture or recovery is supplied'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();report=audit(args.cp.read_bytes())
    with args.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print(f"{len(report['cases'])} original I2C/table instruction contracts passed; no camera access")


if __name__=='__main__':main()
