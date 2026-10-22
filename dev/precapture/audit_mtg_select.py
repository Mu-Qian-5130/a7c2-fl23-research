"""Original MTG_REG_SEL field slices on target/donor synthetic register input.

The diagnostic label is source evidence; no clock/edge/lock/physical register
behavior follows from that name or from identical encoded target/donor code.
Logging is stopped before execution; the following store slice is independent.
"""
import argparse
import hashlib
import json
from pathlib import Path
from unicorn import arm_const as R
from support.reference import SPECS, loaded_span
from support.register_source import RegisterSource, STACK, STOP

WORD=0xf5411000
TARGET=dict(entry=0xb9b580,after_log=0xb9b59a,getter=0xb9b5b4,logger=0xb9afd6)
DONOR=dict(entry=0xc31ebc,after_log=0xc31ed6,getter=0xc31ef0,logger=0xc31912)


def audit(target, donor):
    for name,image in (('a7c2-2.01',target),('a1ii-4.00',donor)):
        if hashlib.sha256(image).hexdigest()!=SPECS[name]['sha256']:
            raise ValueError('Unsupported original source: '+name)
    # Both images use explicit laboratory copies at CP_LOAD_BASE. This does
    # not qualify an A1 II physical address or a loaded camera mapping.
    assert loaded_span(target,TARGET['entry'],68)==loaded_span(donor,DONOR['entry'],68)
    assert loaded_span(target,0xfe2a05,12)==b'MTG_REG_SEL\0'
    cases=[]
    for name,image,layout in (('a7c2-2.01',target,TARGET),('a1ii-4.00',donor,DONOR)):
        n=RegisterSource(image,SPECS[name]['sha256'],(WORD,))
        u=n.u
        for selection in (0,1,2,3,4,0xffffffff):
            initial_regs=((R.UC_ARM_REG_SP,STACK+0xf00),(R.UC_ARM_REG_LR,STOP|1),
                (R.UC_ARM_REG_R0,selection),(R.UC_ARM_REG_R4,0x12345678),
                (R.UC_ARM_REG_R6,0x89abcdef),(R.UC_ARM_REG_R7,0x13579bdf))
            n.run(layout['entry'],layout['logger'],initial_regs)
            assert not n.reads and not n.writes
            assert [u.reg_read(reg) for reg in (R.UC_ARM_REG_R0,R.UC_ARM_REG_R1,R.UC_ARM_REG_R2,R.UC_ARM_REG_R3)]==[0,3,0,0]
            sp=u.reg_read(R.UC_ARM_REG_SP)
            assert int.from_bytes(u.mem_read(sp,4),'little')==0
            assert int.from_bytes(u.mem_read(sp+4,4),'little')==selection
            cases.append(dict(source=name,kind='setter-stopped-before-native-log',selection=selection,logger_executed=False))
            frame=u.context_save()
            for initial in (0,0xffffffff,0x55555555,0xaaaaaaaa):
                for readback in (0,0xdeadbeef):
                    # Explicit independent post-logger state; no successful
                    # logger return or preceding native transaction is supplied.
                    u.context_restore(frame)
                    n.run(layout['after_log'],STOP,(),((WORD,initial),(WORD,readback)))
                    wanted=(initial&0xfffffffc)|(selection&3)
                    assert n.writes==[(WORD,4,wanted)]
                    assert u.reg_read(R.UC_ARM_REG_R0)==readback
                    assert u.reg_read(R.UC_ARM_REG_SP)==STACK+0xf00
                    assert [u.reg_read(reg) for reg in (R.UC_ARM_REG_R4,R.UC_ARM_REG_R6,R.UC_ARM_REG_R7)]==[0x12345678,0x89abcdef,0x13579bdf]
                    cases.append(dict(source=name,kind='independent-post-log-RMW',selection=selection,
                                      first_read=initial,second_read=readback,written=wanted,returned=readback))
        for sample in (0,1,2,3,4,0xffffffff,0x55555555,0xaaaaaaaa):
            n.run(layout['getter'],STOP,((R.UC_ARM_REG_SP,STACK+0xf00),(R.UC_ARM_REG_LR,STOP|1)),((WORD,sample),))
            assert not n.writes and u.reg_read(R.UC_ARM_REG_R0)==sample%4
            cases.append(dict(source=name,kind='getter',input=sample,returned=sample%4))
    # Actual native caller's constant setup reaches the setter with R0=3.
    n=RegisterSource(target,SPECS['a7c2-2.01']['sha256'],(WORD,))
    n.run(0xb977c6,TARGET['entry'])
    assert n.u.reg_read(R.UC_ARM_REG_R0)==3 and not n.reads and not n.writes
    cases.append(dict(source='a7c2-2.01',kind='caller-argument',argument=3,callee_executed=False))
    # Independent diagnostic-display prefix passes the name and address to
    # its display service. The display and its MMIO read never execute here.
    n.run(0xb8aed2,0xb83e08)
    assert [n.u.reg_read(reg) for reg in (R.UC_ARM_REG_R0,R.UC_ARM_REG_R1,R.UC_ARM_REG_R2,R.UC_ARM_REG_R3)]==[WORD,4,0x1000,0xfe2a05]
    assert not n.reads and not n.writes
    cases.append(dict(source='a7c2-2.01',kind='diagnostic-label',label='MTG_REG_SEL',address=hex(WORD),display_executed=False))
    return dict(camera_io=False,cases=cases,identical_target_donor_function_bytes=68,
        register='0xf5411000',field_mask=3,physical_role_or_reset_value_qualified=False,
        native_clock_edges_or_exposure=False,
        limits=['Logger calls stop before execution; post-logger slices use explicit independent state',
                'Returning a readback word does not confirm hardware effects',
                'Donor code identity does not qualify physical chip identity, reset values or timing',
                'No sensor, pixels, retained RAW, native save/cancel or camera operation is supplied'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp',type=Path,required=True);p.add_argument('--donor',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    target=a.cp.read_bytes();donor=a.donor.read_bytes()
    report=audit(target,donor)
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print(f"{len(report['cases'])} original MTG selector/label/caller contracts; no hardware timing or capture supplied")


if __name__=='__main__':main()
