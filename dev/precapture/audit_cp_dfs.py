"""Original CP/AP DFS register sequences, offline slices only.

Explicit status/flag words are independent slice inputs, not hardware results.
No external service or clock transition is fabricated or executed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from unicorn import Uc,UC_ARCH_ARM,UC_ARCH_ARM64,UC_MODE_THUMB,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn import arm_const as R,arm64_const as A
from elftools.elf.elffile import ELFFile
from support.reference import SPECS

UPM_SHA='a8b16e1484be48d32c4a401897d13378cf45e5ef6654ebdcfdef5fc593da32eb'
CP_BASE,STACK,STOP=0x108000,0x30000000,0x31000000


def audit(cp,upm_path):
    if hashlib.sha256(cp).hexdigest()!=SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported original stock CP')
    if hashlib.sha256(Path(upm_path).read_bytes()).hexdigest()!=UPM_SHA:
        raise ValueError('Unsupported original AP UPM module')
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    for page in (0xc0b000,0x595000):
        u.mem_map(page,4096);u.mem_write(page,cp[page-CP_BASE:page-CP_BASE+4096])
    for page in (STACK,STOP,0x1b1f000,0xf1388000):u.mem_map(page,4096)
    stops,seen,writes=set(),[],[]
    def boundary(cpu,address,size,user):
        if address in stops:seen.append(address);cpu.emu_stop()
    def memory_write(cpu,access,address,size,value,user):
        if 0xf1388000<=address<0xf1389000:writes.append((address,size,value))
    u.hook_add(UC_HOOK_CODE,boundary);u.hook_add(UC_HOOK_MEM_WRITE,memory_write)
    def run(entry,target,inputs=()):
        stops.clear();stops.add(target);seen.clear();writes.clear()
        u.reg_write(R.UC_ARM_REG_SP,STACK+0xf00);u.reg_write(R.UC_ARM_REG_LR,STOP|1)
        for reg,value in inputs:u.reg_write(reg,value)
        u.emu_start(entry|1,0xffffffff,count=100)
        assert seen==[target] and u.reg_read(R.UC_ARM_REG_PC)==target,'Missing original CP boundary'
        return list(writes)
    cases=[]
    assert run(0xc0be7c,STOP)==[(0xf1388f4c,4,0x101)]
    assert bytes(u.mem_read(0x1b1f9ca,1))==b'\1'
    cases.append(dict(case='original-CP-register-init',write='f1388f4c:101'))
    assert run(0x595cf0,0x595cfe)==[(0xf1388f4c,4,0x101)]
    cases.append(dict(case='original-DFS-init-register-write',external_calls_executed=False))
    u.mem_write(0x1b1f9cb,b'\1')
    assert run(0xc0be02,STOP,((R.UC_ARM_REG_R0,4),(R.UC_ARM_REG_R1,1)))==[]
    assert u.reg_read(R.UC_ARM_REG_R0)==4
    cases.append(dict(case='trial-guard-skips-registers',synthetic_flag=True))
    u.mem_write(0x1b1f9cb,b'\0')
    run(0xc0be02,0xc0be1c,((R.UC_ARM_REG_R0,4),(R.UC_ARM_REG_R1,1)))
    assert u.reg_read(R.UC_ARM_REG_R2)==0xf1388f48 and u.reg_read(R.UC_ARM_REG_R3)==0x101
    cases.append(dict(case='original-pre-request-write-boundary',write_not_executed=True))
    for word in (0x100,0x104,0x10100):
        u.mem_write(0xf1388f58,struct.pack('<I',word))
        assert run(0xc0be1e,0xc0be28,((R.UC_ARM_REG_R2,0xf1388f48),))==[]
        assert run(0xc0be28,0xc0be1e)==[]
        cases.append(dict(case='original-busy-loop-retained',status=word,synthetic_status=True,payload_or_start_written=False))
    for freq in (0,4,6):
      for mode in (0,1):
        u.mem_write(0xf1388f58,b'\0'*4)
        assert run(0xc0be1e,0xc0be2a,((R.UC_ARM_REG_R2,0xf1388f48),))==[]
        actual=run(0xc0be2a,0xc0be3a,((R.UC_ARM_REG_R0,freq),(R.UC_ARM_REG_R1,mode),(R.UC_ARM_REG_R2,0xf1388f48)))
        assert actual==[(0xf1388f54,4,freq|(mode<<8)),(0xf1388f50,4,1)]
        cases.append(dict(case='original-request-encoding',frequency_token=freq,mode=mode,synthetic_not_busy=True,hardware_effect_qualified=False))
    for word in (0,0x100,0x101,1,3):
        u.mem_write(0xf1388f48,struct.pack('<I',word))
        assert run(0xc0be40,0xc0be4a,((R.UC_ARM_REG_R0,0x101),(R.UC_ARM_REG_R2,0xf1388f48)))==[]
        target=0xc0be4c if word&0x101==1 else 0xc0be40
        assert run(0xc0be4a,target)==[]
        cases.append(dict(case='original-sync-completion-poll',status=word,synthetic_status=True,leaves_poll=target==0xc0be4c))
    with Path(upm_path).open('rb') as f:
        elf=ELFFile(f);assert elf['e_machine']=='EM_AARCH64'
        text=elf.get_section_by_name('.text').data()
    base=0x20000000;v=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    v.mem_map(base,(len(text)+4095)&~4095);v.mem_write(base,text)
    for page in (STACK,STOP,0xfffffffff1388000):v.mem_map(page,4096)
    target,ap_seen,ap_writes=0,[],[]
    def ap_boundary(cpu,address,size,user):
        if address==target:ap_seen.append(address);cpu.emu_stop()
    def ap_memory(cpu,access,address,size,value,user):
        if address>=0xfffffffff1388000:ap_writes.append((address,size,value))
    v.hook_add(UC_HOOK_CODE,ap_boundary);v.hook_add(UC_HOOK_MEM_WRITE,ap_memory)
    def ap_run(entry,end,inputs=()):
        nonlocal target
        target=base+end;ap_seen.clear();ap_writes.clear()
        v.reg_write(A.UC_ARM64_REG_SP,STACK+0xf00);v.reg_write(A.UC_ARM64_REG_X29,STACK+0xf00)
        for reg,value in inputs:v.reg_write(reg,value)
        v.emu_start(base+entry,0xffffffffffffffff,count=100)
        assert ap_seen==[target] and v.reg_read(A.UC_ARM64_REG_PC)==target,'Missing original AP boundary'
        return list(ap_writes)
    assert ap_run(0xaff0,0xb004)==[(0xfffffffff1388f54,4,0x101)]
    cases.append(dict(case='original-AP-register-init',kernel_VA='fffffffff1388f54',semaphore_calls_executed=False))
    assert ap_run(0xb058,0xb074)==[(0xfffffffff1388f50,4,0x101)]
    cases.append(dict(case='original-AP-pre-request-write',semaphore_calls_executed=False))
    actual=ap_run(0xb090,0xb0c0,((A.UC_ARM64_REG_W20,4),(A.UC_ARM64_REG_W21,1)))
    assert actual==[(0xfffffffff1388f5c,4,0x104),(0xfffffffff1388f58,4,1)]
    cases.append(dict(case='original-AP-request-encoding',mode=1,frequency_token=4,explicit_slice_inputs=True))
    return dict(camera_io=False,CP_sha256=hashlib.sha256(cp).hexdigest(),UPM_sha256=UPM_SHA,cases=cases,
        CP_register_sequence=dict(pre_write='f1388f48:101',init_write='f1388f4c:101',start='f1388f50:1',command='f1388f54',status='f1388f58'),
        AP_kernel_VA_sequence=dict(pre_write='fffffffff1388f50:101',init_write='fffffffff1388f54:101',start='fffffffff1388f58:1',command='fffffffff1388f5c',status='fffffffff1388f60'),
        limits=['Register roles and model completion behavior remain inferred; no clock tree or silicon timing',
                'Separate CP/AP register views do not establish shared physical wiring',
                'Post-service/flag/status words are explicit slice inputs; external calls are not executed',
                'No native peer/capture/save/cancel or camera restoration is tested'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp',type=Path,required=True);parser.add_argument('--upm',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();report=audit(args.cp.read_bytes(),args.upm)
    with args.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print(f"{len(report['cases'])} original DFS register/guard/poll contracts passed; no hardware transition supplied")


if __name__=='__main__':main()
