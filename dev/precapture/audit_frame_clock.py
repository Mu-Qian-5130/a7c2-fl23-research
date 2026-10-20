"""Trace original retention timestamp producers without executing a timer.

Independent post-timer slices use explicit input samples, not successful
hardware/OS stubs. A timestamp store is not an exposure boundary or calibration.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R4,UC_ARM_REG_R5,UC_ARM_REG_SP,UC_ARM_REG_LR
from support.frame_reference import FrameReferenceOracle,BASE,FRAME,STACK,STOP,words

CLOCK,CONTEXT = 0x1a508a0,0x30010000
TIMER,PROCESS = BASE+0x69f488,BASE+0x888f18


def audit(raw):
    n=FrameReferenceOracle(raw);u=n.u
    u.mem_map(CLOCK&~4095,4096);u.mem_map(CONTEXT,0x7000)
    cases=[]
    for sample in (0,1,0x12345678,0x7fffffff,0xffffffff):
        initial=n.reset(1);u.mem_write(CLOCK,words(0x76543210))
        got=n.run(0x3967f4,(TIMER,),((UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)))
        assert got['args'][0]==0 and bytes(u.mem_read(CLOCK,4))==words(0x76543210)
        assert n.frame()==initial
        # Explicit input to a separate post-service fragment. Timer never ran.
        got=n.run(0x3967fe,(BASE+0xa3b61c,),((UC_ARM_REG_R0,sample),))
        assert got['args']==[4,0x4015,1,sample]
        assert bytes(u.mem_read(CLOCK,4))==words(sample) and n.frame()==initial
        # Whole pure getter and producer prefix read the LATCH, not the timer.
        got=n.run(0xa10fee,(STOP,),((UC_ARM_REG_LR,STOP|1),))
        assert got['args'][0]==sample
        got=n.run(0x3a2e24,(PROCESS,),((UC_ARM_REG_R0,FRAME),
            (UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)))
        assert got['args'][:2]==[FRAME+0x3c3c,FRAME+0x20]
        expected=bytearray(initial);struct.pack_into('<I',expected,0xb98,sample)
        assert n.frame()==bytes(expected)
        cases.append(dict(kind='latched-sample-to-frame-b98',sample=sample,
            latch_clock_service_executed=False,producer_timer_calls=0,
            only_frame_timestamp_changed=True,processing_service_executed=False))
    for active in (0,1):
        for sample in (0,0x89abcdef,0xffffffff):
            initial=bytearray(n.reset(1));u.mem_write(CLOCK,words(0x12345678))
            struct.pack_into('<I',initial,0x5aa0,CONTEXT)
            u.mem_write(FRAME,bytes(initial));u.mem_write(CONTEXT,bytes(0x7000))
            u.mem_write(CONTEXT+0x5a90,words(19))
            u.mem_write(STACK+0x8000+8,words(0x11223344))
            got=n.run(0x392a42,(TIMER,),((UC_ARM_REG_R4,FRAME),
                (UC_ARM_REG_R5,active),(UC_ARM_REG_SP,STACK+0x8000)))
            assert got['args'][0]==0 and n.frame()==bytes(initial)
            # The reference getter/clock return are independent explicit
            # inputs. No preceding acquisition/getter/timer is made successful.
            got=n.run(0x392a48,(BASE+0x392a88,),((UC_ARM_REG_R0,sample),))
            expected=bytearray(initial)
            struct.pack_into('<3I',expected,0x66ec,19 if active else 0xffffffff,0x11223344,sample)
            assert n.frame()==bytes(expected)
            assert bytes(u.mem_read(CONTEXT+0x5a90,4))==words(20 if active else 0)
            assert bytes(u.mem_read(CLOCK,4))==words(0x12345678)
            cases.append(dict(kind='independent-current-sample-to-frame-66f4',
                sample=sample,active=active,old_latch_preserved=True,
                clock_service_executed=False,reference_getter_executed=False,
                specific_frame_and_context_stores_only=True))
    return dict(cases=cases,latch_address=hex(CLOCK),latch_store_file='0x39680e',
        latch_getter_file='0xa10fee',frame_latch_store_file='0x3a2e36',
        independent_frame_clock_call_file='0x392a44',independent_frame_store_file='0x392a86',
        native_clock_service_file='0x69f488',
        findings=['frame+b98 copies a saved global clock value through a pure getter',
            'frame+66f4 receives a separate sample at another processing point',
            'Both stores are 32-bit; neither implements the controller 64-bit clock normalization',
            'No exposure-end interpretation follows from either store alone'],
        limits=['No timer, sensor, reference getter or processing service executes',
            'This does not identify physical exposure start/end or a calibrated tick-to-time mapping',
            'Call entry times, wrap/reset handling and real S2 ordering need their own qualified adapter',
            'The pinned stock source is not fresh installed/loaded-source qualification'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();raw=a.cp.read_bytes()
    sources=[Path(__file__),Path(__file__).with_name('support')/'frame_reference.py']
    report=dict(schema='OFFLINE_ORIGINAL_FRAME_CLOCK_PROVENANCE/1',camera_io=False,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        sources={str(s.relative_to(Path(__file__).parent)):hashlib.sha256(s.read_bytes()).hexdigest() for s in sources},
        **audit(raw))
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print(f"{len(report['cases'])} original clock-store cases; no timer, exposure or camera operation executed.")


if __name__=='__main__':main()
