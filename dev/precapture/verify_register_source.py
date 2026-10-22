"""Failure controls for original register slices; offline private ROM input."""
import argparse
import json
from pathlib import Path
from unicorn import arm_const as R
from support.reference import SPECS, CP_LOAD_BASE, file_span, loaded_span
from support.register_source import RegisterSource, STACK, STOP


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();cp=a.cp.read_bytes();pin=SPECS['a7c2-2.01']['sha256'];word=0xf5411000
    cases=[]
    def rejected(name, function, error=AssertionError):
        try:function()
        except error:cases.append(dict(case=name,rejected=True))
        else:raise AssertionError('Invalid original-register fixture accepted: '+name)
    def make(words=(word,)):return RegisterSource(cp,pin,words)
    def getter(n,plan,count=100):
        return n.run(0xb9b5b4,STOP,((R.UC_ARM_REG_SP,STACK+0xf00),
                     (R.UC_ARM_REG_LR,STOP|1)),plan,count=count)
    rejected('changed-original-source',lambda:RegisterSource(bytes([cp[0]^1])+cp[1:],pin,(word,)),ValueError)
    rejected('instruction-cap-is-not-return',lambda:getter(make(),((word,3),),count=1))
    rejected('no-default-IO-input',lambda:getter(make(),()))
    rejected('leftover-read-plan',lambda:getter(make(),((word,3),(word,3))))
    rejected('wrong-read-order',lambda:getter(make(),((word+4,3),)))
    rejected('neighbour-is-not-admitted',lambda:getter(make((word+4,)),((word,3),)))
    rejected('unlisted-original-store',lambda:make((word+4,)).run(0xb71614,STOP,
        ((R.UC_ARM_REG_R0,0x11000),(R.UC_ARM_REG_R1,0),(R.UC_ARM_REG_LR,STOP|1))))
    rejected('negative-file-offset',lambda:file_span(cp,-1,4),ValueError)
    rejected('empty-source-span',lambda:file_span(cp,0,0),ValueError)
    rejected('past-file-end',lambda:file_span(cp,len(cp),4),ValueError)
    rejected('fixture-before-base',lambda:loaded_span(cp,CP_LOAD_BASE-4,4),ValueError)
    offset=SPECS['a7c2-2.01']['ranges']['s1_start_call'][0]
    assert file_span(cp,offset,16)==loaded_span(cp,offset+CP_LOAD_BASE,16)
    cases.append(dict(case='explicit-file-and-loaded-coordinate-match',passed=True))
    report=dict(camera_io=False,cases=cases,physical_hardware_qualified=False,
                limits=['Failures preserve the source stop boundary, not a device recovery contract',
                        'Explicit coordinate APIs still require independent source/call qualification'])
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print(f"{len(cases)} register-source/coordinate controls; no implicit hardware read value")


if __name__=='__main__':main()
