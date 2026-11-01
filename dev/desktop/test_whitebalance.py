"""C2 AWB original instruction execution and preservation checks; no USB."""
import json
import os
from pathlib import Path
import struct

import pytest

from looktool import whitebalance, direct


@pytest.fixture(scope='module')
def original():
    root=os.environ.get('A7C2_FIRMWARE_ROOT')
    if not root:pytest.skip('Set A7C2_FIRMWARE_ROOT to private official inputs')
    folder=Path(root)/'a7c2-2.01/components'
    return ((folder/'cpapp-b.bin').read_bytes(),
            (folder/'backup-0ed000-unit-02a40000.bin').read_bytes())


def test_original_restore_preserves_unrelated_edits_and_never_changes_settings(original):
    cp,prop=original
    before=bytearray(cp);before[-64:]=bytes(range(64))
    enabled=whitebalance.plan(before,True)
    assert whitebalance.active(enabled)
    assert whitebalance.plan(enabled,True)==enabled
    assert whitebalance.plan(enabled,False)==before
    allowed={at+i for at,old,new in whitebalance.WINDOWS for i in range(len(old))}
    assert all(a==b or i in allowed for i,(a,b) in enumerate(zip(before,enabled)))
    current={'appFw.so':b'unrelated AP','cpapp-b.bin':bytes(before),'resource':b'title'}
    result,wanted,rename=direct.plan(current,None,'wb_enable')
    assert result==dict(current,**{'cpapp-b.bin':enabled})
    assert wanted==[{},{}] and rename is None


def test_unknown_or_partial_native_changes_are_not_overwritten(original):
    cp,_=original
    broken=bytearray(cp);broken[whitebalance.WINDOWS[0][0]]^=1
    with pytest.raises(ValueError,match='conflicts'):whitebalance.plan(broken,True)
    partial=bytearray(cp);at,old,new=whitebalance.WINDOWS[0];partial[at:at+len(new)]=new
    with pytest.raises(ValueError,match='Incomplete'):whitebalance.plan(partial,False)


def test_original_awb_function_consumes_same_values_as_parameter_change(original,tmp_path):
    import itertools
    from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB
    from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
    cp,prop=original;changed_cp=whitebalance.plan(cp,True)
    changed_prop=bytearray(prop);changed_prop[0x930:0x932]=bytes((97,255))
    base,work,stop=0x108000,0x30000000,0x31000000
    cpu=Uc(UC_ARCH_ARM,UC_MODE_THUMB);cpu.mem_map(base,0x3000000-base)
    cpu.mem_map(work,0x100000);cpu.mem_map(stop,4096)
    def run(program,parameters,mode,xy,metric,gate,branch):
        cpu.mem_write(base,program);cpu.ctl_remove_cache(0x257700,0x257800)
        cpu.mem_write(0x17929b0,bytes(parameters));cpu.mem_write(work,bytes(0x100000))
        state,stats,control,root,trace,aux,extra=(work+n for n in (0x1000,0x10000,0x20000,0x21000,0x22000,0x23000,0x24000))
        def w32(at,value):cpu.mem_write(at,struct.pack('<I',value))
        for at,value in ((work,state),(work+4,stats),(control,root),(root,trace),
                         (control+4,aux),(control+8,work+0x25000),(control+0x10,extra)):w32(at,value)
        cpu.mem_write(state+0x23,bytes((mode,)));cpu.mem_write(stats+3,bytes((branch,)))
        cpu.mem_write(stats+0x45a,struct.pack('<H',gate));cpu.mem_write(stats+0x476,struct.pack('<H',metric))
        cpu.reg_write(UC_ARM_REG_SP,work+0xff000);cpu.reg_write(UC_ARM_REG_LR,stop|1)
        cpu.reg_write(UC_ARM_REG_R0,xy[0]|xy[1]<<16)
        cpu.reg_write(UC_ARM_REG_R1,work);cpu.reg_write(UC_ARM_REG_R2,control)
        cpu.emu_start(0x257629,stop,count=100000)
        assert cpu.reg_read(UC_ARM_REG_PC)==stop and cpu.reg_read(UC_ARM_REG_SP)==work+0xff000
        packed=cpu.reg_read(UC_ARM_REG_R0)
        return ([packed&65535,packed>>16],bytes(cpu.mem_read(trace+0x3a4,0x24)).hex())
    counts={m:dict(output=0,trace=0) for m in range(3)};rows=[]
    for xy,metric,gate,branch,mode in itertools.product(
        [(10451,29051),(11284,26344),(9686,32001),(8192,40000),(14000,23000),(18000,12000),(16384,16384)],
        [0,1500,3000,12000],[0,256],[0,1],[0,1,2]):
        before=run(cp,prop,mode,xy,metric,gate,branch)
        reference=run(cp,changed_prop,mode,xy,metric,gate,branch)
        after=run(changed_cp,prop,mode,xy,metric,gate,branch)
        assert after==reference
        if mode==0:assert before==after
        counts[mode]['output']+=before[0]!=after[0];counts[mode]['trace']+=before[1]!=after[1]
        rows.append(dict(mode=mode,input=xy,metric=metric,gate=gate,branch=branch,before=before,after=after))
    assert counts[1]['output'] and counts[2]['output']
    (tmp_path/'awb-native.private.json').write_text(json.dumps(dict(camera_io=False,native_helper_stubs=False,
        physical_color_validated=False,cases=len(rows),counts=counts,rows=rows),indent=2))
