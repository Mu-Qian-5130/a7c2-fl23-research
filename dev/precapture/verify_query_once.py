"""Tagged query-send ownership models, not actual allocation or CP delivery.

The header fixture executes independent original post-pool instructions with
non-A5 poison bytes. Every send removes the shared mapping before returning,
so any later payload/header access fails instead of looking harmless.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from unicorn import UC_HOOK_CODE
from unicorn import arm64_const as R
from support.build import compile_shared
from support.elf import image_loader
from support.memory import MEM,STACK,STOP
from support.uipc import original_header,LIBRARY_SHA
from support.kernel import UIPC_SHA

IOCTL,SHARED,SIZE=0x21000000,0x60000000,0x200000
MESSAGE=SHARED+0x1040
OWN_ID,NONCE=0x803f6111,0x12345678


def decode(raw):
    values=struct.unpack('<8I2qQ2I',raw)
    return dict(zip(('magic','version','phase','ownership','nonce','own_id','allocation_attempts',
        'send_attempts','allocation_status','send_status','message','header_verified','packet_written'),values))


def model(elf,header,spec):
    u,symbols=image_loader(elf,'aarch64',('precapture_query_once',));u.mem_map(IOCTL,4096)
    binding,result=MEM+0x100,MEM+0x200;kind=spec['name'];fields=[77,0,SHARED,SIZE]
    if kind=='descriptor-zero':fields[0]=0
    for i,v in spec.get('binding',{}).items():fields[i]=v
    if kind in ('result-in-shared','binding-in-shared'):
        u.mem_map(SHARED,4096)
        if kind=='result-in-shared':result=SHARED+0x200
        else:binding=SHARED+0x100
    if kind=='overlap-result':fields[0]=0;result=binding-56
    u.mem_write(binding,struct.pack('<iIQQ',*fields))
    if kind=='used-result':u.mem_write(result,b'\x01')
    initial=bytes(u.mem_read(result,64));initial_binding=bytes(u.mem_read(binding,24))
    calls=[];mapped=False;before=None
    message=spec.get('message',MESSAGE);nonce=spec.get('nonce',NONCE);own=spec.get('own_id',OWN_ID)
    def ret(value):
        for i in range(1,18):u.reg_write(getattr(R,f'UC_ARM64_REG_X{i}'),0xde000000+i)
        u.reg_write(R.UC_ARM64_REG_X0,value&((1<<64)-1));u.reg_write(R.UC_ARM64_REG_PC,u.reg_read(R.UC_ARM64_REG_LR))
    def hook(cpu,at,size,_):
        nonlocal mapped,before
        if at!=IOCTL:return
        fd,cmd,pointer=[u.reg_read(reg) for reg in (R.UC_ARM64_REG_X0,R.UC_ARM64_REG_X1,R.UC_ARM64_REG_X2)]
        assert fd==fields[0] and cmd in (0x8000000a,0x80000004),'No free/receive/sync/other operation is permitted'
        route,pad,arg=struct.unpack('<IIQ',bytes(u.mem_read(pointer,16)))
        assert route==0x90030001 and pad==0
        state=decode(bytes(u.mem_read(result,64)));calls.append(cmd)
        if cmd==0x8000000a:
            assert calls==[cmd] and state['phase']==1 and state['ownership']==3
            output,length,wait=struct.unpack('<QII',bytes(u.mem_read(arg,16)))
            assert (length,wait)==(12,0)
            allocation=spec.get('allocation_status',0)
            if not allocation and SHARED+64<=message<=SHARED+SIZE-64 and not(message&63):
                u.mem_map(SHARED,SIZE);mapped=True;u.mem_write(message-64,header)
                for offset,value in spec.get('bad_header',{}).items():
                    u.mem_write(message+offset,bytes([value]))
                before=bytes(u.mem_read(message-64,128))
            u.mem_write(output,struct.pack('<Q',message));ret(allocation)
        else:
            assert calls==[0x8000000a,cmd] and arg==message and mapped
            assert (state['phase'],state['ownership'],state['header_verified'],state['packet_written'])==(3,3,1,1)
            expected=bytearray(before)
            struct.pack_into('<I',expected,52,own)
            struct.pack_into('<3I',expected,64,0x41720005,nonce,0x31595251)
            assert bytes(u.mem_read(message-64,128))==bytes(expected),'Only source4 and payload12 may change'
            u.mem_unmap(SHARED,SIZE);mapped=False
            ret(spec.get('send_status',0))
    u.hook_add(UC_HOOK_CODE,hook)
    def run():
        for reg,value in ((R.UC_ARM64_REG_X0,0 if kind=='null-binding' else spec.get('binding_pointer',binding)),
            (R.UC_ARM64_REG_X1,0 if kind=='null-result' else spec.get('result_pointer',result)),
            (R.UC_ARM64_REG_X2,own),(R.UC_ARM64_REG_X3,nonce),
            (R.UC_ARM64_REG_X4,0 if kind=='null-invoke' else IOCTL),
            (R.UC_ARM64_REG_SP,STACK+0x3000),(R.UC_ARM64_REG_LR,STOP)):
            u.reg_write(reg,value)
        u.emu_start(symbols['precapture_query_once'],STOP,count=50000)
        assert u.reg_read(R.UC_ARM64_REG_PC)==STOP
        return u.reg_read(R.UC_ARM64_REG_X0)&0xffffffff
    status=run();raw=bytes(u.mem_read(result,64));state=decode(raw)
    if spec.get('invalid') or kind=='used-result':
        assert status==(-16 if kind=='used-result' else -22)&0xffffffff
        assert not calls and raw==initial and bytes(u.mem_read(binding,24))==initial_binding
        return dict(case=kind,rejected_before_ioctl=True,result_and_binding_untouched=True)
    assert status==spec['return']&0xffffffff and (state['phase'],state['ownership'])==spec['terminal']
    assert state['allocation_status']==spec.get('allocation_status',0)
    assert state['allocation_attempts']==1 and state['send_attempts']==(len(calls)==2)
    if len(calls)==1 and before is not None:
        assert bytes(u.mem_read(message-64,128))==before and state['packet_written']==0
    assert bytes(u.mem_read(binding,24))==initial_binding
    old=list(calls);assert run()==(-16&0xffffffff) and calls==old and bytes(u.mem_read(result,64))==raw
    return dict(case=kind,calls=[hex(c) for c in calls],phase=state['phase'],ownership=state['ownership'],
        reentry_rejected=True,post_send_access_or_free=False,native_operation=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('zig','uipc-kernel','uipc','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    native=a.uipc_kernel.read_bytes();library=a.uipc.read_bytes()
    header,_=original_header(native,library,12,initial_byte=0x3c)
    other,_=original_header(native,library,12,initial_byte=0x7e)
    # The constructor writes these bytes; they are not inherited A5 poison.
    for at,size in ((48,16),(76,4)):
        assert header[at:at+size]==other[at:at+size]
    assert header[52:56]==bytes.fromhex('a5a5a5a5') and struct.unpack_from('<I',header,56)[0]==12
    source=Path(__file__).with_name('ap_query_once.c');elf=a.output/'NOT-INSTALLABLE-tagged-query.elf'
    compile_shared(a.zig,'aarch64',elf,[source])
    specs=[dict(name='handoff',terminal=(4,2),**{'return':0}),
        dict(name='descriptor-zero',terminal=(4,2),**{'return':0}),
        dict(name='nonce-one',nonce=1,terminal=(4,2),**{'return':0}),
        dict(name='distinct-owned-ID',own_id=0x803f6001,terminal=(4,2),**{'return':0})]
    for status in (-22,-1021,-1023,-1024):
        specs.append(dict(name=f'allocation-rejected-{status}',allocation_status=status,message=0,terminal=(5,0),**{'return':-5}))
    for status in (-4,-5,1):
        specs.append(dict(name=f'allocation-unknown-{status}',allocation_status=status,message=0,terminal=(6,3),**{'return':-5}))
    specs.append(dict(name='allocation-error-with-pointer',allocation_status=-1023,terminal=(6,3),**{'return':-5}))
    for pointer in (0,SHARED+16,MESSAGE+1,SHARED+SIZE,(1<<64)-1):
        specs.append(dict(name=f'bad-pointer-{pointer:x}',message=pointer,terminal=(6,3),**{'return':-5}))
    for offset,value in ((-16,1),(-15,0),(-14,2),(-13,1),(-12,0),(-8,16),(-4,0),(12,0)):
        specs.append(dict(name=f'bad-header-{offset}',bad_header={offset:value},terminal=(6,3),**{'return':-5}))
    for status in (-22,-1021,-1024,-5,1,-4,-1023,2):
        specs.append(dict(name=f'send-unknown-{status}',send_status=status,terminal=(6,3),**{'return':-5}))
    for name in ('null-binding','null-result','null-invoke','overlap-result','result-in-shared','binding-in-shared'):
        specs.append(dict(name=name,invalid=True))
    for name,fields in (('negative-fd',{0:-1}),('reserved-binding',{1:1}),('zero-map',{2:0}),
            ('unaligned-map',{2:SHARED+1}),('bad-map-size',{3:4096}),('wrapped-map',{2:0xfffffffffff00000})):
        specs.append(dict(name=name,binding=fields,invalid=True))
    for value in (0,0x803f0000,0x803f8001,0x903f6111,0xffffffff):
        specs.append(dict(name=f'invalid-ID-{value:x}',own_id=value,invalid=True))
    specs.extend([dict(name='zero-nonce',nonce=0,invalid=True),
        dict(name='wrapped-result-pointer',result_pointer=(1<<64)-16,invalid=True),
        dict(name='wrapped-binding-pointer',binding_pointer=(1<<64)-8,invalid=True),dict(name='used-result')])
    cases=[model(elf,header,spec) for spec in specs]
    files=[source,source.with_suffix('.h'),source.with_name('ap_binding_guard.h'),
        source.with_name('ap_probe_once.h'),source.with_name('precapture_query_wire.h')]
    report=dict(schema='OFFLINE_TAGGED_QUERY_SEND_MODELS/1',camera_io=False,cases=cases,
        kernel_sha256=UIPC_SHA,library_sha256=LIBRARY_SHA,
        constructor_poison_independent=[0x3c,0x7e],ELF_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(),
        sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        limits=['Allocation/send results are explicit unit models, not actual IPC or CP receipt',
            'Original post-pool constructor runs independently; no allocator success is supplied',
            'The caller must prove fresh isolated context, own ID and live source/FD/map identity',
            'Successful handoff transfers ownership; no later payload/header read or free is permitted',
            'Unknown/native-call-in-progress states require a durable outer process/context hold',
            'No receiver protocol/release/late-reply teardown, live adapter or pre-capture is established'])
    (a.output/'models.private.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f'{len(cases)} tagged query allocation/send models; no native allocation, CP delivery or camera operation.')


if __name__=='__main__':main()
