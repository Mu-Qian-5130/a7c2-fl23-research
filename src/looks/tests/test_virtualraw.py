"""Synthetic DNG metadata/radiometry and deterministic color-split coverage."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
import numpy as np
from looktool import virtualraw
from looktool.compilelook import split_colors


def profile():
    records=[(50708,2,b'Sony ILCE-7CM2\0'),(50936,2,b'Virtual Test\0'),
             (50721,10,struct.pack('<18i',*([1,1,0,1,0,1,0,1,1,1,0,1,0,1,0,1,1,1]))),
             (50778,3,struct.pack('<H',21)),(50941,4,struct.pack('<I',0))]
    sizes={2:1,3:2,4:4,10:8}
    header=bytearray(b'II'+struct.pack('<HIH',0x4352,8,len(records)))
    end=8+2+12*len(records)+4;payload=bytearray()
    for tag,kind,data in records:
        header.extend(struct.pack('<HHI',tag,kind,len(data)//sizes[kind]))
        if len(data)<=4:header.extend(data.ljust(4,b'\0'))
        else:
            header.extend(struct.pack('<I',end+len(payload)));payload.extend(data)
    return bytes(header+bytes(4)+payload)


class VirtualRawTests(unittest.TestCase):
    def test_generated_raw_has_explicit_primary_ifd_and_preserves_sensor_values(self):
        import tifffile
        with tempfile.TemporaryDirectory() as directory:
            dcp=Path(directory)/'source.dcp';dcp.write_bytes(profile())
            output=Path(directory)/'chart.dng'
            rgb=np.array([[.1,.2,.3],[.7,.6,.5]])
            chart=virtualraw.write(output,dcp,rgb,columns=2,cell=24)
            with tifffile.TiffFile(output) as file:
                self.assertEqual(file.pages[0].tags[254].value,0)
                self.assertEqual(file.pages[0].tags[50708].value,'Sony ILCE-7CM2')
                pixels=file.asarray().astype(float)
            expected=np.rint(512+rgb*15871)
            for i,(x,y) in enumerate(chart['centers']):
                x,y=int(x),int(y)
                np.testing.assert_array_equal([pixels[y,x],pixels[y,x+1],pixels[y+1,x+1]],expected[i])
            self.assertEqual(dcp.read_bytes(),profile())

    def test_virtual_color_groups_do_not_overlap(self):
        source=np.random.default_rng(9).uniform(.02,.98,(1500,3))
        masks=split_colors(source,np.ones(len(source),bool))
        self.assertTrue(np.all(sum(mask.astype(int) for mask in masks)==1))
        groups=(np.floor(source*4).astype(int)*np.array([16,4,1])).sum(1)
        sets=[set(groups[mask]) for mask in masks]
        self.assertFalse(sets[0]&sets[1] or sets[0]&sets[2] or sets[1]&sets[2])


if __name__=='__main__':unittest.main()
