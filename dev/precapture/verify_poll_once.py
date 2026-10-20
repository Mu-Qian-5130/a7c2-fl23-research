"""Receive ownership unit models, not actual native receive or CP replies.

The normal shared range stays UNMAPPED in these tests: the component may
return an opaque pointer, but must never dereference or free it itself.
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
from support.memory import MEM, STACK, STOP

IOCTL, SHARED, SIZE = 0x21000000, 0x60000000, 0x200000
OWN_ID = 0x803f6111


def decode(raw):
    v=struct.unpack('<6IqQ2I',raw)
    return dict(zip(('magic','version','phase','consumed','own_id','reserved',
                     'status','message','attempts','ownership'),v))


def model(elf,spec):
    u,symbols=image_loader(elf,'aarch64',('precapture_poll_once',))
    u.mem_map(IOCTL,4096)
    binding,result=MEM+0x100,MEM+0x200
    kind=spec['name'];fields=[0 if kind=='descriptor-zero' else 77,0,SHARED,SIZE]
    for index,value in spec.get('binding',{}).items():fields[index]=value
    if kind in ('result-in-shared','binding-in-shared'):
        u.mem_map(SHARED,4096)
        if kind=='result-in-shared':result=SHARED+0x200
        else:binding=SHARED+0x100
    if kind=='overlapping-result':
        fields[0]=0;result=binding-40
    u.mem_write(binding,struct.pack('<iIQQ',*fields))
    if kind=='used-result':u.mem_write(result,b'\x01')
    original=bytes(u.mem_read(result,48));original_binding=bytes(u.mem_read(binding,24))
    calls=[]
    def trap(cpu,at,size,_):
        if at!=IOCTL:return
        fd,command,outer=[u.reg_read(r) for r in (R.UC_ARM64_REG_X0,R.UC_ARM64_REG_X1,R.UC_ARM64_REG_X2)]
        assert fd==fields[0] and command==0x80000007 and not calls
        route,pad,inner=struct.unpack('<IIQ',bytes(u.mem_read(outer,16)))
        pointer,timeout,pad2=struct.unpack('<QII',bytes(u.mem_read(inner,16)))
        assert (route,pad,pointer,timeout,pad2)==(OWN_ID,0,result+32,0,0)
        state=decode(bytes(u.mem_read(result,48)))
        assert (state['phase'],state['attempts'],state['ownership'],state['message'])==(1,1,0,0)
        calls.append(dict(command=hex(command),route=hex(route),timeout=timeout))
        u.mem_write(pointer,struct.pack('<Q',spec.get('message',SHARED+64)))
        for i in range(1,18):u.reg_write(getattr(R,f'UC_ARM64_REG_X{i}'),0xde000000+i)
        u.reg_write(R.UC_ARM64_REG_X0,spec.get('status',0)&((1<<64)-1))
        u.reg_write(R.UC_ARM64_REG_PC,u.reg_read(R.UC_ARM64_REG_LR))
    u.hook_add(UC_HOOK_CODE,trap)
    def run():
        for reg,value in ((R.UC_ARM64_REG_X0,0 if kind=='null-binding' else spec.get('binding_pointer',binding)),
            (R.UC_ARM64_REG_X1,0 if kind=='null-result' else spec.get('result_pointer',result)),
            (R.UC_ARM64_REG_X2,spec.get('own_id',OWN_ID)),
            (R.UC_ARM64_REG_X3,0 if kind=='null-invoke' else IOCTL),
            (R.UC_ARM64_REG_SP,STACK+0x3000),(R.UC_ARM64_REG_LR,STOP)):
            u.reg_write(reg,value)
        u.emu_start(symbols['precapture_poll_once'],STOP,count=50000)
        assert u.reg_read(R.UC_ARM64_REG_PC)==STOP
        return u.reg_read(R.UC_ARM64_REG_X0)&0xffffffff
    returned=run();raw=bytes(u.mem_read(result,48))
    if spec.get('invalid') or kind=='used-result':
        assert returned==(-16 if kind=='used-result' else -22)&0xffffffff
        assert not calls and raw==original and bytes(u.mem_read(binding,24))==original_binding
        return dict(case=kind,rejected_before_ioctl=True,result_and_binding_untouched=True)
    decoded=decode(raw)
    assert returned==spec['return']&0xffffffff
    assert (decoded['phase'],decoded['ownership'])==spec['terminal']
    assert decoded['status']==spec.get('status',0) and decoded['message']==spec.get('message',SHARED+64)
    assert len(calls)==1 and bytes(u.mem_read(binding,24))==original_binding
    assert run()==(-16&0xffffffff) and len(calls)==1 and bytes(u.mem_read(result,48))==raw
    return dict(case=kind,calls=calls,phase=decoded['phase'],ownership=decoded['ownership'],
        reentry_rejected=True,payload_read_or_free=False,native_receive=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--zig',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    source=Path(__file__).with_name('ap_poll_once.c');elf=a.output/'NOT-INSTALLABLE-poll-once.elf'
    compile_shared(a.zig,'aarch64',elf,[source])
    specs=[dict(name='received',**{'return':0},terminal=(3,1)),
        dict(name='descriptor-zero',**{'return':0},terminal=(3,1)),
        dict(name='lowest-header-room',message=SHARED+24,**{'return':0},terminal=(3,1)),
        dict(name='last-tail-room',message=SHARED+SIZE-8,**{'return':0},terminal=(3,1)),
        dict(name='empty-fresh-output',status=-1022,message=0,**{'return':1},terminal=(2,0))]
    for name,status,pointer in (
        ('empty-with-pointer',-1022,SHARED+64),('busy',-1021,0),('interrupted',-4,0),
        ('copy-failure',-1024,0),('partial-copy-failure',-1024,SHARED+64),
        ('positive-status',1,SHARED+64),('returned-null',0,0),
        ('header-before-map',0,SHARED+16),('unaligned-pointer',0,SHARED+65),
        ('outside-map',0,SHARED+SIZE),('all-ones-pointer',0,(1<<64)-1)):
        specs.append(dict(name=name,status=status,message=pointer,**{'return':-5},terminal=(4,2)))
    for name in ('null-binding','null-result','null-invoke','overlapping-result','result-in-shared','binding-in-shared'):
        specs.append(dict(name=name,invalid=True))
    for name,fields in (('negative-fd',{0:-1}),('reserved-binding',{1:1}),
        ('zero-map',{2:0}),('unaligned-map',{2:SHARED+1}),('bad-map-size',{3:4096}),
        ('wrapped-map',{2:0xfffffffffff00000})):
        specs.append(dict(name=name,binding=fields,invalid=True))
    for value in (0,0x803f0000,0x803f8001,0x803e6111,0x903f6111,0xffffffff):
        specs.append(dict(name=f'invalid-own-ID-{value:08x}',own_id=value,invalid=True))
    specs.append(dict(name='wrapped-result-pointer',result_pointer=(1<<64)-16,invalid=True))
    specs.append(dict(name='wrapped-binding-pointer',binding_pointer=(1<<64)-8,invalid=True))
    specs.append(dict(name='used-result'))
    cases=[model(elf,spec) for spec in specs]
    files=[source,source.with_suffix('.h'),source.with_name('ap_probe_once.h')]
    report=dict(schema='OFFLINE_SINGLE_POLL_OWNERSHIP_MODELS/1',camera_io=False,cases=cases,
        sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        ELF_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(),
        limits=['Native ioctl results are explicit unit inputs, not actual queue receives',
            'Shared payload is deliberately unmapped; returned addresses remain opaque and unvalidated',
            'Caller must prove fresh isolated context, own ID provenance and exact live sources',
            'Unknown outcomes need a durable outer context/process hold; no adapter is supplied',
            'No request send, payload protocol, release, CP reply, recovery or pre-capture is established'])
    (a.output/'models.private.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f'{len(cases)} one-attempt poll ownership models; no native receive, payload access or camera operation.')


if __name__=='__main__':main()
