"""Status reply validation/release models, not a real received CP packet.

The header is built by original AP instructions for a synthetic owned queue.
Release removes its mapping, then the same poll token is tried with a fresh
result to detect double-free or stale-pointer access.
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
MESSAGE,OWN_ID,NONCE,TAG=SHARED+0x1040,0x803f6111,0x12345678,0x3d6656b9


def decode(raw):
    v=struct.unpack('<8IqQ8I',raw)
    return dict(zip(('magic','version','phase','ownership','own_id','nonce','expected_tag','kind',
        'release_status','message','generation','flags','stage','duration_ms','release_attempts',
        'reserved','reply_nonce','reply_tag'),v))


def model(elf,header,spec):
    u,symbols=image_loader(elf,'aarch64',('precapture_reply_once',));u.mem_map(IOCTL,4096)
    binding,pol,result=MEM+0x100,MEM+0x200,MEM+0x300;kind=spec['name']
    b=[77,0,SHARED,SIZE]
    for i,v in spec.get('binding',{}).items():b[i]=v
    token=[0x314c4f50,1,3,1,OWN_ID,0,0,spec.get('message',MESSAGE),1,1]
    for i,v in spec.get('token',{}).items():token[i]=v
    if kind=='result-overlaps-binding':b[0]=0;result=binding-72
    if kind=='result-overlaps-token':result=pol+32
    u.mem_write(binding,struct.pack('<iIQQ',*b));u.mem_write(pol,struct.pack('<6IqQ2I',*token))
    if kind=='used-result':u.mem_write(result,b'\x01')
    original=bytes(u.mem_read(result,80));original_token=bytes(u.mem_read(pol,48))
    original_binding=bytes(u.mem_read(binding,24));calls=[];message=token[7]
    body=spec.get('payload') or bytes([1,0,0x72,0x41])+struct.pack('<7I',NONCE,0x31545350,TAG,9,0x100,0,500)
    packet=bytearray(body)
    for offset,value in spec.get('packet_words',{}).items():struct.pack_into('<I',packet,offset,value)
    readable=not spec.get('input_error') and SHARED+64<=message<=SHARED+SIZE-64 and not(message&63)
    if readable:
        u.mem_map(SHARED,SIZE);u.mem_write(message-64,header);u.mem_write(message,bytes(packet))
        for offset,value in spec.get('bad_header',{}).items():u.mem_write(message+offset,bytes([value]))
        if 'source' in spec:u.mem_write(message-12,struct.pack('<I',spec['source']))
    def hook(cpu,at,size,_):
        if at!=IOCTL:return
        fd,command,argument=[u.reg_read(r) for r in (R.UC_ARM64_REG_X0,R.UC_ARM64_REG_X1,R.UC_ARM64_REG_X2)]
        assert fd==b[0] and command==0x8000000b and not calls
        route,pad,pointer=struct.unpack('<IIQ',bytes(u.mem_read(argument,16)))
        assert (route,pad,pointer)==(OWN_ID,0,message)
        state=decode(bytes(u.mem_read(result,80)))
        assert state['phase']==3 and state['ownership']==2 and state['release_attempts']==1
        assert struct.unpack('<6IqQ2I',bytes(u.mem_read(pol,48)))[2]==5
        calls.append(command);u.mem_unmap(SHARED,SIZE)
        for i in range(1,18):u.reg_write(getattr(R,f'UC_ARM64_REG_X{i}'),0xde000000+i)
        u.reg_write(R.UC_ARM64_REG_X0,spec.get('release_status',0)&((1<<64)-1))
        u.reg_write(R.UC_ARM64_REG_PC,u.reg_read(R.UC_ARM64_REG_LR))
    u.hook_add(UC_HOOK_CODE,hook)
    def run(destination):
        args=(0 if kind=='null-binding' else binding,0 if kind=='null-token' else pol,
            0 if kind=='null-result' else destination,spec.get('nonce',NONCE),spec.get('tag',TAG),
            0 if kind=='null-invoke' else IOCTL)
        for i,value in enumerate(args):u.reg_write(getattr(R,f'UC_ARM64_REG_X{i}'),value)
        u.reg_write(R.UC_ARM64_REG_SP,STACK+0x3000);u.reg_write(R.UC_ARM64_REG_LR,STOP)
        u.emu_start(symbols['precapture_reply_once'],STOP,count=50000)
        assert u.reg_read(R.UC_ARM64_REG_PC)==STOP
        return u.reg_read(R.UC_ARM64_REG_X0)&0xffffffff
    status=run(result);raw=bytes(u.mem_read(result,80));state=decode(raw)
    if spec.get('input_error'):
        assert status==spec['input_error']&0xffffffff
        assert not calls and raw==original and bytes(u.mem_read(pol,48))==original_token
        return dict(case=kind,rejected_before_access=True,inputs_untouched=True)
    assert status==spec['return']&0xffffffff and (state['phase'],state['ownership'])==spec['terminal']
    assert len(calls)==spec.get('frees',0) and bytes(u.mem_read(binding,24))==original_binding
    assert state['kind']==spec.get('reply_kind',0)
    assert state['magic']==0x31505251 and state['version']==1 and state['own_id']==OWN_ID
    assert state['nonce']==spec.get('nonce',NONCE) and state['expected_tag']==spec.get('tag',TAG)
    if calls:
        words=struct.unpack('<8I',packet)
        assert [state[k] for k in ('reply_nonce','reply_tag','generation','flags','stage','duration_ms')]==[
            words[1],words[3],words[4],words[5],words[6],words[7]]
        assert state['release_status']==spec.get('release_status',0)
    assert state['release_attempts']==len(calls)
    assert run(result)==(-16&0xffffffff) and len(calls)==spec.get('frees',0)
    # New result cannot reuse a consumed poll token, even after a free error.
    fresh=MEM+0x500;u.mem_write(fresh,bytes(80));token_after=bytes(u.mem_read(pol,48))
    assert run(fresh)==(-16&0xffffffff) and bytes(u.mem_read(fresh,80))==bytes(80)
    assert bytes(u.mem_read(pol,48))==token_after and bytes(u.mem_read(result,80))==raw
    return dict(case=kind,phase=state['phase'],ownership=state['ownership'],kind=state['kind'],
        release_attempts=len(calls),new_result_cannot_reuse_poll=True,post_free_access=False,native_free=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('zig','uipc-kernel','uipc','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    header_before,header=original_header(a.uipc_kernel.read_bytes(),a.uipc.read_bytes(),32,
        initial_byte=0x3c,route=OWN_ID,source_id=0x90030001)
    assert header_before[48:52]==bytes.fromhex('02410100')
    source=Path(__file__).with_name('ap_reply_once.c');elf=a.output/'NOT-INSTALLABLE-reply-once.elf'
    compile_shared(a.zig,'aarch64',elf,[source])
    specs=[dict(name='matched',frees=1,reply_kind=1,terminal=(4,0),**{'return':0}),
        dict(name='fault-snapshot',packet_words={20:0x31f,24:3},frees=1,reply_kind=1,terminal=(4,0),**{'return':0})]
    for name,words in (('bad-class',{0:0x41720005}),('wrong-nonce',{4:NONCE+1}),
        ('bad-marker',{8:0}),('wrong-tag',{12:TAG+1}),('reserved-flags',{20:0x120}),
        ('bad-stage',{24:8}),('short-duration',{28:4}),('large-duration',{28:1001}),
        ('disabled-trigger-duration',{20:0})):
        specs.append(dict(name=name,packet_words=words,frees=1,reply_kind=2,terminal=(4,0),**{'return':-84}))
    specs.append(dict(name='foreign-source',source=0x90030002,frees=1,reply_kind=2,terminal=(4,0),**{'return':-84}))
    for offset,value in ((-16,1),(-15,0),(-14,2),(-13,1),(-8,12),(-4,0),(32,0)):
        specs.append(dict(name=f'invalid-native-header-{offset}',bad_header={offset:value},terminal=(5,2),**{'return':-5}))
    for pointer in (0,SHARED+24,MESSAGE+8,SHARED+SIZE-8,(1<<64)-1):
        specs.append(dict(name=f'invalid-extent-{pointer:x}',message=pointer,terminal=(5,2),**{'return':-5}))
    for status in (-4,-5,1):
        specs.append(dict(name=f'free-unknown-{status}',release_status=status,frees=1,reply_kind=1,terminal=(5,2),**{'return':-5}))
    for name in ('null-binding','null-token','null-result','null-invoke','result-overlaps-binding','result-overlaps-token'):
        specs.append(dict(name=name,input_error=-22))
    for i,value in ((0,0),(1,2),(3,0),(4,0x903f6111),(5,1),(6,-1022),(8,2)):
        specs.append(dict(name=f'invalid-token-field-{i}',token={i:value},input_error=-22))
    for i,value in ((2,4),(2,6),(9,0),(9,2)):
        specs.append(dict(name=f'used-token-field-{i}-{value}',token={i:value},input_error=-16))
    specs.extend([dict(name='zero-nonce',nonce=0,input_error=-22),dict(name='zero-tag',tag=0,input_error=-22),
        dict(name='used-result',input_error=-16)])
    cases=[model(elf,header,spec) for spec in specs]
    files=[source,source.with_suffix('.h'),source.with_name('ap_poll_once.h'),source.with_name('ap_probe_once.h'),
        source.with_name('ap_binding_guard.h'),source.with_name('precapture_query_wire.h')]
    report=dict(schema='OFFLINE_STATUS_REPLY_RELEASE_MODELS/1',camera_io=False,cases=cases,
        kernel_sha256=UIPC_SHA,library_sha256=LIBRARY_SHA,owned_queue_constructor_route=hex(OWN_ID),
        ELF_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(),
        sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        limits=['All poll tokens and free outcomes are explicit models, not actual receives/releases',
            'Original lookup/header/source instructions run on independent synthetic objects',
            'A consumed token prevents local serial double-free; it is not a global concurrent-job interlock',
            'Unexpected owned packets can be released while the expected response remains pending',
            'A matched released reply does not prove outgoing transport cleanup or native quiescence',
            'No live context, sender/receiver adapter, CP response, physical restore or pre-capture is established'])
    (a.output/'models.private.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f'{len(cases)} reply/header/ownership models; no native receive/free or camera operation.')


if __name__=='__main__':main()
