"""Compile/test the non-installable release-owner observation protocol.

Private originals, synthetic native objects, independent task-query metadata.
No USB or firmware output; no RTOS query/post or sensor success is simulated.
The command is not installed/sent; this standalone test excludes the S1 integration.
"""
import argparse
import hashlib
import json
import struct
import subprocess
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R8, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from unicorn.arm_const import UC_ARM_REG_R12, UC_ARM_REG_CPSR
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC
from audit_capture_transition import NativeCapture, BASE, OWNER, words
from verify_runtime_state import TAGS
from support.elf import image_loader, codegen_flags
from support.memory import MEM, STACK, STOP

ROOT, TASK, QUERY, POST = 0x1a2332c, 0x1a2361c, 0x5f1f24, 0x4b5fe4
PACKET, ARGS, REPLY = MEM + 0x100, MEM + 0x200, MEM + 0x300
NAMES = ('precapture_release_query_build', 'precapture_release_query_parse',
         'precapture_release_observe', 'precapture_release_task_valid')


def native_objects(cp):
    n = NativeCapture(cp)
    n.u.mem_map(ROOT & ~4095, 4096)
    n.run(0x9da0d6, (0x515be0,), [(UC_ARM_REG_SP, STACK+0x8000), (UC_ARM_REG_LR, STOP|1)])
    n.run(0x9da0fe, ())
    # Separate original post-configuration pointer binding. No omitted
    # configuration call or its return value is made successful.
    n.run(0x9d94be, (0x9d9556,), [(UC_ARM_REG_R4, ROOT),
        (UC_ARM_REG_R8, ROOT+0x2ac), (UC_ARM_REG_SP, STACK+0x8000)])
    raw = bytes(n.u.mem_read(ROOT, 0x310))
    assert struct.unpack_from('<I',raw,0x2f8)[0] == 0x4590f9
    return raw


def query_return_abi(cp):
    # Check the native zero-success / -25 error contract without executing
    # MRC, IRQ masking, RTOS state access or a task query itself.
    md = Cs(CS_ARCH_ARM,CS_MODE_ARM)
    for at,mn,ops in ((0x4e9fa4,'str','r1, [r0]'),(0x4e9fa8,'mov','r1, #0'),
                       (0x4e9fb8,'mov','r0, r1'),(0x4e9fbc,'bx','lr')):
        i=next(md.disasm(cp[at:at+4],at))
        assert (i.mnemonic,i.op_str)==(mn,ops)
    u=Uc(UC_ARCH_ARM,UC_MODE_ARM)
    for at in (BASE+0x4e9000,MEM,STOP):u.mem_map(at,4096)
    u.mem_write(BASE+0x4e9000,cp[0x4e9000:0x4ea000])
    stops=set()
    def boundary(cpu,at,size,user):
        if at in stops:cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE,boundary)
    cases=[]
    for task in (1,0x6f,0x88,0xa1):
        u.mem_write(MEM,words(0))
        u.reg_write(UC_ARM_REG_R0,MEM);u.reg_write(UC_ARM_REG_R1,task-1)
        stops.clear();stops.add(BASE+0x4e9fac)
        u.emu_start(BASE+0x4e9fa0,0xffffffff,count=4)
        assert u.reg_read(UC_ARM_REG_PC)==BASE+0x4e9fac
        assert bytes(u.mem_read(MEM,4))==words(task)
        u.reg_write(UC_ARM_REG_LR,STOP);stops.clear()
        u.emu_start(BASE+0x4e9fb8,STOP,count=3)
        assert u.reg_read(UC_ARM_REG_PC)==STOP and u.reg_read(UC_ARM_REG_R0)==0
        cases.append(dict(kind='post-id-arithmetic-and-return-only',task=task,status=0))
    u.mem_write(MEM,words(0xa5a5a5a5));u.reg_write(UC_ARM_REG_R3,1)
    u.reg_write(UC_ARM_REG_R0,MEM);u.reg_write(UC_ARM_REG_LR,STOP)
    u.emu_start(BASE+0x4e9f4c,STOP,count=8)
    assert u.reg_read(UC_ARM_REG_PC)==STOP and u.reg_read(UC_ARM_REG_R0)==0xffffffe7
    assert bytes(u.mem_read(MEM,4))==words(0xa5a5a5a5)
    cases.append(dict(kind='post-IRQ-restore-error-slice',status=-25))
    return cases


def check(elf,arch,cp,raw):
    names=NAMES + (('precapture_release_query_dispatch','precapture_release_after_query',
        'precapture_release_native_message','precapture_hook_release','precapture_release_hook_after') if arch=='thumb' else ())
    u,sym=image_loader(elf,arch,names)
    u.mem_map(ROOT & ~4095,4096)
    regs=(UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3) if arch=='thumb' else (UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2,UC_ARM64_REG_X3)
    sp,lr,pc=(UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC) if arch=='thumb' else (UC_ARM64_REG_SP,UC_ARM64_REG_LR,UC_ARM64_REG_PC)
    stops={STOP};seen=[]
    def boundary(cpu,at,size,user):
        if at in stops:
            seen.append(dict(at=at,args=[cpu.reg_read(r) for r in regs]));cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE,boundary)
    def run(name,args,targets=(STOP,)):
        stops.clear();stops.update(targets);seen.clear()
        for reg,value in zip(regs,args):u.reg_write(reg,value & ((1<<64)-1))
        u.reg_write(sp,STACK+0x3000);u.reg_write(lr,STOP|int(arch=='thumb'))
        u.emu_start(sym[name],0xffffffffffffffff if arch=='aarch64' else 0xffffffff,count=15000)
        assert len(seen)==1 and u.reg_read(pc)==seen[0]['at']
        return seen[0]
    cases=[]
    def root(mutations=()):
        r=bytearray(raw);struct.pack_into('<I',r,0x2a0,4)
        for at,data in mutations:r[at:at+len(data)]=data
        u.mem_write(ROOT,bytes(r));return bytes(r)
    for generation,desired in ((1,0),(1,1),(7,1),(0xffffffff,0)):
        u.mem_write(PACKET,b'\xa5'*64)
        result=run(NAMES[0],[generation,desired,PACKET,16])
        expect=struct.pack('<BBH3I',5,0,0x40f0,generation,desired,0x50435231)
        assert result['args'][0]==16 and bytes(u.mem_read(PACKET,64))==expect+b'\xa5'*48
        u.mem_write(ARGS,b'\xa5'*16)
        result=run(NAMES[1],[PACKET,16,0x90030001,ARGS])
        assert result['args'][0]==1 and bytes(u.mem_read(ARGS,16))==words(generation,desired)+b'\xa5'*8
        cases.append(dict(kind='query-encode-parse',generation=generation,desired=desired))
    for generation,desired,capacity in ((0,0,16),(1,2,16),(0xffffffff,1,16),(1,1,15)):
        u.mem_write(PACKET,b'\xa5'*64)
        assert run(NAMES[0],[generation,desired,PACKET,capacity])['args'][0]&0xffffffff==0xffffffea
        assert bytes(u.mem_read(PACKET,64))==b'\xa5'*64
        cases.append(dict(kind='invalid-query-build',generation=generation,desired=desired,capacity=capacity))
    base=struct.pack('<BBH3I',5,0,0x40f0,7,1,0x50435231)
    for label,packet,length,origin,out,want in (
        ('ordinary',struct.pack('<BBH3I',5,0,0x403d,0,4,1),16,0x90030001,ARGS,0),
        ('short',base,3,0x90030001,ARGS,-22),('truncated-private',base,15,0x90030001,ARGS,-22),
        ('oversized-private',base,17,0x90030001,ARGS,-22),('origin',base,16,0x80020002,ARGS,-22),
        ('group',b'\0'+base[1:],16,0x90030001,ARGS,-22),('flags',base[:1]+b'\1'+base[2:],16,0x90030001,ARGS,-22),
        ('cookie',base[:12]+words(0),16,0x90030001,ARGS,-22),
        ('zero-gen',base[:4]+words(0)+base[8:],16,0x90030001,ARGS,-22),
        ('desired',base[:8]+words(2)+base[12:],16,0x90030001,ARGS,-22),
        ('alias',base,16,0x90030001,PACKET+4,-22),('unaligned-output',base,16,0x90030001,ARGS+1,-22)):
        u.mem_write(PACKET,packet+b'\xa5'*32);u.mem_write(ARGS,b'\xa5'*16)
        before=bytes(u.mem_read(PACKET,48))
        assert run(NAMES[1],[PACKET,length,origin,out])['args'][0]&0xffffffff==want&0xffffffff
        assert bytes(u.mem_read(PACKET,48))==before and bytes(u.mem_read(ARGS,16))==b'\xa5'*16
        cases.append(dict(kind='query-parse-reject-or-forward',case=label))
    variants=[('idle',[],0),('lost-reason',[(0x2a0,words(0))],-116),
        ('other-reasons',[(0x2a0,words(0x4000004))],0),
        ('selected',[(0x288,words(13))],-16),('bad-selection',[(0x288,words(14))],-22),
        ('active',[(0x290,b'\1')],-16),('requested',[(0x291,b'\1')],-16),
        ('bad-active',[(0x290,b'\2')],-22),('bad-requested',[(0x291,b'\2')],-22),
        ('pending-other-reply',[(0x294,words(0xabcdef))],-16)]
    for at in (0,4,8,12,0x158,0x15c,0x278,0x27c,0x280,0x284,0x298):
        variants.append((f'anchor-{at:x}',[(at,words(0))],-95))
    for index in (1,3,13):
        for flag,want in ((1,-16),(2,-22)):
            variants.append((f'request-{index}-{flag}',[(0x158+0x14+index*16,bytes([flag]))],want))
    for label,mutations,want in variants:
        native=root(mutations);u.mem_write(REPLY,b'\xa5'*48)
        result=run(NAMES[2],[ROOT,7,1,REPLY])
        assert result['args'][0]&0xffffffff==want&0xffffffff,(arch,label,result)
        wire=bytes(u.mem_read(REPLY,32));reason=struct.unpack_from('<I',native,0x2a0)[0] if want!=-95 else 0
        assert wire==words(0,0x8240,7,5,1,0x50435231,want&0xffffffff,reason)
        assert bytes(u.mem_read(REPLY+32,16))==b'\xa5'*16
        assert bytes(u.mem_read(ROOT,0x310))==native
        cases.append(dict(kind='native-owner-observation',case=label,status=want))
    for pointer,generation,desired,out in ((ROOT+1,7,1,REPLY),(0,7,1,REPLY),
        (ROOT,0,1,REPLY),(ROOT,7,2,REPLY),(ROOT,0xffffffff,1,REPLY),
        (ROOT,7,1,REPLY+1),(ROOT,7,1,ROOT+0x2f0),(ROOT,7,1,0)):
        native=root();u.mem_write(REPLY,b'\xa5'*48)
        assert run(NAMES[2],[pointer,generation,desired,out])['args'][0]&0xffffffff==0xffffffea
        assert bytes(u.mem_read(ROOT,0x310))==native and bytes(u.mem_read(REPLY,48))==b'\xa5'*48
        cases.append(dict(kind='invalid-observer-input',root=hex(pointer),generation=generation,desired=desired))
    for task,status in ((0x6f,0),(0,0),(0x88,0),(0x6f,-25),(0x6f,1)):
        want=0 if task==0x6f and not status else -1
        assert run(NAMES[3],[task,status])['args'][0]&0xffffffff==want&0xffffffff
        cases.append(dict(kind='explicit-query-metadata-predicate',task=task,status=status))
    native=[]
    if arch=='thumb':
        for start in (QUERY,POST,BASE+0x351000,BASE+0xae4000,BASE+0x45d000):
            page=start&~4095;u.mem_map(page,4096);u.mem_write(page,cp[page-BASE:page-BASE+4096])
        root();u.mem_write(PACKET,base)
        result=run('precapture_release_query_dispatch',[PACKET,16,0x90030001],(QUERY,))
        assert bytes(u.mem_read(result['args'][0],4))==words(0)
        native.append(dict(kind='real-query-entry-not-executed',address=hex(QUERY),output_initialized_zero=True))
        for at,value in ((0,0),(8,0),(0x14,0x88)):
            original=root();u.mem_write(TASK+at,words(value));before=bytes(u.mem_read(ROOT,0x310))
            result=run('precapture_release_query_dispatch',[PACKET,16,0x90030001],(STOP,QUERY,POST))
            assert result['at']==STOP and result['args'][0]&0xffffffff==0xffffffa1
            assert bytes(u.mem_read(ROOT,0x310))==before
            native.append(dict(kind='wrong-task-object-before-query',offset=at))
        for generation,desired in ((0,1),(1,2),(0xffffffff,1)):
            original=root()
            result=run('precapture_release_after_query',[generation,desired,0x6f,0],(STOP,POST))
            assert result['at']==STOP and result['args'][0]&0xffffffff==0xffffffea
            assert bytes(u.mem_read(ROOT,0x310))==original
            native.append(dict(kind='bad-frozen-arguments-no-post',generation=generation,desired=desired))
        for tid,status in ((0,0),(0x88,0),(0x6f,-25),(0x6f,1)):
            result=run('precapture_release_after_query',[7,1,tid,status],(STOP,POST))
            assert result['at']==STOP and result['args'][0]&0xffffffff==0xffffffff
            native.append(dict(kind='independent-after-query-refusal',task=tid,status=status))
        for label,mutations,want in variants[:10]:
            original=root(mutations)
            result=run('precapture_release_after_query',[7,1,0x6f,0],(POST,))
            assert result['args'][0:2]==[0x1a52b34,0x900302d9] and result['args'][3]==32
            wire=bytes(u.mem_read(result['args'][2],32))
            assert struct.unpack_from('<I',wire,24)[0]==want&0xffffffff
            assert bytes(u.mem_read(ROOT,0x310))==original
            native.append(dict(kind='independent-after-query-to-post-boundary',case=label,status=want,OS_post_executed=False))
        from keystone import Ks,KS_ARCH_ARM,KS_MODE_THUMB
        ks=Ks(KS_ARCH_ARM,KS_MODE_THUMB)
        site,continuation,free=BASE+0x35113a,BASE+0x35113e,BASE+0x45d300
        assert cp[0x35113a:0x35113e]==bytes(ks.asm('bl 0xbec02a',addr=site)[0])
        patch=bytes(ks.asm(f"bl {sym['precapture_hook_release']&~1:#x}",addr=site)[0])
        assert len(patch)==4
        u.mem_write(site,patch)  # Emulator memory only; original file unchanged.
        message=MEM+0x600;loop_sp=STACK+0x3000
        def frame(payload,origin=0x90030001):
            u.mem_write(message-24,b'\xa5'*88)
            u.mem_write(message-12,words(origin,len(payload)))
            u.mem_write(message,payload)
            u.mem_write(loop_sp,words(message))
        def loop(targets):
            stops.clear();stops.update(targets);seen.clear()
            u.reg_write(UC_ARM_REG_SP,loop_sp);u.reg_write(UC_ARM_REG_R4,0x90040193)
            u.reg_write(UC_ARM_REG_CPSR,(u.reg_read(UC_ARM_REG_CPSR)&~0xf8000000)|0xa8000000)
            for reg,value in ((UC_ARM_REG_R1,0x11111111),(UC_ARM_REG_R2,0x22222222),
                (UC_ARM_REG_R3,0x33333333),(UC_ARM_REG_R12,0xcccccccc)):
                u.reg_write(reg,value)
            u.emu_start((BASE+0x351138)|1,0xffffffff,count=15000)
            assert len(seen)==1 and u.reg_read(UC_ARM_REG_PC)==seen[0]['at']
            return seen[0]
        for label,payload,origin,task_bad,want in (
            ('ordinary',struct.pack('<BBH3I',5,0,0x403d,0,4,1),0x90030001,False,continuation),
            ('private-origin',base,0x80020002,False,free),
            ('private-cookie',base[:12]+words(0),0x90030001,False,free),
            ('private-short',base[:15],0x90030001,False,free),
            ('private-task',base,0x90030001,True,free),
            ('private-valid-to-query',base,0x90030001,False,QUERY)):
            original=root()
            if task_bad:u.mem_write(TASK+0x14,words(0x88))
            before=bytes(u.mem_read(ROOT,0x310));frame(payload,origin)
            raw_before=bytes(u.mem_read(message-24,88))
            got=loop((continuation,free,QUERY,POST))
            assert got['at']==want,(label,got)
            assert bytes(u.mem_read(ROOT,0x310))==before
            assert bytes(u.mem_read(message-24,88))==raw_before
            if want==free:assert got['args'][:2]==[0x90040193,message]
            if want==continuation:assert got['args'][0]==origin
            if want!=QUERY:
                assert u.reg_read(UC_ARM_REG_SP)==loop_sp
                assert u.reg_read(UC_ARM_REG_CPSR)&0xf8000000==0xa8000000
                assert u.reg_read(UC_ARM_REG_R12)==0xcccccccc
                assert got['args'][2:]==[0x22222222,0x33333333]
                if want==continuation:assert got['args'][1]==0x11111111
            native.append(dict(kind='actual-CAP-loop-hook-to-boundary',case=label,
                boundary=hex(want),native_free_or_query_or_post_executed=False))
        # Separate wrapper-return slices: only this adapter's return routing
        # is tested. No C handler/RTOS operation is replaced with success.
        for value in (0,1,-5,-22,-95):
            root();frame(base)
            loop((sym['precapture_release_native_message']&~1,))
            stops.clear();stops.update((continuation,free));seen.clear()
            for reg in (UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_R12):u.reg_write(reg,0xdeadbeef)
            u.reg_write(UC_ARM_REG_R0,value&0xffffffff)
            u.emu_start(sym['precapture_release_hook_after'],0xffffffff,count=100)
            assert len(seen)==1 and seen[0]['at']==(continuation if value==0 else free)
            assert u.reg_read(UC_ARM_REG_SP)==loop_sp
            assert u.reg_read(UC_ARM_REG_CPSR)&0xf8000000==0xa8000000
            assert u.reg_read(UC_ARM_REG_R12)==0xcccccccc
            assert seen[0]['args'][2:]==[0x22222222,0x33333333]
            if value:assert seen[0]['args'][:2]==[0x90040193,message]
            native.append(dict(kind='independent-post-handler-routing-slice',explicit_result=value,
                native_free_executed=False,original_free_boundary_reached_once=value!=0))
    return dict(pure_cases=cases,native_slices=native)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp',type=Path,required=True);p.add_argument('--zig',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();cp=a.cp.read_bytes();digest=hashlib.sha256(cp).hexdigest()
    if digest not in TAGS:raise ValueError('Unsupported complete CP source')
    a.output.mkdir(parents=True,exist_ok=False);raw=native_objects(cp);result={}
    for arch,target in (('thumb','thumb-linux-gnueabi'),('aarch64','aarch64-linux-gnu')):
        elf=a.output/f'{arch}-release-observer.elf';sources=['cp_release_observer.c']+(['cp_release_binding.c','cp_release_hook.S'] if arch=='thumb' else [])
        cmd=[str(a.zig),'cc','-target',target,*codegen_flags(arch),'-Oz','-g','-shared','-fPIC','-ffreestanding','-fno-builtin','-fno-stack-protector','-fno-unwind-tables','-fno-asynchronous-unwind-tables','-nostdlib','-Wl,--no-undefined,-Bsymbolic','-o',str(elf),*[str(Path(__file__).with_name(n)) for n in sources]]
        built=subprocess.run(cmd,capture_output=True,text=True,timeout=120)
        if built.returncode:raise RuntimeError(built.stderr[-3000:])
        result[arch]=check(elf,arch,cp,raw)
    report=dict(schema='OFFLINE_RELEASE_OWNER_OBSERVER/1',camera_io=False,cp_sha256=digest,
        proposed_query_command='0x40f0',observation_phase=5,CAP_hook_executed_in_emulator=True,
        S1_phase5_consumer_integrated=False,
        architectures=result,native_query_return_abi_slices=query_return_abi(cp),
        limits=['No CAP queue hook or S1 backend integration installed',
            '40f0 is a proposed unsupported-on-stock private command; do not send it',
            'No RTOS query, IPC send/receive, cancellation release or image operation succeeds in this test',
            'A matched owner observation does not establish sensor/terminal-frame quiescence',
            'Legacy ABI3 rejects phase5; matched ABI4 integration is verified separately',
            'Existing96-byte state/4KiB code storage and startup remain unmodified/unproven'])
    with (a.output/'release-observer.private.json').open('x') as f:json.dump(report,f,indent=2)
    print(json.dumps(dict(status='OFFLINE_OBSERVER_ONLY',pure_cases={k:len(v['pure_cases']) for k,v in result.items()},native_slices={k:len(v['native_slices']) for k,v in result.items()},native_query_abi_slices=len(report['native_query_return_abi_slices']))))


if __name__=='__main__':main()
