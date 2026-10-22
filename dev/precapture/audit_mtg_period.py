"""Original indexed MTG period storage; no physical timing or native ACK.

Native logger/display/period calls stop before execution. Post-call slices
are independent explicit states, never fabricated successful native returns.
"""
import argparse
import hashlib
import json
from pathlib import Path
from unicorn import arm_const as R
from support.reference import SPECS, CP_LOAD_BASE, loaded_span
from support.register_source import RegisterSource, STACK, STOP

ENTRY, AFTER_LOG, GETTER, LOGGER = 0xb9b672, 0xb9b68c, 0xb9b6da, 0xb9afd6
WORDS=(0xf5411010,0xf5411014,0xf5411018)
VALUES=(0,0x1b7e47,0x225dd9,0xffffffff)


def audit(target,donor):
    for name,image in (('a7c2-2.01',target),('a1ii-4.00',donor)):
        if hashlib.sha256(image).hexdigest()!=SPECS[name]['sha256']:
            raise ValueError('Unsupported original source: '+name)
    fragment=loaded_span(target,ENTRY,166)
    # Search exact bytes, requiring a unique match in the pinned donor. No
    # physical donor load address or shared chip timing is inferred.
    at=donor.find(fragment)
    if at<0 or donor.find(fragment,at+1)>=0:raise ValueError('Donor period block is not uniquely identical')
    delta=at+CP_LOAD_BASE-ENTRY
    cases=[]
    for name,image,shift in (('a7c2-2.01',target,0),('a1ii-4.00',donor,delta)):
        n=RegisterSource(image,SPECS[name]['sha256'],WORDS);u=n.u
        for index in (0,1,2,3,0xffffffff):
            for wanted in VALUES:
                registers=((R.UC_ARM_REG_SP,STACK+0xf00),(R.UC_ARM_REG_LR,STOP|1),
                    (R.UC_ARM_REG_R0,index),(R.UC_ARM_REG_R1,wanted),
                    (R.UC_ARM_REG_R4,0x12345678),(R.UC_ARM_REG_R5,0x89abcdef),
                    (R.UC_ARM_REG_R7,0x13579bdf))
                n.run(ENTRY+shift,LOGGER+shift,registers)
                assert not n.reads and not n.writes
                assert [u.reg_read(r) for r in (R.UC_ARM_REG_R0,R.UC_ARM_REG_R1,R.UC_ARM_REG_R2,R.UC_ARM_REG_R3)]==[2,3,0,0]
                sp=u.reg_read(R.UC_ARM_REG_SP)
                assert int.from_bytes(u.mem_read(sp,4),'little')==index
                assert int.from_bytes(u.mem_read(sp+4,4),'little')==wanted
                cases.append(dict(source=name,kind='prefix-before-log',index=index,value=wanted,native_log=False))
                context=u.context_save()
                if index<3:
                    for returned in (0,0xffffffff,0x13579bdf,0x2468ace0):
                        u.context_restore(context)
                        n.run(AFTER_LOG+shift,STOP,(),((WORDS[index],returned),))
                        assert n.writes==[(WORDS[index],4,wanted)] and n.reads==[(WORDS[index],4,returned)]
                        assert n.io_events==[('write',WORDS[index],4,wanted),('read',WORDS[index],4,returned)]
                        assert u.reg_read(R.UC_ARM_REG_R0)==returned
                        assert u.reg_read(R.UC_ARM_REG_SP)==STACK+0xf00
                        assert [u.reg_read(r) for r in (R.UC_ARM_REG_R4,R.UC_ARM_REG_R5,R.UC_ARM_REG_R7)]==[0x12345678,0x89abcdef,0x13579bdf]
                        cases.append(dict(source=name,kind='independent-post-log-write-then-read',index=index,
                                          value=wanted,address=hex(WORDS[index]),second_read=returned,returned=returned,
                                          IO_sequence=[list(event) for event in n.io_events]))
                else:
                    n.run(AFTER_LOG+shift,LOGGER+shift)
                    assert not n.writes and not n.reads
                    assert u.reg_read(R.UC_ARM_REG_R0)==0xe0 and u.reg_read(R.UC_ARM_REG_R1)==3
                    cases.append(dict(source=name,kind='invalid-setter-index',index=index,native_error_log=False,IO=0))
        for index in (0,1,2,3,0xffffffff):
            for sample in VALUES if index<3 else (0,):
                n.run(GETTER+shift,STOP if index<3 else LOGGER+shift,
                    ((R.UC_ARM_REG_SP,STACK+0xf00),(R.UC_ARM_REG_LR,STOP|1),(R.UC_ARM_REG_R0,index)),
                    ((WORDS[index],sample),) if index<3 else ())
                assert not n.writes
                if index<3:assert u.reg_read(R.UC_ARM_REG_R0)==sample
                else:assert not n.reads and u.reg_read(R.UC_ARM_REG_R0)==0xe0
                cases.append(dict(source=name,kind='getter' if index<3 else 'invalid-getter-index',index=index,sample=sample))
    n=RegisterSource(target,SPECS['a7c2-2.01']['sha256'],WORDS);u=n.u
    labels=((0xb8b0a6,0xfe2a32,'MTG_REG_SEL_HD_PERIOD'),
            (0xb8b0c2,0xfe2a48,'MTG_REG_SEL_24_PERIOD'),
            (0xb8b0d6,0xfe2a5e,'MTG_REG_SEL_SD_PERIOD'))
    for index,(entry,string,label) in enumerate(labels):
        assert loaded_span(target,string,len(label)+1)==label.encode()+b'\0'
        n.run(entry,0xb83e08,((R.UC_ARM_REG_R5,WORDS[0]),))
        assert [u.reg_read(r) for r in (R.UC_ARM_REG_R0,R.UC_ARM_REG_R1,R.UC_ARM_REG_R2,R.UC_ARM_REG_R3)]==[WORDS[index],4,0x1010+4*index,string]
        assert not n.reads and not n.writes
        cases.append(dict(source='a7c2-2.01',kind='diagnostic-label',label=label,address=hex(WORDS[index]),display_executed=False))
    for mode in range(8):
        n.run(0xb977aa,LOGGER,((R.UC_ARM_REG_SP,STACK+0xf00),(R.UC_ARM_REG_LR,STOP|1),
              (R.UC_ARM_REG_R0,mode),(R.UC_ARM_REG_R4,0x12345678),(R.UC_ARM_REG_R5,0x89abcdef)))
        # Independent post-selector entry: neither logger nor selector ran.
        n.run(0xb977cc,ENTRY)
        expected0=0x1b7e47 if mode in (0,3,4,7) else 0x20f57f if mode in (1,5) else 0x1b773f
        expected1=0x225dd9 if mode in (0,3,4,7) else 0x22550f
        assert u.reg_read(R.UC_ARM_REG_R0)==0 and u.reg_read(R.UC_ARM_REG_R1)==expected0
        resume=u.reg_read(R.UC_ARM_REG_LR)&~1;context=u.context_save()
        cases.append(dict(source='a7c2-2.01',kind='first-caller-request',mode=mode,index=0,value=expected0,native_setter=False))
        for hypothetical in (0,0xffffffff):
            u.context_restore(context)
            n.run(resume,ENTRY,((R.UC_ARM_REG_R0,hypothetical),))
            assert u.reg_read(R.UC_ARM_REG_R0)==1 and u.reg_read(R.UC_ARM_REG_R1)==expected1
            cases.append(dict(source='a7c2-2.01',kind='independent-second-caller-request',mode=mode,
                              supplied_R0=hypothetical,index=1,value=expected1,native_setter=False))
    for mode in (8,0xffffffff):
        n.run(0xb977aa,LOGGER,((R.UC_ARM_REG_SP,STACK+0xf00),(R.UC_ARM_REG_LR,STOP|1),(R.UC_ARM_REG_R0,mode)))
        n.run(0xb977cc,LOGGER)
        assert not n.reads and not n.writes
        cases.append(dict(source='a7c2-2.01',kind='invalid-caller-mode',mode=mode,native_log=False))
    return dict(camera_io=False,cases=cases,identical_donor_bytes=166,donor_match_file_offset=hex(at),
                period_word_names=[r[2] for r in labels],physical_tick_unit_or_rate_qualified=False,
                limits=['Only original configuration stores/getters and labels are qualified',
                        'Logging/display/setter boundaries are never supplied as successful native calls',
                        'Caller mode integers are not mapped to physical camera drive modes',
                        'Write/readback does not prove timing acceptance, edges, IRQ, exposure or saved pixels'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp',type=Path,required=True);p.add_argument('--donor',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    report=audit(a.cp.read_bytes(),a.donor.read_bytes())
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print(f"{len(report['cases'])} original MTG period/index/caller/label contracts; no timing or camera operation")


if __name__=='__main__':main()
