"""Offline checks for the twelve redrawn portrait line and gauge images."""
import io
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src/vertical'),str(ROOT/'src/desktopapp/vendor')]
from verticaltool import portraitlines
from fwtool.lz77 import inflateLz77


def test_twelve_native_page_rasters_roundtrip():
    rows=portraitlines.specs()
    # Seven line frames, the selection-page border and the four gauge backgrounds.
    assert [(row['group'],row['index']) for row in rows]==[
        (0,0xf96),(0,0xf97),(1,0x397),(1,0x398),(1,0x3d2),(1,0x3ec),(1,0xcac),
        (1,0x291),(1,0x28c),(1,0x28d),(1,0x28e),(1,0x28f)]
    for row in rows:
        pixels=portraitlines.raster(row)
        width,height=row['portrait']
        assert len(pixels)==((width+15)&~15)*height*2
        stream=io.BytesIO(portraitlines.compress(pixels));decoded=[]
        while stream.tell()<len(stream.getbuffer()):decoded.append(inflateLz77(stream))
        assert b''.join(decoded)==pixels
        assert all(len(page)==4096 for page in decoded[:-1])


def test_transparent_line_background_retains_rgb():
    row=portraitlines.specs()[0]
    pixels=portraitlines.raster(row)
    background=(2*row['portrait'][0]+2)*2
    assert pixels[background:background+2]==bytes.fromhex('d0dd')
    assert pixels[background:background+2]!=bytes(2)
