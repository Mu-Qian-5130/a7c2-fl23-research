"""Original add/drop-reference and holder-release contracts, offline only.

Counter mutations run as explicit independent post-lock slices. They do not
make a successful mutex, acquired reference, pixel release or save operation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R4,UC_ARM_REG_R5,UC_ARM_REG_R6,UC_ARM_REG_SP,UC_ARM_REG_LR
from support.frame_reference import (FrameReferenceOracle,BASE,FRAME,HOLDER,VTABLE,DEBUG,
    STOP,STACK,POOL,CALLBACK,ADDREF,DROPREF,QUERY,words)


def audit(raw):
    n=FrameReferenceOracle(raw);u=n.u;cases=[]
    for operation,start,slice_at,tail,delta in (
        ('add',ADDREF,0x36bd6c,0x36bd88,1),
        ('drop',DROPREF,0x36be14,0x36be30,-1)):
        for initial in (0,1,2,7,0xfffffffe,0xffffffff):
            before=n.reset(initial)
            got=n.run(start,(BASE+QUERY,),((UC_ARM_REG_R0,FRAME),))
            assert got['at']==BASE+QUERY and n.frame()==before
            # The lock/query were NOT executed. Original state stores execute
            # only from the independently selected post-lock entry.
            got=n.run(slice_at,(BASE+QUERY,))
            after=(initial+delta)&0xffffffff
            expected=bytearray(before);struct.pack_into('<I',expected,4,after)
            assert n.frame()==bytes(expected) and n.count()==after
            stops=(BASE+0xa07356,) if operation=='drop' and after==0 else (STOP,)
            got=n.run(tail,stops)
            assert n.frame()==bytes(expected)
            if operation=='drop' and after==0:assert got['args'][0]==FRAME
            cases.append(dict(operation=operation,before=initial,after=after,
                entry_stopped_before_lock_query=True,independent_post_lock_slice=True,
                wrap_or_resurrection=initial==0 or (operation=='add' and after==0),
                final_frame_pool_return_boundary=got['at']==BASE+0xa07356,
                RAW_ID_bytes_unchanged=True,native_lock_or_free_executed=False))
    # Armed zero-reference callback: the target passes frame as its second arg,
    # and a delegate receiver as the first. Do not miscast it to void(frame*).
    before=n.reset(1,True)
    got=n.run(DROPREF,(BASE+QUERY,),((UC_ARM_REG_R0,FRAME),))
    got=n.run(0x36be14,(BASE+QUERY,))
    got=n.run(0x36be30,(CALLBACK,))
    assert got['args'][:2]==[FRAME+8,FRAME] and n.count()==0
    cases.append(dict(operation='zero-reference-delegate',receiver=hex(FRAME+8),
        frame_argument=hex(FRAME),callback_executed=False))
    # Whole holder release calls frame vtable+12 BEFORE holder pool return.
    # Observe that boundary without executing either destructor or lock.
    n.reset(2)
    got=n.run(0xa018dc,(BASE+DROPREF,),((UC_ARM_REG_R0,HOLDER),))
    assert got['args'][0]==FRAME and n.count()==2
    held=bytes(u.mem_read(HOLDER,68))
    # Independent post-destructor slice, not an implicit success/return.
    got=n.run(0xa018ec,(BASE+QUERY,))
    assert got['args'][:2]==[0x1a31f40,HOLDER] and bytes(u.mem_read(HOLDER,68))==held
    # A completed ordinary frame-reference decrement may leave pixels alive,
    # while the holder is still returned independently. Frame != holder lease.
    cases.append(dict(operation='holder-release-order',frame_drop_precedes_holder_pool=True,
        frame_refcount_before=2,frame_refcount_unchanged_without_drop=True,
        holder_pool_query_executed=False,holder_bytes_unchanged=True))
    # Explicit original slices keep the SAME frame through addref and holder
    # destruction. Its holder may be reused while the independent frame ref
    # remains. No allocator/destructor/lock result is supplied as successful.
    before=n.reset(1)
    n.run(ADDREF,(BASE+QUERY,),((UC_ARM_REG_R0,FRAME),))
    n.run(0x36bd6c,(BASE+QUERY,));n.run(0x36bd88,(STOP,))
    assert n.count()==2
    n.run(0xa018dc,(BASE+DROPREF,),((UC_ARM_REG_R0,HOLDER),))
    n.run(DROPREF,(BASE+QUERY,))
    n.run(0x36be14,(BASE+QUERY,))
    got=n.run(0x36be30,(BASE+0xa018ec,))
    assert got['at']==BASE+0xa018ec and n.count()==1
    n.run(0xa018ec,(BASE+QUERY,))
    next_node=HOLDER+0x100
    u.mem_write(POOL,words(next_node,500,499))
    n.run(0xa01924,(BASE+QUERY,))
    assert struct.unpack('<I',u.mem_read(HOLDER,4))[0]==next_node
    assert struct.unpack('<3I',u.mem_read(POOL,12))==(HOLDER,500,500)
    expected=bytearray(before);struct.pack_into('<I',expected,4,1)
    assert n.frame()==bytes(expected)
    # Only the separately retained FRAME is meaningful now, not old HOLDER.
    n.run(DROPREF,(BASE+QUERY,),((UC_ARM_REG_R0,FRAME),
        (UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)))
    n.run(0x36be14,(BASE+QUERY,))
    got=n.run(0x36be30,(BASE+0xa07356,))
    assert n.count()==0 and got['args'][0]==FRAME
    cases.append(dict(operation='independent-frame-reference-outlives-holder',
        explicit_reference_count_path=[1,2,1,0],holder_reused_at_count=1,
        old_holder_no_longer_points_to_frame=True,final_frame_pool_return_executed=False,
        native_locks_and_destructors_not_simulated=True))
    # Instruction-cap exhaustion must fail instead of being mistaken for return.
    n.reset(1)
    try:n.run(ADDREF,(BASE+QUERY,),((UC_ARM_REG_R0,FRAME),),count=1)
    except AssertionError:pass
    else:raise AssertionError('Instruction budget was incorrectly treated as a boundary')
    # An undeclared native service is also a hard failure.
    n.reset(1)
    try:n.run(ADDREF,(),((UC_ARM_REG_R0,FRAME),))
    except AssertionError as error:assert 'Unexpected native service' in str(error)
    else:raise AssertionError('Undeclared native call was accepted')
    return dict(vtable=hex(VTABLE),add_reference_file=hex(ADDREF),drop_reference_file=hex(DROPREF),
        native_reference_count_offset=4,cases=cases,boundary_failure_paths=2,
        findings=['Frame reference and pipeline holder have separate lifetimes',
            'Original add/drop use native context-dependent locking; post-lock stores are not acquired references',
            'The decrement can reach a final callback and frame-pool return only at zero',
            'Holder release invokes frame drop first and separately returns the holder to its pool',
            'Native add/drop do not themselves reject zero resurrection or unsigned overflow/underflow',
            'Save completion must identify whether the exact workflow lease was consumed or retained'],
        limits=['No native lock, callback, actual RAW release, frame acquisition or save executes',
            'Reference counter observations are not safe acquisition or terminal-fence evidence',
            'An armed zero-reference delegate is not necessarily a durability completion',
            'Existing holder/frame ownership and an exact-source live adapter remain unproven'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();raw=a.cp.read_bytes()
    sources=[Path(__file__),Path(__file__).with_name('support')/'frame_reference.py']
    report=dict(schema='OFFLINE_ORIGINAL_FRAME_REFERENCE/1',camera_io=False,
                source_sha256=hashlib.sha256(raw).hexdigest(),
                sources={str(p.relative_to(Path(__file__).parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
                **audit(raw))
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print(f"{len(report['cases'])} original reference/holder contracts; no native locking, image release or camera I/O.")


if __name__=='__main__':main()
