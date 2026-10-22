"""Small resource additions preserve old images and have an exact inverse."""
from pathlib import Path
import struct
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/vertical'))
from verticaltool import imagebank


def source_bank(shared=False):
    count=16;rows=2 if shared else 1
    raw=bytearray(struct.pack('<8sHHI',imagebank.MAGIC,8,0,count|(count<<12)))
    raw.extend(b'\xff\xff'*count);base=len(raw)
    for index in range(rows):
        struct.pack_into('<H',raw,16+2*index,index*5)
        raw.extend(struct.pack('<IIHHII',0x1a000000+index,0x40000000,8,4,64,20*(rows-index)-4))
    raw.extend(bytes(range(64)))
    return bytes(raw)


def additions():
    return [dict(index=14,width=2,height=2,payload=b'new one'),
            dict(index=15,width=3,height=3,payload=b'new two')]


def test_added_metadata_reuses_relocated_space_and_keeps_original_image():
    source=source_bank();target,plan=imagebank.add(source,0,additions())
    before=imagebank.inspect(source,0)['records'][0]
    after=imagebank.inspect(target,0)['records']
    assert after[0]['start']>=len(source)
    assert target[after[0]['start']:after[0]['start']+64]==bytes(range(64))
    assert after[14]['at']==before['start']
    assert after[15]['at']==before['start']+20
    assert len(target)-len(source)<100
    assert len(target)%4==0
    assert imagebank.apply(source,plan)==target
    assert imagebank.apply(target,plan,reverse=True)==source
    altered=bytearray(source);altered[plan['windows'][0]['offset']]^=1
    with pytest.raises(ValueError,match='edit bytes differ'):imagebank.apply(altered,plan)


def test_occupied_indices_and_shared_donor_payloads_are_preserved():
    with pytest.raises(ValueError,match='unused indices'):
        imagebank.add(source_bank(),0,[dict(index=0,width=2,height=2,payload=b'x')])
    with pytest.raises(ValueError,match='independent payload'):
        imagebank.add(source_bank(shared=True),0,additions())
