"""Build private PLL tuple constraints from the exact stock CP.

This is an offline experiment input, not a clock model, firmware update or
camera deployment artifact. It contains original source-table values: keep private.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from support.reference import SPECS


def build(cp):
    digest=hashlib.sha256(cp).hexdigest()
    if digest!=SPECS['a7c2-2.01']['sha256']:raise ValueError('Unsupported original stock CP')
    def word(address):return struct.unpack_from('<I',cp,address-0x108000)[0]
    records=[]
    for preset in range(3):
      for mode in (0,1):
        selector=word(0xe949dc+4*preset)
        if selector&~0xfd13:raise ValueError('Unexpected original selector bits')
        coeff=[word(0xe948ec+slot*0x18+preset*8+mode*4)&0x043fff1f for slot in range(5)]
        div=[word(0xe94964+off+preset*8+mode*4)&0x7fe for off in (0x18,0x48)]
        records.append((selector,*coeff,*div))
    payload=b'CPLLSRC1'+digest.encode('ascii')+struct.pack('<I',6)+b''.join(struct.pack('<8I',*row) for row in records)
    assert len(payload)==268
    return payload


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();cp=args.cp.read_bytes();payload=build(cp)
    args.output.mkdir(parents=True,exist_ok=False)
    artifact=args.output/'PLL-source-programs.private.bin';artifact.write_bytes(payload)
    report=dict(camera_io=False,CP_sha256=hashlib.sha256(cp).hexdigest(),artifact=artifact.name,
        bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest(),records=6,
        physical_clock_validity_qualified=False,not_a_deployment_artifact=True)
    (args.output/'manifest.private.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('Private source-tuple fixture built; no hardware LOCK, clock rate or camera operation proved')


if __name__=='__main__':main()
