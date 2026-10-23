"""Original priority-to-channel and worker queue slices, strictly offline.

Independent states stop before queue, wake, send and scheduler services. These
fragments do not prove delivery on a live channel or lifetime after a reply.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM
from unicorn import arm64_const as R
from support.kernel import Module,UIPC_SHA,PCIE_SHA
from support.boundaries import BoundaryRunner
from support.memory import MEM,STACK,STOP


def audit(uipc,pcie):
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    a=Module(u,uipc,UIPC_SHA,0x10000000);b=Module(u,pcie,PCIE_SHA,0x18000000)
    for address,size in ((MEM,65536),(STACK,65536),(STOP,4096)):u.mem_map(address,size)
    A=lambda at:a.at('.text',at)
    B=lambda at:b.at('.text',at)
    run=BoundaryRunner(u,(a,b),stop=STOP,stack=STACK)
    getq=lambda at:struct.unpack('<Q',bytes(u.mem_read(at,8)))[0]
    putq=lambda at,value:u.mem_write(at,struct.pack('<Q',value))
    getw=lambda at:struct.unpack('<I',bytes(u.mem_read(at,4)))[0]
    message,out,frame=MEM+0x1000,MEM+0x2000,STACK+0x8000
    assert a.functions['osal_get_msg_pri']==(A(0x4ce0),40)
    assert b.calls[B(0x3618)]=='osal_get_msg_pri'
    cases=[]
    for encoded in (0,1,4,0x3f,0x41,0x44,0x81,0xc1,0xff):
        u.mem_write(message-15,bytes([encoded]));u.mem_write(out,b'\xa5'*4)
        got=run.call(A(0x4ce0),(message,out))
        assert got['at']==STOP and got['args'][0]==0 and getw(out)==encoded&63
        cases.append(dict(case='original-priority-getter',encoded_header_byte=encoded,priority=encoded&63))
    # Header0x41 in the already physically exercised context packet has priority1.
    for priority in range(5):
        putq(B(0x3be8),MEM+0x3000);u.mem_write(MEM+0x3000,bytes(4))
        u.mem_write(frame+0x60,struct.pack('<I',priority))
        got=run.run(B(0x361c),inputs=[(R.UC_ARM64_REG_X0,0),(R.UC_ARM64_REG_X19,message),
            (R.UC_ARM64_REG_X29,frame),(R.UC_ARM64_REG_SP,frame)])
        assert got['call']=='osal_stat_msgq'
        channel=u.reg_read(R.UC_ARM64_REG_X22)
        assert channel==int(priority==4) and u.reg_read(R.UC_ARM64_REG_X28)==4+channel
        cases.append(dict(case='independent-post-priority-getter',priority=priority,channel=channel,
            statistics_called=False,send_called=False))
    root=getq(B(0x32e0));worker_pools=[MEM+0x4000,MEM+0x5000]
    for index in (0,1):putq(root+0x1e0+index*56,worker_pools[index])
    worker_args=[]
    for index in (0,1):
        got=run.call(B(0x3160),(index,))
        assert got['call']=='pcieif_wait_exec' and got['args'][0]==root+0x200+index*56
        queue=worker_pools[index]+0x88
        assert u.reg_read(R.UC_ARM64_REG_X23)==queue
        worker_args.append(queue)
        cases.append(dict(case='worker-entry-before-wait',worker_index=index,
            pool_slot_offset=0x1e0+index*56,completion_object_offset=0x88,wait_called=False))
        got=run.run(B(0x3210),(B(0x2210),),[(R.UC_ARM64_REG_X23,queue)])
        assert got['at']==B(0x2210) and got['args'][0]==queue
        u.mem_write(queue,struct.pack('<I',index*2))
        got=run.call(B(0x2210),(queue,))
        assert got['call']=='pcieif_queue_is_empty' and got['args'][0]==queue+0x48
        assert u.reg_read(R.UC_ARM64_REG_X24)==index
        cases.append(dict(case='independent-worker-to-completion-queue',worker_index=index,
            queue_empty_or_dequeue_called=False))
    # Separate post-dequeue input: a stack context is passed into wakeup.
    # Neither a dequeue result nor arch_phys_to_va completion is fabricated.
    for pointer in (0,MEM+0x7000):
        putq(message-64+0x18,pointer)
        u.mem_write(frame+0x74,struct.pack('<I',0))
        got=run.run(B(0x2268),inputs=[(R.UC_ARM64_REG_X0,message),(R.UC_ARM64_REG_X29,frame)])
        assert got['call']==('pcieif_sleep_wakeup' if pointer else 'osal_free_msg')
        if pointer:assert got['args'][0]==pointer
        cases.append(dict(case='independent-completion-dispatch',stack_context_present=bool(pointer),
            boundary=got['call'],wake_or_free_called=False))
    return dict(schema='OFFLINE_SYNC_COMPLETION_ROUTE/1',camera_io=False,UIPC_sha256=UIPC_SHA,PCIe_sha256=PCIE_SHA,
        cases=cases,physical_test_header_priority=1,priority4_selects_RT_channel=True,
        original_worker_indices=[0,1],
        limits=['All object/pool/queue pointers and post-service values are synthetic',
            'Header priority1 supports a channel0 hypothesis only when the actual sender/header remain qualified',
            'Worker entry and incoming completion routing still need end-to-end linkage',
            'Live worker scheduling metadata does not identify loaded kernel code or prove CP receipt',
            'A same-CPU scheduling strategy needs a separately reviewed child and actual preemption contract',
            'No affinity change, scheduler service, send, CP callback, RAM patch or physical pre-capture executes'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('uipc-kernel','pcie','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();result=audit(args.uipc_kernel.read_bytes(),args.pcie.read_bytes())
    with args.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(len(result['cases']),'original priority/worker/completion slices; no native service or camera I/O')


if __name__=='__main__':main()
