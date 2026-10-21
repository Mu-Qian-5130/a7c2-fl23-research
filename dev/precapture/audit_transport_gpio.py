"""Original AP/CP GPIO startup contracts; no GPIO/semaphore/notification executes.

Independent post-service slices never provide a successful hardware operation.
Endpoint record correspondence is not an admission of physical inter-chip wiring.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from unicorn import Uc,UC_ARCH_ARM,UC_ARCH_ARM64,UC_MODE_ARM,UC_MODE_THUMB,UC_HOOK_CODE
from unicorn import arm_const as A
from support.kernel import Module,PCIE_SHA
from support.reference import SPECS
from support.boundaries import BoundaryRunner
from support.memory import MEM,STACK,STOP


def cp_audit(raw):
    if hashlib.sha256(raw).hexdigest()!=SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported original CP')
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    for address in (0x56a000,0xbee000,0xea0000):
        u.mem_map(address,4096);u.mem_write(address,raw[address-0x108000:address-0x108000+4096])
    u.mem_map(MEM,4096);u.mem_map(STOP,4096)
    targets,seen=set(),[]
    def observe(cpu,address,size,user):
        if address in targets:seen.append(address);cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE,observe)
    def run(entry,stops,values=()):
        targets.clear();targets.update(stops);seen.clear()
        for register,value in values:u.reg_write(register,value)
        u.emu_start(entry|1,0xffffffff,count=100)
        assert len(seen)==1 and u.reg_read(A.UC_ARM_REG_PC)==seen[0], 'Expected original boundary not reached'
        return seen[0]
    records=[];cases=[]
    for selector in (0,1):
        port,bit=raw[0xea083c-0x108000+selector*8:0xea083c-0x108000+selector*8+2]
        assert (port,bit)==(18,3-selector)
        records.append(dict(selector=selector,port=port,bit=bit))
        assert run(0xbee7e0,(0xbee806,),((A.UC_ARM_REG_R0,selector),
            (A.UC_ARM_REG_SP,MEM+0x800),(A.UC_ARM_REG_LR,STOP|1)))==0xbee806
        cases.append(dict(case='CP-toggle-lock-boundary',selector=selector,semaphore_executed=False))
        # Explicit post-lock slice consumes no omitted service result.
        assert run(0xbee80a,(0xbee814,))==0xbee814
        assert (u.reg_read(A.UC_ARM_REG_R0),u.reg_read(A.UC_ARM_REG_R1))==(port,bit)
        cases.append(dict(case='CP-output-getter-boundary',selector=selector,GPIO_executed=False))
        for level in (0,1,2):
            at=run(0xbee818,(0xbee81a,0xbee824),((A.UC_ARM_REG_R0,level),))
            assert at==(0xbee824 if level==0 else 0xbee81a)
            cases.append(dict(case='CP-post-level-toggle-branch',selector=selector,
                              synthetic_level=level,output_operation_executed=False))
    assert run(0x56a95a,(0x56a95c,))==0x56a95c and u.reg_read(A.UC_ARM_REG_R0)==0
    cases.append(dict(case='CP-initial-output-selector',output_operation_executed=False))
    assert run(0x56a960,(0x56a964,))==0x56a964
    assert (u.reg_read(A.UC_ARM_REG_R0),u.reg_read(A.UC_ARM_REG_R1))==(17,2)
    cases.append(dict(case='CP-startup-input-getter',port=17,bit=2,GPIO_executed=False))
    for level in (0,1,2,0xffffffff):
        at=run(0x56a968,(0x56a96c,0x56a970),((A.UC_ARM_REG_R0,level),))
        assert at==(0x56a96c if level==1 else 0x56a970)
        cases.append(dict(case='CP-post-startup-level-guard',synthetic_level=level,
                          notification_boundary_reached=level==1,notification_executed=False))
    return dict(output_records=records,startup_input=dict(port=17,bit=2,required_level=1),cases=cases)


def ap_audit(raw):
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);module=Module(u,raw,PCIE_SHA,0x10000000)
    for address,size in ((MEM,0x10000),(STACK,0x10000),(STOP,4096)):u.mem_map(address,size)
    run=BoundaryRunner(u,(module,),stop=STOP,stack=STACK)
    at=lambda offset:module.at('.text',offset)
    table=struct.unpack('<Q',bytes(u.mem_read(at(0x3ee0),8)))[0]+0x18
    records=[];cases=[]
    for selector in (0,1):
        port,bit=bytes(u.mem_read(table+selector*16,2));assert (port,bit)==(18,9-selector)
        records.append(dict(selector=selector,port=port,bit=bit))
        got=run.call(at(0x3e20),(selector,));assert got['call']=='pcieif_sem_lock'
        cases.append(dict(case='AP-toggle-lock-boundary',selector=selector,semaphore_executed=False))
        got=run.run(at(0x3e5c));assert got['call']=='gpio_get_data_bit' and got['args'][:2]==[port,bit]
        cases.append(dict(case='AP-output-getter-boundary',selector=selector,GPIO_executed=False))
    got=run.call(at(0),());assert got['call']=='pcieif_set_interrupt' and got['args'][0]==0
    cases.append(dict(case='AP-initial-output-selector',output_operation_executed=False))
    got=run.run(at(0x10));assert got['call']=='gpio_get_data_bit' and got['args'][:2]==[17,4]
    cases.append(dict(case='AP-startup-input-getter',port=17,bit=4,GPIO_executed=False))
    return dict(output_records=records,startup_input=dict(port=17,bit=4),cases=cases)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp',type=Path,required=True)
    parser.add_argument('--pcie',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();cp=args.cp.read_bytes();pcie=args.pcie.read_bytes()
    report=dict(schema='OFFLINE_AP_CP_GPIO_STARTUP/1',camera_io=False,
        CP_sha256=hashlib.sha256(cp).hexdigest(),AP_module_sha256=hashlib.sha256(pcie).hexdigest(),
        CP=cp_audit(cp),AP=ap_audit(pcie),
        limits=['No GPIO read/write, semaphore operation or initialization notification executes',
                'Post-getter levels are independent inputs, not native hardware results',
                'Output records do not establish physical peer wiring or IRQ routing',
                'No AP/CP receipt, pixels, saving, quiescence or camera safety is admitted'])
    files=[Path(__file__),*[Path(__file__).with_name('support')/name
        for name in ('kernel.py','reference.py','boundaries.py','memory.py')]]
    report['sources']={str(f.relative_to(Path(__file__).parent)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    with args.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print(f"{len(report['CP']['cases'])+len(report['AP']['cases'])} original GPIO startup contracts; no peer/notification success supplied.")


if __name__=='__main__':
    main()
