"""Current-byte recovery never requires an earlier host-side portrait job."""
from pathlib import Path
import struct
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/vertical'))
from verticaltool import imagebank,portraitbank


def bank():
    count=7844
    raw=bytearray(struct.pack('<8sHHI',imagebank.MAGIC,8,0,count|(((count+1)&~1)<<12)))
    raw.extend(b'\xff\xff'*((count+1)&~1));struct.pack_into('<H',raw,16,0)
    raw.extend(struct.pack('<IIHHII',0x1a000000,0x40000000,8,8,128,16))
    raw.extend(bytes(range(128)))
    return bytes(raw)


def test_footer_reconstructs_original_and_repeated_plan_is_identical():
    source=bank();original,target,plan=portraitbank.prepare(source,0)
    assert original==source and target.endswith(portraitbank.MAGIC)
    assert portraitbank.prepare(target,0)==(source,target,plan)
    assert imagebank.apply(target,plan,reverse=True)==source


def test_partial_append_and_each_partial_metadata_write_resume_from_current_bytes():
    source=bank();_,target,plan=portraitbank.prepare(source,0)
    partial=source+target[len(source):len(source)+67]
    assert portraitbank.prepare(partial,0)[1]==target
    working=bytearray(source+target[len(source):])
    for window in plan['windows']:
        after=bytes.fromhex(window['after_hex']);at=window['offset']
        for size in (1,len(after)):
            working[at:at+size]=after[:size]
            assert portraitbank.prepare(working,0)[1]==target


def test_unknown_tail_is_preserved_as_a_conflict():
    with pytest.raises(ValueError,match='Unrecognized data'):
        portraitbank.prepare(bank()+b'not-our-append',0)
