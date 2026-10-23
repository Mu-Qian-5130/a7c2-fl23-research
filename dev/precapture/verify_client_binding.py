"""Generated isolated-child binding models; no process/scheduling/device API runs."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from unicorn import UC_HOOK_CODE
from unicorn import arm64_const as R
from support.aarch64_abi import client_binding_abi
from support.build import compile_shared
from support.elf import image_loader
from support.memory import MEM,STACK,STOP

CALL=0x21000000
CATCHABLE=((1<<64)-1)^((1<<8)|(1<<18))


def state(raw):
    v=struct.unpack('<8I6q6Q2I3q',raw)
    return dict(magic=v[0],version=v[1],phase=v[2],ownership=v[3],expected_parent=v[4],CPU=v[5],
        enter_calls=v[6],leave_calls=v[7],pid=v[8],parent=v[9],policy_before=v[10],priority_before=v[11],
        policy_after=v[12],priority_after=v[13],affinity_before=v[14],affinity_after=v[15],affinity_restored=v[16],
        signals_before=v[17],signals_after=v[18],signals_restored=v[19],observed_CPU=v[20],
        reserved=v[21],last_result=v[22],enter_status=v[23],leave_status=v[24])


def model(elf,kind):
    u,symbols=image_loader(elf,'aarch64',('precapture_client_bind_once','precapture_client_unbind_once'))
    u.mem_map(CALL,4096);u.mem_write(MEM,bytes(160))
    if kind=='used-state':u.mem_write(MEM+159,b'\1')
    mask=3 if kind=='CPU-unavailable' else 7
    original_mask=mask;signal_mask=0x10;original_signals=signal_mask
    calls=[];policy_reads=0;priority_reads=0;leave=False
    failure_index=int(kind.split('-')[-1]) if kind.startswith(('enter-fail-','leave-fail-')) else -1
    def return_value(value):
        u.reg_write(R.UC_ARM64_REG_X0,value&((1<<64)-1));u.reg_write(R.UC_ARM64_REG_PC,u.reg_read(R.UC_ARM64_REG_LR))
    def callback(cpu,at,size,_):
        nonlocal mask,signal_mask,policy_reads,priority_reads
        if at!=CALL:return
        args=[u.reg_read(getattr(R,f'UC_ARM64_REG_X{i}')) for i in range(7)]
        n,a,b,c,d,e,f=args
        assert n in (120,121,122,123,135,168,172,173) and not e and not f
        current=state(bytes(u.mem_read(MEM,160)))
        index=current['leave_calls'] if leave else current['enter_calls']
        calls.append(dict(syscall=n,leaving=leave,index=index))
        if (kind.startswith('enter-fail-') and not leave or kind.startswith('leave-fail-') and leave) and index==failure_index:
            return_value(-22);return
        if n==172:return_value(518 if kind=='same-as-parent' else 1353);return
        if n==173:return_value(519 if kind=='wrong-parent' else 518);return
        if n==120:
            assert a==0;policy_reads+=1
            return_value(1 if kind=='policy-before' or kind=='policy-drift' and policy_reads==2 else 0);return
        if n==121:
            assert a==0;priority_reads+=1
            u.mem_write(b,struct.pack('<i',1 if kind=='priority-before' or kind=='priority-drift' and priority_reads==2 else 0))
            return_value(0);return
        if n in (122,123):
            assert a==0 and b==8 and not d
            if n==122:
                requested=struct.unpack('<Q',bytes(u.mem_read(c,8)))[0]
                assert requested==(original_mask if leave else 4)
                mask=requested;return_value(0);return
            actual=mask^(1 if kind=='affinity-drift' and current['ownership']&2 else 0)
            u.mem_write(c,struct.pack('<Q',actual));return_value(8);return
        if n==135:
            assert a in (0,2) and d==8
            previous=signal_mask
            if b:
                requested=struct.unpack('<Q',bytes(u.mem_read(b,8)))[0]
                assert requested==(original_signals if leave else CATCHABLE)
                signal_mask=requested if a==2 else signal_mask|requested
            if c:
                actual=previous^(1 if kind=='signal-drift' and current['ownership']&1 else 0)
                u.mem_write(c,struct.pack('<Q',actual))
            return_value(0);return
        if n==168:
            assert not b and not c and not d
            u.mem_write(a,struct.pack('<I',1 if kind=='CPU-drift' else 2));return_value(0);return
    u.hook_add(UC_HOOK_CODE,callback)
    def invoke(name,arguments):
        for i,value in enumerate(arguments):u.reg_write(getattr(R,f'UC_ARM64_REG_X{i}'),value)
        u.reg_write(R.UC_ARM64_REG_SP,STACK+0x3000);u.reg_write(R.UC_ARM64_REG_LR,STOP)
        u.emu_start(symbols[name],STOP,count=50000)
        assert u.reg_read(R.UC_ARM64_REG_PC)==STOP
        return u.reg_read(R.UC_ARM64_REG_X0)&0xffffffff
    result=invoke('precapture_client_bind_once',(0 if kind=='null-state' else MEM,518,64 if kind=='invalid-CPU' else 2,CALL))
    bound=state(bytes(u.mem_read(MEM,160)))
    expected=kind=='normal' or kind.startswith('leave-fail-')
    assert (result==0)==expected,(kind,result,bound)
    if result:
        assert not any(row['leaving'] for row in calls)
        if kind in ('null-state','used-state','invalid-CPU'):assert not calls
        assert bound['ownership'] in (0,1,3)
        return dict(case=kind,status=result,phase=bound['phase'],ownership=bound['ownership'],calls=len(calls))
    assert bound['phase']==4 and bound['ownership']==3 and bound['enter_calls']==13
    assert mask==4 and signal_mask==CATCHABLE
    leave=True
    result=invoke('precapture_client_unbind_once',(MEM,CALL));ended=state(bytes(u.mem_read(MEM,160)))
    if kind.startswith('leave-fail-'):
        assert result and ended['phase']==9 and ended['ownership'] in (1,3)
    else:
        assert not result and ended['phase']==7 and not ended['ownership']
        assert ended['leave_calls']==4 and mask==original_mask and signal_mask==original_signals
        previous=len(calls)
        assert invoke('precapture_client_unbind_once',(MEM,CALL))==0xffffffea and len(calls)==previous
    return dict(case=kind,status=result,phase=ended['phase'],ownership=ended['ownership'],calls=len(calls))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zig',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(exist_ok=False)
    abi=client_binding_abi(args.zig,args.output/'target-ABI')
    source=Path(__file__).with_name('ap_client_binding.c');elf=args.output/'component.elf'
    compile_shared(args.zig,'aarch64',elf,[source])
    cases=[model(elf,name) for name in ('normal','null-state','used-state','invalid-CPU','same-as-parent','wrong-parent',
        'policy-before','priority-before','CPU-unavailable','affinity-drift','signal-drift','CPU-drift','policy-drift','priority-drift',
        *['enter-fail-'+str(i) for i in range(1,14)],*['leave-fail-'+str(i) for i in range(1,5)])]
    result=dict(camera_io=False,models_only=True,cases=cases,target_ABI=abi,
        source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (source,source.with_suffix('.h'),Path(__file__))},ELF_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(),
        physical_binding=False,CP_send=False,context_cleanup_or_native_lifetime_admission=False)
    with (args.output/'report.private.json').open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2)
    print(len(cases),'generated isolated-client bind/unbind models; target ABI verified; no native/camera operation')


if __name__=='__main__':main()
