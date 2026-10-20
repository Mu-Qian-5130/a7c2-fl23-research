"""Original AP polling and CP reply-route evidence on synthetic memory only.

No queue is created; no native lock/copy/send/free or CP query executes.
An asynchronous reply channel still needs real context, ownership and exit
validation; the synchronous24-byte mutation observer is not such a channel.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from types import SimpleNamespace

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn import arm64_const as R
from unicorn import arm_const as C
from support.kernel import Module, UIPC_SHA, PCIE_SHA
from support.uipc import library, LIBRARY_SHA
from support.reference import SPECS
from support.boundaries import BoundaryRunner
from support.memory import MEM, STACK

STOP, CP_BASE, OWN_ID = 0x50000000, 0x108000, 0x803f6111


def audit(kernel_raw, library_path, cp, pcie=None):
    if hashlib.sha256(cp).hexdigest() != SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Exact original target CP required')
    # Each fixture uses an independent CPU. No uconf or native driver is live.
    lib, plt = library(library_path)
    lib.mem_map(STOP,4096)
    lrun = BoundaryRunner(lib,[SimpleNamespace(calls={plt['ioctl']:'ioctl',
        plt['__errno_location']:'errno'})],stop=STOP,stack=STACK)
    output=MEM+0x300
    got=lrun.call(0x3c60,(OWN_ID,output,0))
    assert got['call']=='ioctl' and got['args'][:2]==[77,0xffffffff80000007]
    outer=got['args'][2]
    assert struct.unpack('<I',bytes(lib.mem_read(outer,4)))[0]==OWN_ID
    inner=struct.unpack('<Q',bytes(lib.mem_read(outer+8,8)))[0]
    assert struct.unpack('<QI',bytes(lib.mem_read(inner,12)))==(output,0)
    # Independent post-ioctl input: the original wrapper retries busy forever.
    frame=lib.reg_read(R.UC_ARM64_REG_X29)
    got=lrun.run(0x3c9c,inputs=[(R.UC_ARM64_REG_X0,-1021),
        (R.UC_ARM64_REG_X19,MEM),(R.UC_ARM64_REG_X20,outer),
        (R.UC_ARM64_REG_X29,frame)])
    assert got['call']=='ioctl'
    wire=dict(command='0x80000007',argument_bytes=16,receive_argument_bytes=16,
        timeout=0,wrapper_retries_status=-1021,native_ioctl=False)

    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    m=Module(u,kernel_raw,UIPC_SHA,0x10000000)
    for at,size in ((MEM,0x20000),(STACK,0x10000),(STOP,4096)):
        u.mem_map(at,size)
    A=lambda n:m.at('.text',n)
    run=BoundaryRunner(u,(m,),stop=STOP,stack=STACK)
    q=lambda at,v:u.mem_write(at,struct.pack('<Q',v))
    getq=lambda at:struct.unpack('<Q',bytes(u.mem_read(at,8)))[0]
    assert getq(m.at('.rodata',0x3d8))==A(0xfd0)
    frame,owner,queue,node,out=STACK+0x8000,MEM+0x1000,MEM+0x2000,MEM+0x3000,MEM+0x4000
    u.mem_write(frame+0x38,bytes(4))
    got=run.run(A(0x1024),inputs=[(R.UC_ARM64_REG_X20,OWN_ID),(R.UC_ARM64_REG_X29,frame)])
    assert got['call']=='osal_rcv_msg_tmo' and got['args'][:3]==[OWN_ID,frame+0x20,0]
    got=run.call(A(0x3bf8),(OWN_ID,node+24),(A(0x2938),))
    assert got['at']==A(0x2938) and got['args'][0]==OWN_ID&0xffff
    routing=dict(AP_own_ID_dispatch='local queue lookup',lookup_or_send_executed=False)

    empty=[]
    for flags,initial in ((0,0),(2,0),(8,0),(8,0xdeadbeef)):
        u.mem_write(queue,bytes(64));u.mem_write(queue,bytes([flags]));q(out,initial)
        q(queue+0x38,MEM+0x5000)
        before=bytes(u.mem_read(queue,64))
        got=run.run(A(0x4234),inputs=[(R.UC_ARM64_REG_X19,queue),
            (R.UC_ARM64_REG_X22,out),(R.UC_ARM64_REG_X23,0)])
        assert got['call']=='osal_unlock' and got['at']==A(0x4264)
        assert u.reg_read(R.UC_ARM64_REG_X21)&0xffffffff==(-1022&0xffffffff)
        assert getq(out)==initial and bytes(u.mem_read(queue,64))==before
        empty.append(dict(flags=flags,initial_output=hex(initial),status=-1022,
            output_untouched=True,wait_node_or_schedule=False,lock_executed=False))
    # Contrast with nonzero timeout; stop BEFORE even its current-task read.
    got=run.run(A(0x4288),(A(0x42b8),),inputs=[(R.UC_ARM64_REG_X19,queue),
        (R.UC_ARM64_REG_X22,out),(R.UC_ARM64_REG_X23,1),
        (R.UC_ARM64_REG_X29,frame)])
    assert got['at']==A(0x42b8) and getq(out)==0

    received=[]
    for next_node in (0,MEM+0x7000):
        u.mem_write(queue,bytes(64));u.mem_write(queue,b'\x08')
        q(queue+0x10,node);q(queue+0x38,MEM+0x5000);q(node,next_node);q(out,0)
        before=bytes(u.mem_read(node,64))
        got=run.run(A(0x4234),inputs=[(R.UC_ARM64_REG_X19,queue),
            (R.UC_ARM64_REG_X22,out),(R.UC_ARM64_REG_X23,0)])
        assert got['at']==A(0x4264) and got['call']=='osal_unlock'
        assert getq(out)==node+24 and getq(queue+0x10)==next_node
        assert bytes(u.mem_read(node,64))==before and u.reg_read(R.UC_ARM64_REG_X21)==0
        received.append(dict(next_node=bool(next_node),returned_payload_offset=24,
            node_bytes_unchanged=True,refcount_free_or_lock_executed=False))

    # Command7 frees a dequeued message if copying its pointer to user fails.
    # Caller must never infer ownership or attempt another free on that error.
    q(frame+0x20,node+24)
    got=run.run(A(0x10b4),inputs=[(R.UC_ARM64_REG_X0,1),
        (R.UC_ARM64_REG_X20,OWN_ID),(R.UC_ARM64_REG_X29,frame)])
    assert got['call']=='osal_free_msg' and got['args'][:2]==[OWN_ID,node+24]
    copy_failure=dict(reaches_free_with_receive_ID=True,free_executed=False)

    incoming=[]
    if pcie is not None:
        b=Module(u,pcie,PCIE_SHA,0x18000000);B=lambda n:b.at('.text',n)
        receive=BoundaryRunner(u,(m,b),stop=STOP,stack=STACK)
        metadata,device,payload,receiver=MEM+0x8000,MEM+0x10000,MEM+0x6000,MEM+0x9000
        u.mem_write(metadata+8,struct.pack('<3I',32,OWN_ID,0x90030001))
        u.mem_write(device+0x3ce4,bytes(4))
        q(receiver+0x28,device)
        # Independent post-dequeue ring inputs. Start before the original
        # wait0 MOV, rather than inheriting x3 from an unrelated earlier slice.
        got=receive.run(B(0xc78),inputs=[(R.UC_ARM64_REG_X21,metadata),
            (R.UC_ARM64_REG_X19,receiver),(R.UC_ARM64_REG_X5,device),
            (R.UC_ARM64_REG_X0,0),(R.UC_ARM64_REG_X2,0x84210843),
            (R.UC_ARM64_REG_X29,frame)])
        assert got['call']=='osal_valloc_msg_wait' and got['args']==[OWN_ID,frame+0xa8,32,0],got
        incoming.append(dict(kind='incoming-AP-allocation',route=hex(OWN_ID),bytes=32,wait=0,native_allocate=False))
        # Independent post-allocation inputs; no successful allocator is fed
        # to the earlier slice. Source is copied from original RX metadata.
        q(frame+0xa8,payload)
        got=receive.run(B(0xcf0),inputs=[(R.UC_ARM64_REG_X29,frame)])
        assert got['call']=='osal_set_msg_src' and got['args'][:2]==[payload,0x90030001]
        incoming.append(dict(kind='incoming-source-field',source='0x90030001',native_setter=False))
        got=receive.run(B(0xdd8),inputs=[(R.UC_ARM64_REG_X29,frame),(R.UC_ARM64_REG_X23,OWN_ID)])
        assert got['call']=='osal_snd_msg' and got['args'][:2]==[OWN_ID,payload]
        incoming.append(dict(kind='incoming-destination-queue',route=hex(OWN_ID),native_enqueue=False))

    # Original CP peer routing: domain1 is local on CP; domain0 is local on AP.
    c=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    c.mem_map(CP_BASE,(len(cp)+4095)&~4095);c.mem_write(CP_BASE,cp)
    for at,size in ((MEM,0x10000),(STACK,0x10000),(STOP,4096),(0x1a7e000,4096)):
        c.mem_map(at,size)
    c.mem_write(0x1a7e968,struct.pack('<I',MEM+0x1000))
    c.mem_write(MEM+0x1000,struct.pack('<I',0x60000001))
    boundaries={CP_BASE+0x45cc6a,0xbeb99a,CP_BASE+0xa18bce,STOP}
    seen=[]
    def stop(cpu,at,size,_):
        if at in boundaries:seen.append(at);cpu.emu_stop()
    c.hook_add(UC_HOOK_CODE,stop)
    def call(at,args):
        seen.clear()
        for reg,value in zip((C.UC_ARM_REG_R0,C.UC_ARM_REG_R1,C.UC_ARM_REG_R2),args):
            c.reg_write(reg,value)
        c.reg_write(C.UC_ARM_REG_SP,STACK+0x8000);c.reg_write(C.UC_ARM_REG_LR,STOP|1)
        c.emu_start((CP_BASE+at)|1,0xffffffff,count=200)
        assert len(seen)==1 and c.reg_read(C.UC_ARM_REG_PC)==seen[0]
        return seen[0]
    peer=[]
    for route,local in ((OWN_ID,False),(0x903f6111,True),(0x90030001,True),(0x80030001,False)):
        got=call(0x45cb38,(route,MEM+0x2000))
        assert got==(0xbeb99a if local else CP_BASE+0x45cc6a)
        if not local:
            assert c.reg_read(C.UC_ARM_REG_R0)==route and c.reg_read(C.UC_ARM_REG_R1)==MEM+0x2000
        peer.append(dict(destination=hex(route),CP_local=local,peer_service_executed=False))
    filters=[]
    for origin,forward in ((OWN_ID,True),(0x80bf6111,False),(0x80dc6111,False)):
        got=call(0x7d2a14,(MEM+0x2000,12,origin))
        assert got==(CP_BASE+0xa18bce if forward else STOP)
        filters.append(dict(origin=hex(origin),reply_header_helper_reached=forward,native_send=False))

    result=dict(schema='OFFLINE_ASYNC_REPLY_QUEUE_SOURCE_EVIDENCE/1',camera_io=False,
        uipc_sha256=UIPC_SHA,library_sha256=LIBRARY_SHA,CP_sha256=SPECS['a7c2-2.01']['sha256'],
        wire=wire,AP_routing=routing,empty=empty,received=received,
        copy_failure=copy_failure,CP_peer_routing=peer,CP_reply_filter=filters,
        live_channel_proven=False,
        limits=[
            'Every queue/message/post-call value is an independent synthetic input',
            'Fresh context ID provenance, actual receive and message validation/release remain unverified',
            'Clear output before every poll; empty status leaves any old pointer untouched',
            'Use a one-attempt raw ioctl; the native library wrapper can retry busy without bound',
            'Polling timeout is not remote cancellation; pending traffic requires continued context ownership',
            'No CP request handler emits a new diagnostic reply in this implementation',
            'The old synchronous mutation observer cannot be reused as an asynchronous reply protocol',
            'No native service, CP query, firmware modification or physical pre-capture executes'])
    if pcie is not None:
        result['pcie_sha256']=PCIE_SHA;result['incoming_reply_route']=incoming
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('uipc-kernel','uipc','cp','output'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--pcie',type=Path,help='Also check original incoming allocation/source/enqueue slices')
    a=p.parse_args();report=audit(a.uipc_kernel.read_bytes(),a.uipc,a.cp.read_bytes(),
        a.pcie.read_bytes() if a.pcie else None)
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print('Original AP nonwaiting receive and CP peer reply routes checked; no live reply channel or camera operation.')


if __name__=='__main__':main()
