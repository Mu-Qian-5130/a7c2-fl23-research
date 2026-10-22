"""Compare named original FILE spans; never admit a loaded/current firmware."""
import argparse
import hashlib
import json
from pathlib import Path
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from support.reference import SPECS, CP_LOAD_BASE, file_span


def compare(stock, current):
    spec=SPECS['a7c2-2.01']
    if hashlib.sha256(stock).hexdigest()!=spec['sha256']:
        raise ValueError('Exact original stock CP required')
    if len(stock)!=len(current):raise ValueError('Current file extent differs')
    rows=[]
    for name,(offset,size) in spec['ranges'].items():
        if file_span(stock,offset,size)!=file_span(current,offset,size):
            raise ValueError(f'Changed named file span {name} at {offset:#x}')
        rows.append(dict(name=name,file_offset=hex(offset),fixture_address=hex(offset+CP_LOAD_BASE),bytes=size,equal=True))
    # Independent original encoded branch destinations check the coordinate
    # convention; these are disassembled at FILE offsets, not the load base.
    decoder=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
    for origin,target in spec['calls']:
        op=next(decoder.disasm(file_span(stock,origin,4),origin,count=1))
        assert op.mnemonic=='bl' and op.op_str==f'#{target:#x}'
    return dict(camera_io=False,spans=rows,original_call_displacements=len(spec['calls']),
                coordinate='SPECS ranges and calls are file offsets',
                whole_current_program_admitted=False,loaded_RAM_verified=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp',type=Path,required=True)
    p.add_argument('--current-cp',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();stock=a.cp.read_bytes();current=a.current_cp.read_bytes()
    report=compare(stock,current)
    rejected=[]
    for name,(offset,size) in SPECS['a7c2-2.01']['ranges'].items():
        changed=bytearray(stock);changed[offset]^=1
        try:compare(stock,changed)
        except ValueError:rejected.append(name)
        else:raise AssertionError('Changed named FILE span admitted')
    report['changed_named_span_rejections']=rejected
    report['limits']=['Only named on-disk spans are compared, not all modified firmware',
                      'A historical snapshot is not current camera identity or loaded RAM',
                      'No installation, native call, exposure, pixel retention or restoration is tested']
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print(f"{len(report['spans'])} named FILE spans matched; {len(rejected)} drift controls rejected; no loaded-state admission")


if __name__=='__main__':main()
