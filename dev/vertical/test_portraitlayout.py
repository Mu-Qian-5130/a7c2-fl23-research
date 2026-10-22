"""Portrait image reference changes preserve corresponding landscape tables."""
from pathlib import Path
import struct
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/vertical'))
from verticaltool import portraitlayout

PAIR=((0,128,64,0x02000f96),)


def fixture():
    raw=bytearray(256)
    for root,size in ((0,0x028001e0),(128,0x01e00280)):
        struct.pack_into('<6I',raw,root,0x82,0xb81,0x250e,0,0,size)
        struct.pack_into('<I',raw,root+64,0x02000f96)
    return bytes(raw)


def test_portrait_reference_has_an_inverse_and_landscape_stays_original():
    source=fixture();target,windows=portraitlayout.references(source,True,pairs=PAIR)
    assert len(windows)==1 and windows[0]['offset']==64
    assert target[128:]==source[128:]
    assert portraitlayout.references(target,True,pairs=PAIR)==(target,[])
    assert portraitlayout.references(target,False,pairs=PAIR)[0]==source


def test_layout_and_landscape_conflicts_stop_planning():
    raw=bytearray(fixture());raw[128]^=1
    with pytest.raises(ValueError,match='canvas differs'):
        portraitlayout.references(raw,True,pairs=PAIR)
    raw=bytearray(fixture());raw[192]^=1
    with pytest.raises(ValueError,match='Landscape image'):
        portraitlayout.references(raw,True,pairs=PAIR)
