"""Child setup UNIT MODELS. Syscall results are explicit inputs, not real OS evidence.

No camera, process creation, original-kernel API execution or firmware output.
The generated ELF has no loader/init entry and must never be uploaded directly.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from unicorn import UC_HOOK_CODE
from unicorn import arm64_const as R
from support.build import compile_shared
from support.elf import codegen_flags, image_loader
from support.memory import MEM, STACK, STOP
from support.aarch64_abi import open_flags

SYSCALL=0x21000000
WORKSPACE=0x31000000
STATE=MEM
IMAGE=MEM+0x200
NONCE=0x726e3101
NAME='/tmp/jiritsu/private-selftest.elf'


def dirent(name):
    text=name.encode()+b'\0';size=(19+len(text)+7)&~7
    return struct.pack('<QQHB',1,0,size,0)+text+bytes(size-19-len(text))


def decode(raw):
    v=struct.unpack('<8I7q',raw)
    return dict(magic=v[0],version=v[1],step=v[2],consumed=v[3],nonce=v[4],closed_fds=v[5],
        directory_reads=v[6],exec_attempts=v[7],directory_descriptor=v[8],directory_close_status=v[9],
        failed_descriptor=v[10],enumeration_status=v[11],execveat_status=v[12],execve_status=v[13],return_status=v[14])


def model(elf,kind,abi):
    u,symbols=image_loader(elf,'aarch64',('precapture_child_exec_once',))
    u.mem_map(SYSCALL,4096);u.mem_map(WORKSPACE,4096)
    u.mem_write(STATE,bytes(88));u.mem_write(IMAGE,NAME.encode()+b'\0')
    if kind=='used-result':u.mem_write(STATE+84,b'\1')
    initial=bytes(u.mem_read(STATE,88));calls=[];closed=[];execs=[];read=0;transition=[]
    keep=0 if kind=='exec-fd-zero' else 22;directory=23
    payload=b''.join(dirent(n) for n in ('.','..','0','1','2','20',str(keep),str(directory)))
    if kind=='exec-fd-zero':payload=b''.join(dirent(n) for n in ('.','..','0','1','2','20','23'))
    if kind=='bad-record-size':payload=payload[:16]+b'\0\0'+payload[18:]
    elif kind=='unterminated-name':payload=struct.pack('<QQHB',1,0,24,0)+b'11111'
    elif kind=='short-record':payload=b'x'*23
    elif kind=='odd-record-size':payload=payload[:16]+b'\x19\0'+payload[18:]
    elif kind=='record-overrun':payload=struct.pack('<QQHB',1,0,64,0)+b'0\0'+bytes(3)
    elif kind=='large-nonnumeric-name':payload=dirent('99999999999')+dirent('foo')+dirent(str(keep))+dirent(str(directory))
    def text(p):return bytes(u.mem_read(p,160)).split(b'\0',1)[0].decode()
    def argv(p):
        values=struct.unpack('<4Q',bytes(u.mem_read(p,32)));assert values[3]==0
        return [text(x) for x in values[:3]]
    def ret(value):
        for i in range(1,18):u.reg_write(getattr(R,f'UC_ARM64_REG_X{i}'),0xde000000+i)
        u.reg_write(R.UC_ARM64_REG_X0,value&((1<<64)-1));u.reg_write(R.UC_ARM64_REG_PC,u.reg_read(R.UC_ARM64_REG_LR))
    def trap(cpu,at,size,_):
        nonlocal read
        if at!=SYSCALL:return
        regs=[u.reg_read(getattr(R,f'UC_ARM64_REG_X{i}')) for i in range(7)]
        nr=regs[0];v=regs[1:];calls.append(nr)
        assert nr in (56,61,57,281,221),('forbidden syscall',nr)
        if nr==56:
            assert text(v[1])=='/proc/self/fd' and v[0]==(-100&((1<<64)-1)) and v[2:]==[abi['directory_flags'],0,0,0]
            ret(-22 if kind=='directory-open-EINVAL' else -13 if kind=='directory-open-denied' else directory)
        elif nr==61:
            assert v[0]==directory and v[2:]==[4096,0,0,0];read+=1
            if kind in ('directory-read-EINVAL','read-and-close-error'):ret(-22)
            elif kind=='oversized-read':ret(4097)
            elif kind=='directory-budget':u.mem_write(v[1],dirent(str(keep)));ret(len(dirent(str(keep))))
            elif read==1:u.mem_write(v[1],payload);ret(len(payload))
            else:ret(0)
        elif nr==57:
            fd=v[0];assert v[1:]==[0,0,0,0,0] and fd!=keep and fd not in closed
            closed.append(fd)
            ret(1 if kind=='descriptor-close-positive' and fd!=directory else
                -4 if kind=='descriptor-close-EINTR' and fd!=directory else
                -5 if kind in ('directory-close-error','read-and-close-error') and fd==directory else 0)
        elif nr in (281,221):
            assert directory in closed and len(execs)<2
            execs.append(nr)
            if nr==281:
                assert v[0]==keep and text(v[1])=='' and v[4:]==[0x1000,0]
                arguments=argv(v[2]);environment=v[3]
            else:
                assert kind in ('fallback-transition','fallback-error') and text(v[0])==f'/proc/self/fd/{keep}'
                arguments=argv(v[1]);environment=v[2];assert v[3:]==[0,0,0]
            state=decode(bytes(u.mem_read(STATE,88)))
            assert arguments==[NAME,f'{NONCE:08x}',f"{state['closed_fds']:08x}"]
            assert bytes(u.mem_read(environment,8))==bytes(8)
            if kind in ('exec-transition','exec-fd-zero','large-nonnumeric-name') or (kind=='fallback-transition' and nr==221):
                transition.append(nr);u.emu_stop();return
            if kind in ('fallback-transition','fallback-error') and nr==281:ret(-38)
            else:ret(-22 if kind=='exec-EINVAL' else -13 if kind=='exec-denied' else -5 if nr==221 else 0)
    u.hook_add(UC_HOOK_CODE,trap)
    def run():
        for reg,value in ((R.UC_ARM64_REG_X0,-1 if kind=='negative-fd' else keep),
            (R.UC_ARM64_REG_X1,0 if kind=='zero-nonce' else NONCE),(R.UC_ARM64_REG_X2,0 if kind=='null-name' else IMAGE),
            (R.UC_ARM64_REG_X3,0 if kind=='null-result' else STATE),
            (R.UC_ARM64_REG_X4,0 if kind=='null-workspace' else STATE if kind=='overlap-workspace' else WORKSPACE),
            (R.UC_ARM64_REG_X5,0 if kind=='null-syscall' else SYSCALL),
            (R.UC_ARM64_REG_SP,STACK+0x3000),(R.UC_ARM64_REG_LR,STOP)):
            u.reg_write(reg,value&((1<<64)-1))
        u.emu_start(symbols['precapture_child_exec_once'],STOP,count=500000)
        return u.reg_read(R.UC_ARM64_REG_X0)&((1<<64)-1)
    status=run();raw=bytes(u.mem_read(STATE,88));r=decode(raw)
    if kind in ('negative-fd','zero-nonce','null-name','null-result','null-workspace','overlap-workspace','null-syscall','used-result'):
        expected=-16 if kind=='used-result' else -22
        assert status==expected&((1<<64)-1) and not calls and raw==initial
        return dict(case=kind,syscalls=[],result_untouched=True,real_process=False)
    if transition:
        assert r['step']==(7 if kind=='fallback-transition' else 6)
        assert r['return_status']==-1 and r['exec_attempts']==len(execs)
        return dict(case=kind,syscalls=calls,modeled_exec_transition=True,real_process=False)
    assert u.reg_read(R.UC_ARM64_REG_PC)==STOP and r['return_status']<0
    expected={
        'directory-open-EINVAL':(1,-22),'directory-open-denied':(1,-13),
        'directory-read-EINVAL':(2,-22),'read-and-close-error':(2,-22),'oversized-read':(2,-5),'directory-budget':(3,-75),
        'bad-record-size':(3,-74),'unterminated-name':(3,-74),'short-record':(3,-74),
        'odd-record-size':(3,-74),'record-overrun':(3,-74),'descriptor-close-EINTR':(4,-4),'descriptor-close-positive':(4,-5),
        'directory-close-error':(5,-5),'exec-EINVAL':(6,-22),'exec-denied':(6,-13),
        'fallback-error':(7,-5),'unexpected-exec-return':(6,-5)}[kind]
    assert (r['step'],r['return_status'])==expected,(kind,r)
    assert status==expected[1]&((1<<64)-1)
    if kind=='read-and-close-error':
        assert r['enumeration_status']==-22 and r['directory_close_status']==-5
    if kind in ('directory-open-EINVAL','directory-open-denied'):
        assert r['directory_reads']==0 and 57 not in calls
    if kind=='exec-EINVAL':assert execs==[281] and 221 not in calls
    if r['step']<6:assert not execs
    old=list(calls);assert run()==(-16&((1<<64)-1)) and calls==old and bytes(u.mem_read(STATE,88))==raw
    return dict(case=kind,syscalls=calls,failed_step=r['step'],status=r['return_status'],repeat_rejected=True,real_process=False)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--zig',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    elf=a.output/'NOT-INSTALLABLE-child-exec.elf';source=Path(__file__).with_name('ap_child_exec.c')
    compile_shared(a.zig, 'aarch64', elf,
        [source])
    kinds=('exec-transition','fallback-transition','exec-fd-zero','large-nonnumeric-name',
        'negative-fd','zero-nonce','null-name','null-result','null-workspace','overlap-workspace','null-syscall','used-result',
        'directory-open-EINVAL','directory-open-denied','directory-read-EINVAL','oversized-read','directory-budget',
        'bad-record-size','unterminated-name','short-record','odd-record-size','record-overrun',
        'descriptor-close-EINTR','descriptor-close-positive','directory-close-error','read-and-close-error',
        'exec-EINVAL','exec-denied','fallback-error','unexpected-exec-return')
    abi=open_flags(a.zig,a.output/'target-abi')
    wrong=a.output/'wrong-host-flags';wrong.mkdir()
    production=source.with_name('ap_linux_aarch64.h').read_text()
    poisoned=production.replace('AP_A64_O_DIRECTORY=0x4000','AP_A64_O_DIRECTORY=0x10000')
    assert poisoned!=production
    (wrong/'ap_linux_aarch64.h').write_text(poisoned)
    try:open_flags(a.zig,a.output/'rejected-host-abi',header_directory=wrong)
    except RuntimeError as error:
        assert 'AArch64 directory ABI' in str(error),str(error)
    else:raise AssertionError('Target headers must reject host/x86 directory flags')
    cases=[model(elf,k,abi) for k in kinds]
    report=dict(schema='OFFLINE_CHILD_EXEC_UNIT_MODELS/2',camera_io=False,cases=cases,target_open_flags=abi,
        independent_target_static_assert_rejects_host_flags=True,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),ELF_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(),
        limits=['Explicit syscall models, not real open/getdents/close/exec evidence',
                'Caller must already be isolated child with byte-verified executable FD',
                'No parent launcher, durable result writer, live adapter or hardware guarantee',
                'Existing EINVAL observation cannot identify a failed step retroactively'])
    (a.output/'models.private.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f'Child-only setup: {len(cases)} explicit syscall/evidence models; no camera or process execution.')
if __name__=='__main__':main()
