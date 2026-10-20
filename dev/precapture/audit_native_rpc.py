"""Original UIPC owner/map/direct-RPC boundaries on synthetic RAM only.

Stops before native allocation, remap, locking, copying, scheduling and PCIe
services. Independent post-call inputs do not establish actual API success.
No device access, generated firmware or installation exists in this audit.
"""
import argparse
import json
import struct
from pathlib import Path

from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
from unicorn import arm64_const as R
from audit_native_message_route import Module,UIPC_SHA,PCIE_SHA,MEM,STACK,STOP

def audit(uipc,pcie):
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    a=Module(u,uipc,UIPC_SHA,0x10000000);b=Module(u,pcie,PCIE_SHA,0x18000000)
    for at,size in ((MEM,0x40000),(STACK,0x10000),(STOP,4096)):u.mem_map(at,size)
    A=lambda x:a.at('.text',x);B=lambda x:b.at('.text',x)
    calls={**a.calls,**b.calls};boundaries=set();seen=[]
    def hook(cpu,at,size,_):
        if at in calls or at in boundaries:
            seen.append(dict(at=at,call=calls.get(at),args=[cpu.reg_read(r) for r in
                (R.UC_ARM64_REG_X0,R.UC_ARM64_REG_X1,R.UC_ARM64_REG_X2,R.UC_ARM64_REG_X3)]))
            cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook)
    def run(entry,targets=(),inputs=()):
        boundaries.clear();boundaries.update((STOP,*targets));seen.clear()
        for reg,value in inputs:u.reg_write(reg,value&((1<<64)-1))
        u.emu_start(entry,0xffffffffffffffff,count=4000)
        assert len(seen)==1 and u.reg_read(R.UC_ARM64_REG_PC)==seen[0]['at']
        return seen[0]
    def call(entry,args,targets=()):
        return run(entry,targets,[*zip((R.UC_ARM64_REG_X0,R.UC_ARM64_REG_X1,R.UC_ARM64_REG_X2,R.UC_ARM64_REG_X3),args),
            (R.UC_ARM64_REG_SP,STACK+0x8000),(R.UC_ARM64_REG_LR,STOP)])
    def putq(at,value):u.mem_write(at,struct.pack('<Q',value))
    def getq(at):return struct.unpack('<Q',bytes(u.mem_read(at,8)))[0]
    def putw(at,value):u.mem_write(at,struct.pack('<I',value))
    def getw(at):return struct.unpack('<I',bytes(u.mem_read(at,4)))[0]

    owner,task,vma,file=MEM+0x1000,MEM+0x2000,MEM+0x4000,MEM+0x5000
    owner_checks=[]
    # The SAME opaque task field is captured on context creation and checked
    # on ioctl. Never infer its semantic type just from the offset.
    for identity in (0x1122334455667788,0x8877665544332211):
        putq(task+0x2d8,identity)
        got=run(A(0x42c),(A(0x444),),[(R.UC_ARM64_REG_X0,task),(R.UC_ARM64_REG_X19,owner)])
        assert got['at']==A(0x444) and getq(owner+0x28)==identity
        owner_checks.append(dict(kind='context-captures-owner',same_opaque_field='task+0x2d8',identity_preserved=True))
    for match in (False,True):
        putq(owner+0x28,0x12345678);putq(task+0x2d8,0x12345678 if match else 0x87654321)
        got=run(A(0x558),(A(0x568),A(0x590)),[(R.UC_ARM64_REG_X0,task),(R.UC_ARM64_REG_X20,owner)])
        assert got['at']==A(0x568 if match else 0x590)
        owner_checks.append(dict(kind='ioctl-owner-comparison',matched=match,accepted=match))

    info_checks=[]
    dispatch=a.at('.rodata',0x3a0)
    assert getq(dispatch+16*8)==A(0xb50)
    got=call(A(0xb50),(0,MEM+0x6000,owner))
    assert got['at']==A(0xb88) and got['call']=='osal_dynamic_id'
    assert got['args'][:2]==[0x2a,0x3f]
    info_frame=u.reg_read(R.UC_ARM64_REG_SP)
    assert bytes(u.mem_read(info_frame+0x30,16))==struct.pack('<4I',0x200000,0x80000,0x20000,0)
    info_checks.append(dict(kind='initial-context-info',mapping_bytes=0x200000,
        local_heap_bytes=0x80000,aux_bytes=0x20000,dynamic_id_service_executed=False))
    for dynamic_id in (1,7):
        # Independent post-dynamic-id/pre-user-copy slice. No successful
        # allocator, user copy or kernel registration is supplied/executed.
        putw(info_frame+0x3c,dynamic_id)
        got=run(A(0xbd0),inputs=[(R.UC_ARM64_REG_X29,info_frame),(R.UC_ARM64_REG_X20,MEM+0x6000)])
        assert got['at']==A(0xbdc) and got['call']=='__arch_copy_to_user'
        assert got['args'][:3]==[MEM+0x6000,info_frame+0x30,16]
        assert getw(info_frame+0x3c)==dynamic_id
        info_checks.append(dict(kind='info-copy-boundary',synthetic_dynamic_id=dynamic_id,
            output_bytes=16,user_copy_or_registration_executed=False,reply_source_encoding_unproved=True))

    map_checks=[]
    for length in (0x1000,0x1ff000,0x200000,0x201000):
        putq(file+8,MEM+0x5800);putq(MEM+0x5800,owner)
        putq(vma,0x60000000);putq(vma+8,0x60000000+length);putq(vma+0x48,0x1234);putq(owner+0x30,0)
        got=call(A(0xd70),(file,vma),(A(0xd9c),A(0xe20)))
        assert got['at']==A(0xd9c if length==0x200000 else 0xe20)
        map_checks.append(dict(kind='mapping-size',bytes=length,accepted=length==0x200000,remap_executed=False))
    for returned in (0,1):
        # Independent post-remap slice. Explicit result0 is NOT a real remap.
        got=run(A(0xe00),(A(0xe0c),),[(R.UC_ARM64_REG_X0,returned),(R.UC_ARM64_REG_X19,vma),
            (R.UC_ARM64_REG_X20,owner)])
        assert got['at']==A(0xe0c)
        assert getq(owner+0x30)==(0 if returned else 0x60000000)
        map_checks.append(dict(kind='post-remap',synthetic_result=returned,user_base_stored=not returned,remap_executed=False))
        putq(owner+0x30,0)

    # Route5 copies24 bytes and handles callback delegation separately.
    frame=STACK+0x8000;user=0x60000000;native=MEM+0x20000
    root=getq(A(0x13b0));putq(root+0x40,native);putq(owner+0x30,user)
    sync_checks=[]
    for offset in (-1,0,64,0x1fffff,0x200000):
        for callback in (0,0x55667788):
            u.mem_write(frame+0x48,struct.pack('<3Q',user+offset,callback,0))
            got=run(A(0x12f0),(A(0x12c0),A(0x134c),A(0x1324)),[
                (R.UC_ARM64_REG_X0,0),(R.UC_ARM64_REG_X19,owner),(R.UC_ARM64_REG_X21,0x908f084b),
                (R.UC_ARM64_REG_X29,frame),(R.UC_ARM64_REG_SP,frame)])
            valid=0<=offset<0x200000
            expected=A(0x1324 if callback else 0x134c) if valid else A(0x12c0)
            assert got['at']==expected
            if valid:
                assert got['args'][:2]==[0x908f084b,native+offset]
                if not callback:
                    assert got['args'][2:]==[A(0x148),frame+0x38]
            sync_checks.append(dict(kind='direct-sync-message-range',offset=offset,callback_input=bool(callback),
                accepted=valid,delegation_finish=valid and bool(callback),whole_message_extent_checked=False,
                copy_or_sync_executed=False))
    # Post-native return without delegation does not copy user callback data.
    for status in (0,-1024):
        u.mem_write(frame,struct.pack('<2Q',0,STOP));putq(frame+0x40,0)
        got=run(A(0x1350),inputs=[(R.UC_ARM64_REG_X0,status),(R.UC_ARM64_REG_X29,frame),(R.UC_ARM64_REG_SP,frame)])
        assert got['at']==STOP and got['args'][0]&0xffffffff==status&0xffffffff
        sync_checks.append(dict(kind='post-native-no-delegation',synthetic_status=status,copy_to_user_executed=False))

    public=b.at('.data',0xb8);assert getq(public+8)==B(0x3c58)
    pubroot=getq(A(0x4158));putq(pubroot+0x458,public)
    got=call(A(0x3f18),(0x908f084b,native+64,0,0),(B(0x3c58),))
    assert got['at']==B(0x3c58) and got['args'][:2]==[0x908f084b,native+64]
    got=run(B(0x3c58));assert got['at']==B(0x34f8) and u.reg_read(R.UC_ARM64_REG_X20)==1
    sync_checks.append(dict(kind='registered-PCIe-sync-route',callback='0x3c58',common_sender_sync_flag=1,
                            debug_or_PCIe_service_executed=False))

    # Original wait budget is MAX_SCHEDULE_TIMEOUT, not the log DMA's3000.
    context=MEM+0x8000
    got=call(B(0x48e0),(context,))
    assert got['at']==B(0x4910) and u.reg_read(R.UC_ARM64_REG_X20)==0x7fffffffffffffff
    wait_checks=[dict(kind='initial-native-wait-budget',ticks='0x7fffffffffffffff',lock_or_schedule_executed=False)]
    for ready in (0,1):
        putw(context+0x10,ready)
        got=run(B(0x4934),(B(0x4900),B(0x4944)),[(R.UC_ARM64_REG_X19,context),
            (R.UC_ARM64_REG_X20,0x7fffffffffffffff)])
        assert got['at']==B(0x4900 if not ready else 0x4944)
        if not ready:assert got['args'][0]==0x7fffffffffffffff
        wait_checks.append(dict(kind='completion-flag',ready=bool(ready),reaches_schedule=not ready,schedule_executed=False))
    got=run(B(0x4904),(B(0x4910),),[(R.UC_ARM64_REG_X0,0x7fffffffffffffff),(R.UC_ARM64_REG_X19,context)])
    assert got['at']==B(0x4910) and u.reg_read(R.UC_ARM64_REG_X20)==0x7fffffffffffffff
    wait_checks.append(dict(kind='independent-post-schedule',synthetic_remaining='0x7fffffffffffffff',reenters_wait=True))
    return dict(schema='OFFLINE_NATIVE_DIRECT_RPC_BOUNDARIES/1',camera_io=False,uipc_sha256=UIPC_SHA,
        pcie_sha256=PCIE_SHA,owner_checks=owner_checks,info_checks=info_checks,map_checks=map_checks,sync_checks=sync_checks,wait_checks=wait_checks,
        limits=['All task/map/native results are synthetic; no kernel or device API executed',
                'Opaque owner-field semantics and real standalone context initialization are unproved',
                'The direct synchronous PCIe wait has no short deadline; process lifetime must be preserved',
                'No completion fault/cancel contract, CP response, source load or real pre-capture is established'])

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--uipc-kernel',type=Path,required=True);p.add_argument('--pcie',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    report=audit(a.uipc_kernel.read_bytes(),a.pcie.read_bytes())
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2)
    count=sum(len(report[k]) for k in ('owner_checks','info_checks','map_checks','sync_checks','wait_checks'))
    print(f'{count} original owner/map/direct-RPC/wait boundary slices; no kernel or camera operations.')
if __name__=='__main__':main()
