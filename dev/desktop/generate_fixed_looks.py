"""Generate bounded public patch recipes from an owner's original C2 AP."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/looks'))
from looktool.fixedlookscode import code

def generate(source):
    raw=Path(source).read_bytes()
    if raw[:6]!=b'\x7fELF\x02\x01' or len(raw)!=99960744:
        raise ValueError('Original C2 2.01 AArch64 AP required')
    spans=code(63)
    # All code windows are in the first load segment: file offset equals VA.
    if raw[0x1b5cd14:0x1b5cd24].hex()!='21e01f513f140071e0879f1ac0035fd6':
        raise ValueError('Custom-slot predicate preimage differs')
    tables={0x3757f04:[0x02000713,*range(0x020006c5,0x020006cb)],
        0x3758074:[0x0200093b,*[0x020008ef+13*i for i in range(6)]],
        0x3757d94:[0x02001866,*[0x0200181a+13*i for i in range(6)]],
        0x3757c24:[0x020033f1,*range(0x020033a3,0x020033a9)]}
    import struct
    read_only={}
    for at,values in tables.items():
        expected=struct.pack('<7I',*values)
        if raw[at:at+28]!=expected:raise ValueError('Native live icon table differs at '+hex(at))
        read_only[str(at)]=expected.hex()
    read_only[str(0x41af2dc)]=raw[0x41af2dc:0x41af2dc+24].hex()
    return dict(schema='a7c2-fixed-looks/1',read_only=read_only,
        before={str(at):raw[at:at+len(value)].hex() for at,value in spans.items()},
        templates=[{str(at):value.hex() for at,value in code(mask).items()} for mask in range(64)],
        menu_image_fields=[dict(offset=0x59896e8+i*0xb8+0x48,
            before=raw[0x59896e8+i*0xb8+0x48:0x59896e8+i*0xb8+0x50].hex(),
            normal=0x020006c5+i,selected=0x020008ef+13*i) for i in range(6)])

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-ap',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    args.output.write_text(json.dumps(generate(args.source_ap),indent=2)+'\n',encoding='ascii')
