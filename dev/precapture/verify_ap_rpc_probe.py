"""Isolated-context RPC component UNIT MODELS, not native RPC observations.

Explicit ioctl replies model ownership/protocol outcomes. An original
constructor produces the24-byte header fixture. Native library marshal
instructions independently reach ioctl before execution. No live binding,
process, kernel wait, CP message, firmware write or boot occurs.
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
from support.uipc import original_header, library

SHARED,SIZE,IOCTL=0x60000000,0x200000,0x21000000
BLOCK,MESSAGE=SHARED+0x1000,SHARED+0x1040
BIND,STATE=MEM+0x200,MEM
NAMES=('precapture_rpc_probe_once','precapture_probe_native_ioctl')


def decode(raw):
    v=struct.unpack('<8I3q3Q8I',raw)
    return dict(magic=v[0],version=v[1],phase=v[2],ownership=v[3],nonce=v[4],
        allocation_attempts=v[5],rpc_attempts=v[6],release_attempts=v[7],
        allocation_status=v[8],rpc_status=v[9],release_status=v[10],
        message=v[11],callback=v[12],callback_context=v[13],response_status=v[14],
        nonce_echo=v[15],tail_nonce=v[16],processor_state=v[17],reply_kind=v[18],source=v[19])


def model(elf,header,spec):
    u,sym=image_loader(elf,'aarch64',NAMES)
    u.mem_map(SHARED,SIZE);u.mem_map(IOCTL,4096);u.mem_write(BLOCK,header)
    binding=[77,0,SHARED,SIZE]
    for i,v in spec.get('binding',{}).items():binding[i]=v
    u.mem_write(BIND,struct.pack('<iIQQ',*binding));u.mem_write(STATE,bytes(112))
    if spec.get('used'):u.mem_write(STATE+108,b'\1')
    before=bytes(u.mem_read(STATE,112));nonce=spec.get('nonce',0xa17e1234)
    source=spec.get('source',0x80020002);calls=[];mapped=True
    def ret(cpu,value):
        for i in range(1,18):cpu.reg_write(getattr(R,f'UC_ARM64_REG_X{i}'),0xde000000+i)
        cpu.reg_write(R.UC_ARM64_REG_X0,value&((1<<64)-1));cpu.reg_write(R.UC_ARM64_REG_PC,cpu.reg_read(R.UC_ARM64_REG_LR))
    def callback(cpu,at,n,_):
        nonlocal mapped
        if at!=IOCTL:return
        fd,op,arg=[cpu.reg_read(r) for r in (R.UC_ARM64_REG_X0,R.UC_ARM64_REG_X1,R.UC_ARM64_REG_X2)]
        assert fd==77
        route,pad,ptr=struct.unpack('<IIQ',bytes(cpu.mem_read(arg,16)))
        assert route==0x908f084b and not pad;calls.append(op)
        state=decode(bytes(cpu.mem_read(STATE,112)))
        if op==0x8000000a:
            assert calls==[op] and state['phase']==1 and state['allocation_attempts']==1
            out,count,wait=struct.unpack('<QII',bytes(cpu.mem_read(ptr,16)))
            assert(count,wait)==(24,0) and bytes(cpu.mem_read(out,8))==bytes(8)
            status=spec.get('allocation_status',0);message=spec.get('message',MESSAGE if not status else 0)
            cpu.mem_write(out,struct.pack('<Q',message))
            if spec.get('bad_header'):cpu.mem_write(MESSAGE-8,struct.pack('<I',16))
            ret(cpu,status)
        elif op==0x80000005:
            assert calls==[0x8000000a,op] and state['phase']==3 and state['ownership']==2
            assert struct.unpack('<3Q',bytes(cpu.mem_read(ptr,24)))==(MESSAGE,0,0)
            expected=bytearray(24);expected[0]=0xe1;struct.pack_into('<I',expected,20,nonce)
            assert bytes(cpu.mem_read(MESSAGE,24))==bytes(expected)
            sourced=bytearray(header[:64]);struct.pack_into('<I',sourced,52,source)
            assert bytes(cpu.mem_read(BLOCK,64))==bytes(sourced)
            assert state['source']==source and state['version']==2
            status=spec.get('rpc_status',0)
            cb,ctx=spec.get('delegate',0),spec.get('context',0)
            changed_message=spec.get('returned_message',MESSAGE)
            cpu.mem_write(ptr,struct.pack('<3Q',changed_message,cb,ctx))
            if status or cb or ctx or changed_message!=MESSAGE:
                # Ambiguous completion may have consumed the mapping. The
                # component must neither touch nor free it afterward.
                cpu.mem_unmap(SHARED,SIZE);mapped=False;ret(cpu,status);return
            response=bytearray(expected);kind=spec.get('reply','absent')
            if kind=='absent':response[1]=0x80
            elif kind=='present':
                response[1]=0x5a;struct.pack_into('<3I',response,8,nonce,0xdeadbeef,0x60000013)
            elif kind=='wrong-echo':
                response[1]=0x5a;struct.pack_into('<3I',response,8,nonce^1,0xdeadbeef,0x60000013)
            elif kind=='wrong-tail':
                response[1]=0x5a;struct.pack_into('<I',response,8,nonce);struct.pack_into('<I',response,20,nonce^1)
            elif kind=='ordinary-address':
                response[1]=1;struct.pack_into('<QI',response,8,0x05000000,0x778000)
            elif kind=='unchanged':pass
            else:raise AssertionError(kind)
            cpu.mem_write(MESSAGE,bytes(response));ret(cpu,0)
        elif op==0x8000000b:
            assert calls==[0x8000000a,0x80000005,op] and ptr==MESSAGE
            assert state['phase']==5 and state['ownership']==1 and state['release_attempts']==1
            cpu.mem_unmap(SHARED,SIZE);mapped=False;ret(cpu,spec.get('release_status',0))
        else:raise AssertionError('Unplanned native operation')
    u.hook_add(UC_HOOK_CODE,callback)
    def run():
        for r,v in ((R.UC_ARM64_REG_X0,0 if spec.get('null_binding') else BIND),(R.UC_ARM64_REG_X1,STATE),
                (R.UC_ARM64_REG_X2,nonce),(R.UC_ARM64_REG_X3,source),
                (R.UC_ARM64_REG_X4,0 if spec.get('null_callback') else IOCTL),
                (R.UC_ARM64_REG_SP,STACK+0x3000),(R.UC_ARM64_REG_LR,STOP)):
            u.reg_write(r,v&((1<<64)-1))
        u.emu_start(sym[NAMES[0]],STOP,count=8000)
        assert u.reg_read(R.UC_ARM64_REG_PC)==STOP
        return u.reg_read(R.UC_ARM64_REG_X0)&0xffffffff
    result=run();assert result==spec.get('return',-5)&0xffffffff,(spec,hex(result))
    raw=bytes(u.mem_read(STATE,112));state=decode(raw)
    assert calls==spec['calls']
    if calls:
        assert(state['phase'],state['ownership'])==spec['terminal']
        assert state['rpc_attempts']==int(0x80000005 in calls)
        assert state['release_attempts']==int(0x8000000b in calls)
        if 'kind' in spec:assert state['reply_kind']==spec['kind']
        if state['reply_kind']==2:
            assert state['nonce_echo']==nonce and state['tail_nonce']==nonce
            assert state['processor_state']==0x60000013
            # Opaque word12 must not be copied into any semantic result field.
            assert 0xdeadbeef not in struct.unpack('<28I',raw)
        old=list(calls);assert run()==(-16&0xffffffff)
        assert calls==old and bytes(u.mem_read(STATE,112))==raw
    else:assert raw==before
    return dict(case=spec['name'],model_calls=[hex(c) for c in calls],terminal_phase=state['phase'],
        terminal_ownership=state['ownership'],reply_kind=state['reply_kind'],mapping_removed=not mapped,
        actual_RPC_or_kernel_operation=False)


def native_sync_wire(path):
    u,entry=library(path);seen=[]
    def hook(cpu,at,n,_):
        if at==entry['ioctl']:seen.append(at);cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook)
    for r,v in ((R.UC_ARM64_REG_X0,0x908f084b),(R.UC_ARM64_REG_X1,MESSAGE),
            (R.UC_ARM64_REG_SP,STACK+0x8000),(R.UC_ARM64_REG_LR,STOP)):
        u.reg_write(r,v)
    u.emu_start(0x3a98,0xffffffffffffffff,count=100)
    assert seen==[entry['ioctl']] and u.reg_read(R.UC_ARM64_REG_X0)==77
    assert u.reg_read(R.UC_ARM64_REG_X1)&0xffffffff==0x80000005
    packet=u.reg_read(R.UC_ARM64_REG_X2)
    route,inner=struct.unpack('<I4xQ',bytes(u.mem_read(packet,16)))
    assert route==0x908f084b and struct.unpack('<3Q',bytes(u.mem_read(inner,24)))==(MESSAGE,0,0)
    return dict(original_library_entry='0x3a98',command='0x80000005',inner_bytes=24,
        message_pointer_matches=True,callback_and_context_initially_zero=True,ioctl_executed=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--uipc-kernel',type=Path,required=True);p.add_argument('--uipc',type=Path,required=True)
    p.add_argument('--zig',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();header,original_sourced=original_header(a.uipc_kernel.read_bytes(),a.uipc.read_bytes(),24)
    assert struct.unpack_from('<I',header,56)[0]==24
    expected=bytearray(header);struct.pack_into('<I',expected,52,0x80020002)
    assert bytes(expected)==original_sourced  # original native setter, not a modeled API result
    wire=native_sync_wire(a.uipc)
    a.output.mkdir(parents=True,exist_ok=False);elf=a.output/'NOT-INSTALLABLE-ap-rpc-probe.elf'
    compile_shared(a.zig, 'aarch64', elf,
        [Path(__file__).with_name('ap_rpc_probe_once.c'), Path(__file__).with_name('ap_probe_once.c')])
    A,S,F=0x8000000a,0x80000005,0x8000000b
    specs=[dict(name='observer-absent',calls=[A,S,F],terminal=(6,0),kind=1,**{'return':0}),
        dict(name='observer-present',reply='present',calls=[A,S,F],terminal=(6,0),kind=2,**{'return':0}),
        dict(name='callback-delegation',delegate=0x72000000,calls=[A,S],terminal=(8,3)),
        dict(name='callback-context',context=0x1234,calls=[A,S],terminal=(8,3)),
        dict(name='message-changed',returned_message=MESSAGE+64,calls=[A,S],terminal=(8,3)),
        dict(name='bad-native-header',bad_header=True,calls=[A],terminal=(8,3)),
        dict(name='null-pointer',message=0,calls=[A],terminal=(8,3)),
        dict(name='outside-pointer',message=0x72000000,calls=[A],terminal=(8,3)),
        dict(name='unaligned-pointer',message=MESSAGE+1,calls=[A],terminal=(8,3)),
        dict(name='failed-with-pointer',allocation_status=-1023,message=MESSAGE,calls=[A],terminal=(8,3)),
        dict(name='free-unknown',release_status=-5,calls=[A,S,F],terminal=(8,3))]
    for reply in ('wrong-echo','wrong-tail','ordinary-address','unchanged'):
        specs.append(dict(name=reply,reply=reply,calls=[A,S,F],terminal=(6,0),kind=3,**{'return':-84}))
    for value in (-22,-1021,-1023,-1024):
        specs.append(dict(name=f'allocate-rejected-{value}',allocation_status=value,calls=[A],terminal=(7,0)))
    for value in (-4,-5,1):
        specs.append(dict(name=f'allocate-unknown-{value}',allocation_status=value,calls=[A],terminal=(8,3)))
    for value in (-22,-4,-5,-1021):
        specs.append(dict(name=f'RPC-unknown-{value}',rpc_status=value,calls=[A,S],terminal=(8,3)))
    for name,fields in (('negative-fd',dict(binding={0:-1})),('bad-reserved',dict(binding={1:1})),
            ('unaligned-map',dict(binding={2:SHARED+1})),('bad-size',dict(binding={3:4096})),
            ('wrapped-map',dict(binding={2:0xfffffffffffff000})),('zero-nonce',dict(nonce=0)),
            ('null-binding',dict(null_binding=True)),('null-callback',dict(null_callback=True))):
        specs.append(dict(name=name,calls=[],**fields,**{'return':-22}))
    specs.append(dict(name='used-result',used=True,calls=[],**{'return':-16}))
    for value in (0,0x00020002,0xa5a5a5a5,0xffffffff):
        specs.append(dict(name=f'invalid-source-{value:08x}',source=value,calls=[],**{'return':-22}))
    specs.append(dict(name='distinct-explicit-source',source=0x80020005,calls=[A,S,F],terminal=(6,0),kind=1,**{'return':0}))
    results=[model(elf,header,s) for s in specs]
    report=dict(schema='OFFLINE_RPC_PROBE_UNIT_MODELS/2',camera_io=False,cases=results,native_wire_boundary=wire,
        kernel_header_fixture_payload_bytes=24,ELF_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(),
        source_setter_original_displacement=-12,source_provenance_verified=False,
        limits=['RPC success/failure/replies are deliberate unit models, not real native service observations',
            'This component can block in the kernel; never invoke it in AP service init',
            'Unknown/delegated states retain unresolved ownership; a future isolated process must preserve its lifetime',
            'No live source/FD/map adapter, isolated launcher or durable host fencing is supplied',
            'No CP response, ROM write/reload/recovery or physical pre-capture is proven'])
    (a.output/'unit-models.private.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(f'RPC component:{len(results)} ownership/protocol MODELS and original sync-wire boundary. No live RPC or camera operation.')
if __name__=='__main__':main()
