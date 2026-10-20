"""Status-reply unit models on both ISAs; callback returns are explicit inputs.

No native reply service, IPC, task, queue, source loading or camera executes.
Linked native-entry boundary checks live in verify_runtime_entries.py.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from unicorn import UC_HOOK_CODE
from unicorn import arm64_const as A
from unicorn import arm_const as T
from support.build import compile_shared
from support.elf import image_loader
from support.memory import MEM, STACK, STOP

REPLY=0x21000000
DEFAULT=[0,1,500,0,0,0,0,0,0,0,0,0]
TAG,NONCE,ORIGIN=0x3d6656b9,0x12345678,0x803f6111


def model(elf,arch,spec):
    u,symbols=image_loader(elf,arch,('precapture_backend_query',))
    regs=[getattr(A,f'UC_ARM64_REG_X{i}') for i in range(6)] if arch=='aarch64' else [T.UC_ARM_REG_R0,T.UC_ARM_REG_R1,T.UC_ARM_REG_R2,T.UC_ARM_REG_R3]
    sp,lr,pc=(A.UC_ARM64_REG_SP,A.UC_ARM64_REG_LR,A.UC_ARM64_REG_PC) if arch=='aarch64' else (T.UC_ARM_REG_SP,T.UC_ARM_REG_LR,T.UC_ARM_REG_PC)
    state,ops,packet=MEM,MEM+0x100,MEM+0x200
    values=list(DEFAULT)
    for i,v in spec.get('state',{}).items():values[i]=v
    raw=struct.pack('<12I',*values);u.mem_write(state,raw)
    request=bytearray(bytes([5,0,0x72,0x41])+struct.pack('<II',NONCE,0x31595251))
    for i,v in spec.get('request',{}).items():request[i]=v
    u.mem_write(packet,bytes(request))
    width=8 if arch=='aarch64' else 4
    callback=0 if spec['name']=='null-reply' else REPLY|(arch=='thumb')
    u.mem_write(ops,bytes(3*width)+struct.pack('<Q' if width==8 else '<I',callback))
    u.mem_map(REPLY,4096);calls=[]
    def hook(cpu,at,size,_):
        if at!=REPLY:return
        args=[u.reg_read(r) for r in regs[:3]]
        pointer,length,origin=args
        assert length==32 and origin==ORIGIN and not calls
        flags=values[0]|(values[8]<<1)|(values[10]<<2)|(values[11]<<3)|(values[4]<<4)|(values[1]<<8)
        nonce=struct.unpack_from('<I',request,4)[0]
        expected=bytes([1,0,0x72,0x41])+struct.pack('<7I',nonce,0x31545350,TAG,
            values[9],flags,values[3],values[2])
        actual=bytes(u.mem_read(pointer,32))
        assert actual==expected,(arch,spec['name'],actual.hex(),expected.hex())
        assert bytes(u.mem_read(state,48))==raw and bytes(u.mem_read(packet,12))==bytes(request)
        calls.append(dict(packet_hex=actual.hex(),origin=hex(origin),native_service=False))
        if arch=='aarch64':
            for i in range(1,18):u.reg_write(getattr(A,f'UC_ARM64_REG_X{i}'),0xde000000+i)
        else:
            for r in (T.UC_ARM_REG_R1,T.UC_ARM_REG_R2,T.UC_ARM_REG_R3,T.UC_ARM_REG_R12):u.reg_write(r,0xde000001)
        u.reg_write(regs[0],spec.get('callback_return',0)&((1<<64)-1 if arch=='aarch64' else 0xffffffff))
        u.reg_write(pc,u.reg_read(lr))
    u.hook_add(UC_HOOK_CODE,hook)
    args=[0 if spec['name']=='null-state' else state,0 if spec['name']=='null-ops' else ops,
        0 if spec['name']=='zero-source-tag' else TAG,0 if spec['name']=='null-request' else packet,
        spec.get('length',12),spec.get('origin',ORIGIN)]
    u.reg_write(sp,STACK+0x3000);u.reg_write(lr,STOP|(arch=='thumb'))
    for reg,value in zip(regs,args):u.reg_write(reg,value)
    if arch=='thumb':u.mem_write(STACK+0x3000,struct.pack('<2I',*args[4:]))
    u.emu_start(symbols['precapture_backend_query'],STOP,count=10000)
    assert u.reg_read(pc)==STOP and u.reg_read(regs[0])&0xffffffff==spec['return']&0xffffffff
    assert bool(calls)==spec.get('reply',False)
    assert bytes(u.mem_read(state,48))==raw and bytes(u.mem_read(packet,12))==bytes(request)
    return dict(case=spec['name'],reply_calls=calls,state_and_request_unchanged=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--zig',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    specs=[dict(name='idle',reply=True,**{'return':1}),
        dict(name='pending',state={3:7,4:1,8:1,9:123,10:1},reply=True,**{'return':1}),
        dict(name='faulted',state={0:1,3:3,8:1,9:0xffffffff,10:1,11:1},reply=True,**{'return':1}),
        dict(name='unconfigured',state={1:0,2:0},reply=True,**{'return':1}),
        dict(name='nonce-one',request={4:1,5:0,6:0,7:0},reply=True,**{'return':1}),
        dict(name='nonce-all-ones',request={4:255,5:255,6:255,7:255},reply=True,**{'return':1})]
    for status in (-1,-5,1):
        specs.append(dict(name=f'reply-error-{status}',callback_return=status,reply=True,**{'return':-5}))
    for name in ('null-state','null-ops','null-reply','null-request','zero-source-tag'):
        specs.append(dict(name=name,**{'return':-22}))
    for length in (0,4,11,13,16):specs.append(dict(name=f'bad-length-{length}',length=length,**{'return':-22}))
    for at in (0,1,2,3,4,8):
        fields={at:0 if at in (0,2,3,4,8) else 1}
        if at==4:fields.update({5:0,6:0,7:0})
        specs.append(dict(name=f'bad-request-field-{at}',request=fields,**{'return':-22}))
    for origin in (0,0x803f0000,0x803f8001,0x90030001,0x80bf6111):
        specs.append(dict(name=f'bad-origin-{origin:x}',origin=origin,**{'return':-22}))
    for index,value in ((0,2),(1,4),(2,4),(2,1001),(3,8),(4,2),(8,2),(10,2),(11,2)):
        specs.append(dict(name=f'invalid-state-{index}-{value}',state={index:value},**{'return':-84}))
    results={}
    for arch in ('thumb','aarch64'):
        elf=a.output/(arch+'-backend-query.elf')
        names=('cp_backend.c','cp_control_state.c','s1_trigger.c','capture_gate.c')
        sources=[Path(__file__).with_name(n) for n in names]
        compile_shared(a.zig,arch,elf,sources)
        results[arch]=dict(cases=[model(elf,arch,spec) for spec in specs],
            ELF_sha256=hashlib.sha256(elf.read_bytes()).hexdigest())
    report=dict(schema='OFFLINE_CP_STATUS_QUERY_UNIT_MODELS/1',camera_io=False,architectures=results,
        sources={n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest()
                 for n in (*names,'cp_backend.h','precapture_query_wire.h')},
        limits=['Callback return values are models, not successful native IPC or actual AP receipt',
            'Caller must serialize in the original S1 owner with verified runtime/source/origin',
            'Native reply helper can wait for allocation; no bounded live request is admitted',
            'No installer, sender, reload, physical query or pre-capture result is provided'])
    (a.output/'query-models.private.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f'{len(specs)} read-only query cases per ISA; callback results modeled, no native service or camera operation.')


if __name__=='__main__':main()
