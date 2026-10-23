"""Original priority-to-channel and worker queue slices, strictly offline.

Independent states stop before queue, wake, send and scheduler services. These
fragments do not prove delivery on a live channel or lifetime after a reply.
"""
import argparse
import json
from pathlib import Path
import struct

from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_MEM_READ
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
    for index in (0,1):
        got=run.call(B(0x3160),(index,))
        assert got['call']=='pcieif_wait_exec' and got['args'][0]==root+0x200+index*56
        queue=worker_pools[index]+0x88
        assert u.reg_read(R.UC_ARM64_REG_X23)==queue
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
    linkage=[]
    # All six original literals independently relocate to the same BSS root.
    # This is stronger than assigning equal synthetic addresses by convention.
    bindings=[]
    for offset in (0x2918,0x2990,0x2a18,0x2d50,0x2f60,0x32e0):
        relocation=b.rel[B(offset)]
        identity=(relocation['section'],relocation['addend'])
        assert relocation['type']==257 and identity==(b.elf.get_section_index('.bss'),0x288)
        bindings.append(dict(text_literal_offset=offset,section='.bss',addend=0x288))
        assert getq(B(offset))==root
    linkage.append(dict(case='six-original-literals-share-relocation',bindings=bindings))
    # Actual source store fragments publish pool0=root and pool1=root+f0.
    got=run.call(B(0x2998),())
    assert got['call']=='pcieif_wait_init'
    assert u.reg_read(R.UC_ARM64_REG_X19)==root and u.reg_read(R.UC_ARM64_REG_X20)==root+0xf0
    got=run.run(B(0x29d8))
    assert got['call']=='pcieif_wait_init' and getq(root+0x1e0)==root
    got=run.run(B(0x2a00))
    assert got['at']==STOP and getq(root+0x218)==root+0xf0
    linkage.append(dict(case='independent-pool-publication-stores',pool_offsets=[0,0xf0],
        slot_offsets=[0x1e0,0x218],locks_wait_init_and_device_init_called=False))
    for channel in (0,1):
        pool=root+channel*0xf0
        # Observe the first and second endpoint initialization independently;
        # translated physical pointers, queue init and locks stay unexecuted.
        got=run.call(B(0x1f90),(pool,channel))
        assert got['call']=='arch_phys_to_va'
        assert u.reg_read(R.UC_ARM64_REG_X19)==pool+0x68
        first_endpoint=getw(pool+0x20)
        assert first_endpoint==2*channel
        translated=MEM+0x8000
        got=run.run(B(0x2004),inputs=[(R.UC_ARM64_REG_X0,translated)])
        assert got['call']=='pcieif_queue_init' and got['args'][0]==pool+0x68
        assert getw(translated+0x1ce0)==1 and getw(translated+0x1ce4)==0
        assert getq(pool+0x48)==translated
        # The next fragment begins AFTER the omitted lock-initialization call.
        got=run.run(B(0x203c),inputs=[(R.UC_ARM64_REG_X19,pool+0xd0)])
        assert got['call']=='arch_phys_to_va'
        assert getw(pool+0x88)==2*channel+1
        linkage.append(dict(case='independent-endpoint-initialization',channel=channel,
            endpoint_indices=[2*channel,2*channel+1],queue_offsets=[0x68,0xd0],
            physical_translation_queue_initialization_or_lock_executed=False))
        # A synchronous send appends to the second endpoint's original list.
        metadata=MEM+0x3000;context=MEM+0x3800
        u.mem_write(metadata+8,struct.pack('<I',24))
        got=run.call(B(0x2c38),(channel,context,metadata))
        assert got['call']=='__udif_cache_ctrl' and getq(metadata+0x18)==context
        got=run.run(B(0x2ca0))
        assert got['call']=='pcieif_add_node' and got['args'][:2]==[pool+0xb8,metadata]
        linkage.append(dict(case='independent-sync-send-list',channel=channel,
            owner_offset=0x68,list_offset=0xb8,cache_enqueue_called=False))
        # IRQ scanner walks first (async) then second (sync) endpoint. Source
        # stores the observed notification flag to0 before a wake service.
        got=run.call(B(0x2dc8),(channel,),targets=(B(0x2e28),))
        assert got['at']==B(0x2e28)
        assert u.reg_read(R.UC_ARM64_REG_X19)==pool+0x48
        assert u.reg_read(R.UC_ARM64_REG_X20)==root+0x1e8+channel*56
        got=run.run(B(0x2e8c),(B(0x2e28),))
        assert got['at']==B(0x2e28)
        assert u.reg_read(R.UC_ARM64_REG_X19)==pool+0xb0
        wait_object=root+0x200+channel*56
        assert u.reg_read(R.UC_ARM64_REG_X20)==wait_object
        # Explicit notify-path entry; the hardware flag is not supplied as a
        # successful device event or executed through its device-read prefix.
        got=run.run(B(0x2e84),inputs=[(R.UC_ARM64_REG_X20,wait_object)])
        assert got['call']=='pcieif_wait_done' and got['args'][0]==wait_object
        got=run.call(B(0x3160),(channel,))
        assert got['call']=='pcieif_wait_exec' and got['args'][0]==wait_object
        assert u.reg_read(R.UC_ARM64_REG_X23)==pool+0x88
        got=run.call(B(0x2210),(pool+0x88,))
        assert got['call']=='pcieif_queue_is_empty' and got['args'][0]==pool+0xd0
        linkage.append(dict(case='independent-IRQ-wake-and-worker-queue',channel=channel,
            sync_device_pointer_offset=0xb0,completion_queue_offset=0xd0,
            notify_and_wait_same_original_object=True,hardware_flag_read_or_wait_wake_dequeue_executed=False))
    # Check the AFTER-wakeup tail separately. It uses cached header values and
    # completion-object storage; touching the old message or caller context
    # would fail even if another expected service boundary is reached.
    tails=[];forbidden=((MEM+0x1000-64,128),(MEM+0x7000,24));accesses=[]
    def no_old_reference(cpu,kind,address,size,value,_):
        assert not any(address<begin+length and begin<address+size for begin,length in forbidden), 'Old message/context read after wake'
        accesses.append((address,size))
    read_hook=u.hook_add(UC_HOOK_MEM_READ,no_old_reference)
    for channel in (0,1):
        obj=MEM+0x6000;device=MEM+0x9000
        putq(obj+0x28,device);u.mem_write(device+4,struct.pack('<I',17))
        debug=getq(B(0x2420));timing=getq(B(0x2440))
        u.mem_write(debug,bytes(4));u.mem_write(timing,bytes(4))
        accesses.clear()
        got=run.run(B(0x2294),inputs=[(R.UC_ARM64_REG_X19,obj),(R.UC_ARM64_REG_X24,channel),
            (R.UC_ARM64_REG_X26,debug),(R.UC_ARM64_REG_X25,timing),
            (R.UC_ARM64_REG_X21,0x908f084b),(R.UC_ARM64_REG_X22,0x80020002),
            (R.UC_ARM64_REG_X29,frame)])
        assert got['call']=='osal_stat_msgq'
        # Independent post-stats success state, not a stub for that service.
        u.mem_write(frame+0x8c,bytes(4))
        got=run.run(B(0x23c0),inputs=[(R.UC_ARM64_REG_X0,0)])
        assert got['call']=='_raw_spin_lock_irqsave' and got['args'][0]==obj+0x60
        u.mem_write(obj+0x20,struct.pack('<I',2))
        got=run.run(B(0x22fc),inputs=[(R.UC_ARM64_REG_X0,0x1234)])
        assert got['call']=='_raw_spin_unlock_irqrestore' and getw(obj+0x20)==1
        assert got['args'][:2]==[obj+0x60,0x1234]
        got=run.run(B(0x2314))
        assert got['call']=='pcieif_get_head' and got['args'][0]==obj+0x30
        got=run.run(B(0x231c),(B(0x2244),),[(R.UC_ARM64_REG_X0,0)])
        assert got['at']==B(0x2244)
        tails.append(dict(case='independent-after-wakeup-tail',channel=channel,
            previous_message_or_wait_context_read=False,next_iteration_boundary_reached=True,
            stats_lock_unlock_queue_or_wake_called=False,data_reads=len(accesses)))
    u.hook_del(read_hook)
    return dict(schema='OFFLINE_SYNC_COMPLETION_ROUTE/1',camera_io=False,UIPC_sha256=UIPC_SHA,PCIe_sha256=PCIE_SHA,
        cases=cases,physical_test_header_priority=1,priority4_selects_RT_channel=True,
        linked_native_storage_slices=linkage,
        independent_after_wakeup_tail_slices=tails,
        original_worker_indices=[0,1],
        limits=['All object/pool/queue pointers and post-service values are synthetic',
            'Header priority1 supports a channel0 hypothesis only when the actual sender/header remain qualified',
            'Source storage/wait-object linkage does not execute DMA, IRQ, remote receipt or completion',
            'Live worker scheduling metadata does not identify loaded kernel code or prove CP receipt',
            'A same-CPU scheduling strategy needs a separately reviewed child and actual preemption contract',
            'No affinity change, scheduler service, send, CP callback, RAM patch or physical pre-capture executes'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('uipc-kernel','pcie','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();result=audit(args.uipc_kernel.read_bytes(),args.pcie.read_bytes())
    with args.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(len(result['cases'])+len(result['linked_native_storage_slices'])+len(result['independent_after_wakeup_tail_slices']),
          'original priority/storage/IRQ/completion slices; no native service or camera I/O')


if __name__=='__main__':main()
