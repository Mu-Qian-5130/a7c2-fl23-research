"""Original empty-UIPC-context init/cleanup slices on synthetic RAM only.

All native copy/ID/lock/callback/free APIs stop before execution. Post-call
slices are independent explicit metadata inputs, never successful API mocks.
No connection, device FD, map, IPC message or firmware output is created.
"""
import argparse,json,struct
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM
from unicorn import arm64_const as R
from support.kernel import Module,UIPC_SHA
from support.boundaries import BoundaryRunner
from support.uipc import library,original_header,LIBRARY_SHA

MEM,STACK,STOP=0x30000000,0x40000000,0x50000000


def audit(raw,native_library):
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);m=Module(u,raw,UIPC_SHA,0x10000000)
    for at,size in ((MEM,0x20000),(STACK,0x10000),(STOP,4096)):u.mem_map(at,size)
    A=lambda offset:m.at('.text',offset)
    runner=BoundaryRunner(u,[m],stop=STOP,stack=STACK)
    def q(at,value):u.mem_write(at,struct.pack('<Q',value))
    def w(at,value):u.mem_write(at,struct.pack('<I',value))
    def readq(at):return struct.unpack('<Q',bytes(u.mem_read(at,8)))[0]
    def readw(at):return struct.unpack('<I',bytes(u.mem_read(at,4)))[0]
    owner=MEM+0x1000

    # Kernel UAPI16 creates a user queue ID before copying16 bytes out.
    got=runner.call(A(0xb50),(0,MEM+0x4000,owner))
    assert got['at']==A(0xb88) and got['call']=='osal_dynamic_id' and got['args'][:2]==[0x2a,0x3f]
    frame=u.reg_read(R.UC_ARM64_REG_SP);saved_frame=bytes(u.mem_read(frame,64))
    init=[]
    for ident in (0,0x803f6111):
        u.mem_write(frame,saved_frame);w(frame+0x3c,ident)
        u.reg_write(R.UC_ARM64_REG_SP,frame);u.reg_write(R.UC_ARM64_REG_X29,frame)
        got=runner.run(A(0xbb0),inputs=[(R.UC_ARM64_REG_X20,-22)])
        assert got['at']==(A(0xc4c) if ident else STOP)
        if ident:assert got['args'][:3]==[0x4a,0,ident]
        else:assert got['args'][0]&0xffffffff==(-22&0xffffffff)
        init.append(dict(kind='independent-invalid-user-output-range',synthetic_ID=hex(ident),
                         reaches_ID_release=bool(ident),ID_release_executed=False))
    for remaining in (0,1):
        u.mem_write(owner,bytes(256));u.mem_write(frame,saved_frame);w(frame+0x3c,0x803f6111)
        got=runner.run(A(0xbe0),(A(0xbf0),A(0xc4c)),inputs=[(R.UC_ARM64_REG_X0,remaining),
            (R.UC_ARM64_REG_X19,owner),(R.UC_ARM64_REG_X29,frame),(R.UC_ARM64_REG_SP,frame)])
        assert got['at']==A(0xc4c if remaining else 0xbf0)
        if remaining:assert got['args'][:3]==[0x4a,0,0x803f6111] and readw(owner+0x64)==0
        else:assert readw(owner+0x64)==1 and readw(owner+0x68)==0x803f6111
        init.append(dict(kind='independent-post-copy',synthetic_uncopied_bytes=remaining,
            ID_attached_to_owner=not remaining,copy_ID_release_or_MRS_executed=False))

    # The actual dynamic-ID prefix selects the queue arena, not the semaphore
    # path, for operation2a/type3f. Stop before taking its native lock.
    got=runner.call(A(0x5780),(0x2a,0x3f,MEM+0x6000))
    assert got['at']==A(0x57f0) and got['call']=='osal_lock'
    dynamic_root=readq(A(0x5cf8))
    assert got['args'][0]==dynamic_root+0x40
    id_cases=[];table=MEM+0x7000;queue=MEM+0x8000;bitmap=MEM+0x9000;out=MEM+0x6000;frame=STACK+0x8000
    for queue_id,flags in ((0x6001,0),(0x6111,0),(0x6111,1)):
        u.mem_write(queue,bytes(64));u.mem_write(bitmap,bytes(64));q(table+0x18,bitmap)
        w(frame+0x6c,0x003f0000);w(frame+0x88,0);q(frame+0x90,0);q(frame+0x70,0);q(frame+0x80,0x12345678)
        u.mem_write(queue,bytes([flags]))
        got=runner.run(A(0x5b28),inputs=[(R.UC_ARM64_REG_X25,out),(R.UC_ARM64_REG_X28,queue_id),
            (R.UC_ARM64_REG_X3,queue),(R.UC_ARM64_REG_X20,table),(R.UC_ARM64_REG_X22,table),
            (R.UC_ARM64_REG_X23,queue_id&63),(R.UC_ARM64_REG_X29,frame)])
        assert got['at']==A(0x58cc) and got['call']=='osal_unlock'
        assert readw(out)==0x803f0000|queue_id and readq(queue+0x30)==0x003f0000|queue_id
        id_cases.append(dict(synthetic_queue_index=hex(queue_id),native_returned_ID=hex(readw(out)),
            queue_storage_ID=hex(readq(queue+0x30)),lock_or_queue_services_executed=False))

    release=[]
    for registered,heap in ((0,0),(1,0),(0,MEM+0xa000)):
        u.mem_write(owner,bytes(256));w(owner+0x64,registered);w(owner+0x68,0x803f6111);q(owner+0x40,heap)
        got=runner.call(A(0x2b8),(owner,))
        assert got['at']==A(0x2dc) and got['call']=='delete_cbs' and got['args'][1]==owner
        # Independent post-delete input: this fresh context has no registered
        # callbacks and no messages have been issued. Do not model delete.
        got=runner.run(A(0x2e0))
        expected=0x31c if heap else 0x334 if registered else 0x374
        assert got['at']==A(expected)
        assert got['call']==('vfree' if heap else 'mutex_lock' if registered else 'kfree')
        release.append(dict(registered=bool(registered),synthetic_callback_heap=bool(heap),
            empty_slots=4,next_service=got['call'],delete_free_or_lock_executed=False))
    got=runner.run(A(0x360),inputs=[(R.UC_ARM64_REG_X20,owner)])
    assert got['at']==A(0x36c) and got['args'][:3]==[0x4a,0,0x803f6111]
    release.append(dict(kind='independent-post-list-removal',native_ID_release_arguments=['0x4a',0,'0x803f6111'],
                        ID_release_executed=False))

    # The cancel-only client's message is a newly allocated16-byte AP-side
    # packet. Use the original constructor fixture and stop BEFORE refcount
    # atomics and native free. No free success is invented.
    header,_=original_header(raw,native_library.read_bytes())
    block=MEM+0xb000;payload=block+64;queue=MEM+0xc000
    u.mem_write(block,header);u.mem_write(queue,bytes(64))
    queue_root=readq(A(0x47a8));q(queue_root+0x18,queue)
    got=runner.call(A(0x4650),(0x90030001,payload),(A(0x46ac),))
    assert got['at']==A(0x46ac) and got['args'][1]==payload-24
    free_slices=[]
    for dedicated in (False,True):
        pool=MEM+0xd000;q(queue+0x30,pool if dedicated else 0)
        # Independent input after both refcount operations; they did NOT run.
        got=runner.run(A(0x46ec),inputs=[(R.UC_ARM64_REG_X6,queue),
            (R.UC_ARM64_REG_X5,payload),(R.UC_ARM64_REG_X1,payload-24)])
        assert got['at']==A(0x4720 if dedicated else 0x4768) and got['call']=='vpool_free'
        assert got['args'][1:3]==[block,128]
        if dedicated:assert got['args'][0]==pool
        free_slices.append(dict(synthetic_dedicated_pool=dedicated,original_allocated_block_bytes=128,
            reaches_local_pool_free=True,refcount_or_pool_service_executed=False))

    # Original userspace initialization failure unmaps its shared mapping
    # before closing its own device descriptor. Each stops at the real PLT.
    lib,entries=library(native_library);lib_stop=0x20000000
    lib_runner=BoundaryRunner(lib,[type('Calls',(),{'calls':{entries['munmap']:'munmap',entries['close']:'close'}})()],
        stop=lib_stop,stack=STACK)
    lib.mem_write(MEM,struct.pack('<I',77));lib.mem_write(MEM+8,struct.pack('<Q',0x62000000));lib.mem_write(MEM+0x10,struct.pack('<I',0x200000))
    got=lib_runner.run(0x3648,inputs=[(R.UC_ARM64_REG_X22,0x19000)])
    assert got['call']=='munmap' and got['args'][:2]==[0x62000000,0x200000]
    got=lib_runner.run(0x3658,inputs=[(R.UC_ARM64_REG_X22,0x19000)])
    assert got['call']=='close' and got['args'][0]==77

    # The original stats return four counters/flags, but NOT queue+2's
    # outstanding allocation references. Empty FIFO alone is insufficient.
    queue,stats,nodes=MEM+0x10000,MEM+0x11000,MEM+0x12000
    stats_cases=[]
    for queued,waiters,callback,refs in ((0,0,0,0),(2,0,0,0),(0,2,0,0),
                                       (0,0,1,0),(0,0,0,1)):
        u.mem_write(queue,bytes(64));u.mem_write(stats,bytes(16));u.mem_write(nodes,bytes(256))
        u.mem_write(queue+2,struct.pack('<h',refs))
        q(queue+0x10,nodes if queued else 0)
        if queued:q(nodes,nodes+32);q(nodes+32,0)
        q(queue+8,nodes+64 if waiters else 0)
        if waiters:q(nodes+64,nodes+96);q(nodes+96,0)
        q(queue+0x28,nodes+128 if callback else 0);q(queue+0x38,MEM+0x13000)
        got=runner.run(A(0x3194),inputs=[(R.UC_ARM64_REG_X19,stats),(R.UC_ARM64_REG_X20,queue)])
        assert got['at']==A(0x3200) and got['call']=='osal_unlock'
        observed=struct.unpack('<4I',bytes(u.mem_read(stats,16)))
        assert observed==(queued,waiters,0,callback)
        stats_cases.append(dict(queued=queued,waiters=waiters,callback=callback,
            outstanding_refs=refs,reported=list(observed),lock_or_native_stats_executed=False))

    # Independent post-stats inputs: ID release warns about pending objects,
    # but its separate post-warning tail STILL clears identity and bitmap.
    # Never use close as a cancellation/drain operation for pending traffic.
    arena,bitmap=MEM+0x14000,MEM+0x15000;frame=STACK+0x8000;index=0x6111;base=0x6100
    release_checks=[]
    for queued,waiters,callback,refs in ((0,0,0,0),(1,0,0,0),(0,1,0,0),
                                       (0,0,1,0),(0,0,0,1)):
        u.mem_write(queue,bytes(64));q(queue+0x30,0x003f6111)
        u.mem_write(queue+2,struct.pack('<h',refs))
        q(queue+0x10,nodes if queued else 0);q(queue+8,nodes+64 if waiters else 0)
        q(queue+0x28,nodes+128 if callback else 0)
        pending_links=[readq(queue+n) for n in (8,0x10,0x28)]
        u.mem_write(frame+0x90,struct.pack('<4I',queued,waiters,0,callback))
        got=runner.run(A(0x5990),(A(0x59b0),),inputs=[(R.UC_ARM64_REG_X23,queue),
            (R.UC_ARM64_REG_X29,frame),(R.UC_ARM64_REG_X25,0x803f6111)])
        warns=bool(queued or waiters or callback or refs)
        assert got['at']==(A(0x5c7c) if warns else A(0x59b0))
        if warns:assert got['call']=='printk'
        assert readq(queue+0x30)==0x003f6111
        w(arena+0x10,base);q(arena+0x18,bitmap);q(bitmap,1<<(index-base))
        # Do not mock printk success or native ID release. Execute only the
        # explicit after-warning mutation fragment up to the unlock service.
        got=runner.run(A(0x5c80 if warns else 0x59b0),inputs=[
            (R.UC_ARM64_REG_X23,queue),(R.UC_ARM64_REG_X20,arena),
            (R.UC_ARM64_REG_X21,index),(R.UC_ARM64_REG_X22,arena)])
        assert got['at']==A(0x5a34) and got['call']=='osal_unlock'
        assert readq(queue+0x30)==0 and readq(bitmap)==0
        assert [readq(queue+n) for n in (8,0x10,0x28)]==pending_links
        assert struct.unpack('<h',bytes(u.mem_read(queue+2,2)))[0]==refs
        release_checks.append(dict(queued=queued,waiters=waiters,callback=callback,
            outstanding_refs=refs,reaches_warning=warns,independent_tail_clears_ID=True,
            pending_links_and_refs_not_drained=True,
            native_logging_lock_ID_release_executed=False))
    return dict(schema='OFFLINE_EMPTY_IPC_CONTEXT_LIFETIME/1',camera_io=False,
        kernel_module_sha256=UIPC_SHA,native_library_sha256=LIBRARY_SHA,
        init_failure_slices=init,user_queue_ID_slices=id_cases,empty_release_slices=release,
        cancel_free_slices=free_slices,
        original_queue_stats_slices=stats_cases,ID_release_pending_checks=release_checks,
        original_user_failure_cleanup=['munmap-before-close'],
        limits=['All ranges, IDs, callback slots and post-service states are explicit synthetic inputs',
            'No native ID allocator/copy/lock/callback/heap/map/close or current-task read executes',
            'Empty-context cleanup cannot be generalized to in-flight or unknown message ownership',
            'Stats omit outstanding references; nonempty ID release warns and still clears the ID',
            'Successful close/empty stats/matched reply do not independently prove peer quiescence',
            'Returned user queue ID grammar is original-instruction evidence, not a real new standalone ID',
            'No actual exec/context, CP reply, camera safety or pre-capture acceptance is established'])


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--uipc-kernel',type=Path,required=True)
    p.add_argument('--uipc',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    report=audit(a.uipc_kernel.read_bytes(),a.uipc)
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print('Empty native context: init/ID/release and original unmap-before-close boundaries; no live operation.')
if __name__=='__main__':main()
