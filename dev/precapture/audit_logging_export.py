"""Original logging gateway slices; no real IPC, DMA, wait or camera access.

Mode0 is rejection, NOT a cached-log read. Mode1 allocates/synchronously
queries CP then starts DMA. Explicit post-operation inputs do not prove any
service completed. A3000-tick DMA wait does not bound allocation/CP query or
prove callback quiescence on return. Provider lifetime remains unresolved.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2,
    UC_ARM64_REG_X3, UC_ARM64_REG_X19, UC_ARM64_REG_X20, UC_ARM64_REG_X21,
    UC_ARM64_REG_X23, UC_ARM64_REG_X24, UC_ARM64_REG_X29,
    UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC)
from audit_native_message_route import Module

SHA = 'f1db304af8fd7c6a208880cc40edd11218a94f02d3b10ddd81aea9a8aa103852'
MEM, STACK, STOP = 0x30000000, 0x40000000, 0x50000000
REQUEST, CP_REQUEST, TASK = MEM+0x1000, MEM+0x2000, MEM+0x3000
CP_LOG, AP_LOG, LOG_BYTES = 0x05000000, 0x405780000, 0x778000


def words(*v):
    return struct.pack('<'+'I'*len(v), *v)


def audit(raw):
    u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    m = Module(u, raw, SHA, 0x10000000)
    for at, size in ((MEM, 0x10000), (STACK, 0x10000), (STOP, 4096)):
        u.mem_map(at, size)
    A = lambda x: m.at('.text', x)
    boundaries, seen = {STOP}, []
    def trace(cpu, at, size, _):
        if at in boundaries or at in m.calls:
            seen.append(dict(at=at, call=m.calls.get(at), args=[cpu.reg_read(r) for r in
                (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3)]))
            cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE, trace)
    def run(entry, targets=(), inputs=()):
        seen.clear();boundaries.clear();boundaries.update((STOP, *(A(x) for x in targets)))
        for r, value in inputs:u.reg_write(r, value & ((1<<64)-1))
        u.emu_start(A(entry), 0xffffffffffffffff, count=1000)
        assert len(seen)==1 and u.reg_read(UC_ARM64_REG_PC)==seen[0]['at']
        return seen[0]
    def call(entry, args):
        return run(entry, inputs=[*zip((UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2), args),
            (UC_ARM64_REG_SP, STACK+0x8000), (UC_ARM64_REG_LR, STOP)])
    def q(at):return struct.unpack('<Q', bytes(u.mem_read(at,8)))[0]
    request=bytearray(b'\xa5'*24);request[0]=0;request[1]=0
    request[8:20]=bytes(12);u.mem_write(REQUEST, bytes(request))
    got=call(0x5a00, ())
    assert got['at']==A(0x5a24) and got['call']=='osal_reg_sync_msg_queue_cb'
    assert got['args'][0]==0x808f084a and got['args'][2]==A(0x5570) and not got['args'][3]
    registration=dict(route='0x808f084a', callback='0x5570', native_registration_executed=False)

    got=call(0x5570, (REQUEST,))
    assert got['at']==STOP and not got['call']
    expected=bytearray(request);expected[1]=0x80
    assert bytes(u.mem_read(REQUEST,24))==bytes(expected)
    mode0=dict(native_external_calls=0, response_status='0x80', address=0, bytes=0, cached_read=False)
    request[0]=1;u.mem_write(REQUEST,bytes(request));u.mem_write(CP_REQUEST,b'\xa5'*24)
    got=call(0x5570,(REQUEST,))
    assert got['at']==A(0x55e0) and got['call']=='osal_valloc_msg_wait'
    assert got['args'][0]==0x908f084b and got['args'][2:]==[24,1]
    frame=u.reg_read(UC_ARM64_REG_X29)
    assert frame==u.reg_read(UC_ARM64_REG_SP)
    u.mem_write(frame+0x58,struct.pack('<Q',CP_REQUEST))
    got=run(0x55ec)
    assert got['at']==A(0x560c) and got['call']=='osal_snd_sync_msg'
    assert got['args'][:2]==[0x908f084b,CP_REQUEST]
    query=bytearray(b'\xa5'*24);query[0]=1;query[1]=0;query[8:20]=bytes(12)
    assert bytes(u.mem_read(CP_REQUEST,24))==bytes(query)
    mode1=dict(cp_route='0x908f084b', query_bytes=24, pool_wait_flag=1,
        allocation_or_sync_query_executed=False, query_from_independent_post_allocation_slice=True)

    # Independent typed CP response: no reply is synthesized for a native
    # service mock. Only original field loads and boundary construction run.
    query[1]=1;struct.pack_into('<Q',query,8,CP_LOG);struct.pack_into('<I',query,16,LOG_BYTES)
    u.mem_write(CP_REQUEST,bytes(query))
    got=run(0x562c,inputs=[(UC_ARM64_REG_X2,CP_REQUEST)])
    assert got['at']==A(0x5640) and got['call']=='osal_free_msg'
    assert got['args'][:2]==[0x908f084b,CP_REQUEST]
    got=run(0x564c)
    assert got['at']==A(0x565c) and got['call']=='ulogio_read_backup'
    assert got['args'][:3]==[0xfa006e,frame+0x50,8]
    assert q(frame+0x50)==0
    # Separate native backup output, not an executed/successful backup API.
    u.mem_write(frame+0x50,struct.pack('<Q',AP_LOG))
    got=run(0x5664)
    assert got['at']==A(0x5690) and got['call']=='pcidma_transfer_async'
    descriptor=bytes(u.mem_read(got['args'][0],40))
    fields=struct.unpack('<4BI4Q',descriptor)
    assert fields==(0,4,0,0,LOG_BYTES,CP_LOG,AP_LOG,A(0x5890),frame+0x4f)
    flag=frame+0x4f
    dma=dict(independent_CP_address=hex(CP_LOG),independent_AP_address=hex(AP_LOG),
        independent_bytes=LOG_BYTES,callback='0x5890',context_storage='caller stack +0x4f',
        descriptor_storage='caller stack +0x60',DMA_executed=False,
        provider_descriptor_copy_or_context_lifetime_established=False)
    got=run(0x5694,inputs=[(UC_ARM64_REG_X0,0)])
    assert got['at']==A(0x56c0) and got['call']=='_raw_spin_lock_irqsave'
    waiter=u.reg_read(UC_ARM64_REG_X19)
    assert u.reg_read(UC_ARM64_REG_X20)==3000
    waits=[]
    for remaining in (3000,17):
        for completed in (0,1,0x82):
            u.mem_write(flag,bytes([completed]))
            got=run(0x56e4,inputs=[(UC_ARM64_REG_X20,remaining),(UC_ARM64_REG_X19,waiter)])
            assert got['at']==A(0x56b0 if not completed else 0x56f4)
            if not completed:
                assert got['call']=='schedule_timeout' and got['args'][0]==remaining
            waits.append(dict(explicit_remaining_ticks=remaining,explicit_flag=completed,
                native_boundary=got['call'],scheduler_or_lock_executed=False))
    for returned in (0,7):
        for completed in (0,1,0x82):
            u.mem_write(flag,bytes([completed]))
            got=run(0x56b4,inputs=[(UC_ARM64_REG_X0,returned),(UC_ARM64_REG_X19,waiter)])
            assert u.reg_read(UC_ARM64_REG_X20)==returned
            assert got['at']==A(0x56f4 if not returned else 0x56c0)
            if not returned:
                assert u.reg_read(UC_ARM64_REG_X23)&0xffffffff==(0xffffffff if not completed else 0)
            waits.append(dict(explicit_post_schedule_result=returned,explicit_flag=completed,
                native_boundary=got['call'],scheduler_or_lock_executed=False))

    # Separate post-current-task read: clear waiter bookkeeping. It never
    # cancels a transfer or changes the descriptor's context pointer.
    u.mem_write(waiter+8,struct.pack('<Q',TASK));u.mem_write(TASK+0x20,struct.pack('<Q',2))
    got=run(0x56fc,inputs=[(UC_ARM64_REG_X0,0xa5),(UC_ARM64_REG_X2,TASK),
        (UC_ARM64_REG_X19,waiter)])
    assert got['at']==A(0x570c) and got['call']=='_raw_spin_unlock_irqrestore'
    assert q(waiter+8)==0 and q(TASK+0x20)==0
    replies=[]
    for name,status,completed in (('complete',0,1),('timeout',0xffffffff,0),('DMA-error',0,0x82)):
        u.mem_write(REQUEST,bytes(request));u.mem_write(flag,bytes([completed]))
        got=run(0x5710,inputs=[(UC_ARM64_REG_X21,REQUEST),(UC_ARM64_REG_X23,status),
            (UC_ARM64_REG_X24,LOG_BYTES),(UC_ARM64_REG_X29,frame),(UC_ARM64_REG_SP,frame)])
        if name=='complete':
            assert got['at']==STOP
            assert bytes(u.mem_read(REQUEST+1,1))==b'\1'
            assert q(REQUEST+8)==AP_LOG and struct.unpack('<I',u.mem_read(REQUEST+16,4))[0]==LOG_BYTES
        else:
            assert got['call']=='printk'
            if name=='DMA-error':run(0x57b0)  # Explicit post-log slice; ignored return.
            assert bytes(u.mem_read(REQUEST+1,1))==b'\x82'
            assert q(REQUEST+8)==0 and bytes(u.mem_read(REQUEST+16,4))==bytes(4)
        replies.append(dict(explicit_post_operation_state=name, response_status='1' if name=='complete' else '0x82',
            response_from_independent_slices=True,actual_DMA_completion=False))

    # This shows what a callback WOULD write with no published waiter. It
    # does not establish that the real provider can call late/on timeout.
    callback_cases=[]
    for completion_status in (0,5):
        u.mem_write(flag,b'\0');u.mem_write(waiter+8,bytes(8))
        got=call(0x5890,(completion_status,flag))
        assert got['at']==A(0x58b4) and got['call']=='_raw_spin_lock_irqsave'
        assert bytes(u.mem_read(flag,1))==(b'\1' if not completion_status else b'\x82')
        got=run(0x58b8,inputs=[(UC_ARM64_REG_X0,0xa5)])
        assert got['at']==A(0x58d0) and got['call']=='_raw_spin_unlock_irqrestore'
        callback_cases.append(dict(synthetic_completion_status=completion_status,published_waiter_present=False,
            context_byte_written_before_lock=True,actual_late_callback_observed=False))
    # Compatibility guard for the proposed DIRECT-CP private response: an
    # accidental request through the old AP log-copy bridge must reject5a,
    # even if its words look like nonzero addresses/lengths. No DMA starts.
    private_request=bytearray(request);private_request[0]=0xe1
    u.mem_write(REQUEST,bytes(private_request))
    got=call(0x5570,(REQUEST,))
    assert got['at']==A(0x55e0)
    private_frame=u.reg_read(UC_ARM64_REG_X29)
    reply=bytearray(24);reply[1]=0x5a
    struct.pack_into('<3I',reply,8,0xa17e1234,0xdeadbeef,0x60000013)
    u.mem_write(CP_REQUEST,bytes(reply));u.mem_write(private_frame+0x58,struct.pack('<Q',CP_REQUEST))
    got=run(0x561c)
    assert got['at']==A(0x57f0) and got['call']=='printk'
    got=run(0x57f4)  # Separate post-log slice; result ignored.
    assert got['at']==A(0x5800) and got['call']=='osal_free_msg'
    got=run(0x57cc)  # Separate post-free slice; result ignored.
    assert got['at']==A(0x57e4) and got['call']=='printk'
    assert bytes(u.mem_read(REQUEST+1,1))==b'\x80'
    assert q(REQUEST+8)==0 and bytes(u.mem_read(REQUEST+16,4))==bytes(4)
    body_calls=sorted(set(name for at,name in m.calls.items() if A(0x5570)<=at<A(0x5838)))
    assert not any(any(word in name.lower() for word in ('cancel','terminate','synchronize','drain')) for name in body_calls)
    return dict(registration=registration,mode0=mode0,mode1=mode1,DMA_descriptor=dma,
        initial_wait_ticks=3000,wait_slices=waits,response_slices=replies,callback_slices=callback_cases,
        callback_body_imports=body_calls,transfer_cancel_or_quiescence_call_identified=False,
        old_AP_bridge_rejects_private_status5a_before_DMA=True,
        private_response_rejection_from_independent_slices=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ulogio-kernel',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();raw=a.ulogio_kernel.read_bytes()
    report=dict(schema='OFFLINE_LOGGING_EXPORT_LIFETIME/1',camera_io=False,
        source_sha256=SHA,**audit(raw),
        limits=['All messages, responses, backup outputs, callback flags and scheduler returns are synthetic slice inputs',
            'No allocation/query/free/backup/lock/DMA/scheduler or real current-task read executes',
            'Mode0 rejects, not a cached read; mode1 retains potentially indefinite allocation/sync-query waits',
            'The3000-tick DMA wait alone is not an end-to-end timeout or proof that provider work has stopped',
            'Stack context remains a callback sink with no waiter, but a real late callback/UAF is NOT established',
            'Provider descriptor-copy/completion/cancellation guarantees require independent evidence',
            'Process isolation alone cannot establish kernel callback-stack lifetime safety',
            'No live logger invocation, worker or pre-capture candidate is provided'])
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print('Original log gateway: mode0 rejects; mode1 CP-query/DMA boundaries;12 wait /3 response /2 callback slices. No live operations; callback lifetime unresolved.')
if __name__=='__main__':main()
