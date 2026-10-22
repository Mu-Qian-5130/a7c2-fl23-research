"""Backup ST and live menu ST are separate states; compiled native tests, no USB."""
import itertools
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src/shutter_sound'),str(ROOT/'dev/shutter_sound')]
from looktool import runtimebindings
from verify_probe import execute
from unicorn import UC_HOOK_CODE
from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2,UC_ARM64_REG_X3,UC_ARM64_REG_X4,UC_ARM64_REG_LR,UC_ARM64_REG_PC

@pytest.fixture(scope='module')
def ap():
    image=bytearray(0x57c6710+18*32)
    for at,hexcode in runtimebindings.SIGNATURES.items():
        raw=bytes.fromhex(hexcode);image[at:at+len(raw)]=raw
    for index in range(10,18):
        key=0x02cf0cd0+2*(index-10) if index<16 else (0x02cf1287 if index==16 else 0x02cf1289)
        struct.pack_into('<8I',image,0x57c6710+index*32,3,key,0x10000,0,0,0,0x14ea+index,0)
    return bytes(image)

def run_worker(ap,worker,selected,*,linked=True,fault='none'):
    base=0x400000000;values=list(range(10))+[5,6,7,8,9,1,10,11]
    calls=[];pointers=[]
    helpers=[0x178f950,0x2e06cc0,0x36830a8,0x2506ff0,0x2e068cc,0x178f974,0x2506218]
    headers={at:bytes.fromhex(code) for at,code in runtimebindings.SIGNATURES.items()}
    if fault=='signature':headers[0x178f950]=bytes(len(headers[0x178f950]))
    def setup(cpu,appbase):
        pages=set()
        def put(at,raw):
            for page in range(at&~4095,(at+len(raw)+4095)&~4095,4096):
                if page not in pages:cpu.mem_map(page,4096);pages.add(page)
            cpu.mem_write(at,raw)
        put(base+0x7eac508,struct.pack('<18I',*values))
        put(base+0x7eac550,bytes(720));put(base+0x7e70598,struct.pack('<I',13))
        for index in range(18):
            pointer=base+0xa000000+index*8;pointers.append(pointer)
            put(pointer,struct.pack('<I',values[index]))
            if linked:put(base+0x7eac550+index*40+8,struct.pack('<Q',pointer))
        for at in helpers:put(base+at,bytes.fromhex('c0035fd6'))
        # Execute the two original, fully guarded leaf getters.
        put(base+0x287ee10,bytes.fromhex(runtimebindings.SIGNATURES[0x287ee10]))
        def hook(uc,at,size,user):
            offset=at-base
            if offset not in helpers:return
            args=[uc.reg_read(reg) for reg in [UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2,UC_ARM64_REG_X3,UC_ARM64_REG_X4]]
            calls.append((offset,args))
            if offset==0x178f950:uc.mem_write(args[0],bytes(16))
            elif offset==0x36830a8:
                index=args[1]-0x14e9
                target=next(row for row in selected if row['index']==index)
                assert args[0]==0 and args[2]==(pointers[index] if linked else base+0x7eac508+index*4)
                assert args[4]==4 and bytes(uc.mem_read(args[3],4))==struct.pack('<I',target['value'])
            elif offset==0x2506218:
                assert args[0]==0x14e9
                if fault=='selected_readback':uc.mem_write(base+0x7eac508+selected[0]['index']*4,struct.pack('<I',9))
                if fault=='unselected_change':uc.mem_write(base+0x7eac508,struct.pack('<I',9))
            uc.reg_write(UC_ARM64_REG_PC,uc.reg_read(UC_ARM64_REG_LR))
        cpu.hook_add(UC_HOOK_CODE,hook)
    holder=[]
    def setup_and_keep(cpu,appbase):holder.append(cpu);setup(cpu,appbase)
    def syscall(cpu,no,args):
        if no==67 and args[3] in [base+0x7eac508,base+0x7e70598]:
            cpu.mem_write(args[1],bytes(cpu.mem_read(args[3],args[2])));return args[2]
        return None
    raw=execute(worker,ap,fault if fault in ['model','nonroot'] else 'none',extra_headers=headers,
        setup_native=setup_and_keep,extra_syscall=syscall,decode=lambda raw:raw,
        result_path='/tmp/jiritsu/a7c2.runtime.result',extra_outputs={'/tmp/jiritsu/a7c2.runtime.result':0x241})
    status=struct.unpack_from('<q',raw,16)[0]
    expected_status={'signature':-84,'model':-22,'nonroot':-22,'selected_readback':-5,'unselected_change':-84}.get(fault,0)
    assert status==expected_status
    if expected_status:
        with pytest.raises(ValueError):runtimebindings.parse(raw,selected)
        if fault in ['signature','model','nonroot']:assert calls==[]
        return
    result=runtimebindings.parse(raw,selected)
    changed=[row for row in selected if values[row['index']]!=row['value']]
    assert len(calls)==len(changed)*7
    for step,row in enumerate(changed):
        batch=calls[step*7:step*7+7]
        assert [at for at,args in batch]==helpers
        assert batch[3][1][0]==0x14e9+row['index']
    if linked:
        expected=values[:]
        for row in selected:expected[row['index']]=row['value']
        assert [struct.unpack('<I',holder[0].mem_read(pointer,4))[0] for pointer in pointers]==expected
    return result

@pytest.mark.parametrize('slots',[list(c) for n in range(1,7) for c in itertools.combinations(range(1,7),n)])
def test_every_selected_slot_combination_preserves_the_other_bases(ap,tmp_path,slots):
    selected=runtimebindings.targets(ap,{0x02cf0cd0+2*(slot-1):b'\0' for slot in slots})
    build=runtimebindings.build(ap,selected,tmp_path)
    result=run_worker(ap,build['path'],selected)
    assert result['current']==13

@pytest.mark.parametrize('linked',[False,True])
@pytest.mark.parametrize('fault',['none','signature','model','nonroot','selected_readback','unselected_change'])
def test_compiled_worker_uses_the_native_menu_sequence_and_checks_results(ap,tmp_path,linked,fault):
    selected=runtimebindings.targets(ap,{0x02cf0cd6:b'\0'})
    build=runtimebindings.build(ap,selected,tmp_path)
    run_worker(ap,build['path'],selected,linked=linked,fault=fault)

@pytest.mark.parametrize('value',[0,10,11])
def test_native_fl23_bases_can_also_be_synchronized_or_cleared(ap,tmp_path,value):
    selected=runtimebindings.targets(ap,{0x02cf1287:bytes([value]),0x02cf1289:bytes([value])})
    build=runtimebindings.build(ap,selected,tmp_path)
    run_worker(ap,build['path'],selected)

def test_already_st_backup_still_updates_a_stale_native_model(ap,tmp_path):
    fields={0x02cf0cd6:b'\0'};selected=runtimebindings.targets(ap,fields)
    owner=SimpleNamespace(root=tmp_path,zig=None,state={'journal':[]},_runtime_binding_ap=ap,
        record=lambda *a,**kw:None,raw=lambda *a:None)
    camera=SimpleNamespace(property_read=lambda key:b'\0',snapshot=lambda memory:memory,
        records=lambda raw:[{0x02cf0cd6:SimpleNamespace(data=b'\0')}])
    # Separate model starts BW despite both backup snapshots reporting ST.
    def invoke(camera,blob,**kwargs):
        assert kwargs['mode']==1
        return run_worker(ap,next((tmp_path/'runtime-bindings').rglob('look-bindings.so')),selected)
    with patch.object(runtimebindings,'invoke',side_effect=invoke) as call:
        result=runtimebindings.sync(camera,owner,fields)
        assert result['before'][13]==8 and result['after'][13]==0
        assert runtimebindings.sync(camera,owner,fields) is None
        assert call.call_count==1

def test_no_look_binding_fields_do_not_read_programs_or_build_workers():
    runtimebindings.sync(SimpleNamespace(),SimpleNamespace(),{0x02cf1906:b'\0'})
