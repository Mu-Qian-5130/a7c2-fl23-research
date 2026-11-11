"""Actual DCP construction and paired frontend output; no camera access."""
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pytest
from looktool import dcpexport,compilelook,r5fit,lookfile,rawidentity
from looktool.references import DcpLook,tiff_tags
from looktool.color import hsv_to_rgb,srgb_decode
from hybrid_compiler_fixture import result
from test_compile_dcp_offline import dcp

def identity(path):
    path.write_text('LUT_3D_SIZE 2\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n',encoding='utf-8')

def test_actual_export_preserves_calibration_and_grid_node_colors(tmp_path):
    source=tmp_path/'identity.cube';identity(source);out=tmp_path/'Identity.dcp'
    report=dcpexport.cube_profile(source,'Identity',out,dimensions=(36,32,32))
    _,before=tiff_tags(dcpexport.BASE.read_bytes());_,after=tiff_tags(out.read_bytes())
    for tag in dcpexport.CALIBRATION_TAGS:
        assert before.get(tag)==after.get(tag)
    parent,child=DcpLook(dcpexport.BASE),DcpLook(out)
    hsv=np.array([[h*10,s/31,srgb_decode(np.array([v/31]))[0]]for h,s,v in [(1,8,16),(8,16,20),(14,24,12),(26,8,24)]])
    probes=hsv_to_rgb(hsv)
    np.testing.assert_allclose(child.render(probes),parent.render(probes),rtol=0,atol=2e-5)
    assert child.dims==(36,32,32)and np.array_equal(child.table[:,:,0],np.broadcast_to([0,1,1],child.table[:,:,0].shape))
    assert report['camera_calibration_preserved']and not report['actual_Adobe_verified']

def test_cube_frontend_publishes_both_files_and_exact_raw_binding(tmp_path):
    source=tmp_path/'identity.cube';identity(source);out=tmp_path/'Pair.a7look'
    original_export=dcpexport.cube_profile
    def compact(*args,**kwargs):return original_export(*args,dimensions=(36,32,32),**kwargs)
    with patch.object(r5fit,'fit',return_value=result())as fit,patch.object(dcpexport,'cube_profile',side_effect=compact):
        assert compilelook.main([str(source),'--name','Pair','--output',str(out),'--input-space','sony-st-srgb'])==0
    companion=out.with_suffix('.dcp');assert companion.is_file()
    document=lookfile.read(out)
    assert rawidentity.source_bytes(document['raw_profile'])==companion.read_bytes()
    assert document['raw_profile']['source_profile']=='Pair'and fit.call_count==1
    assert document['validation']['metrics']['paired_DCP']['created_from_CUBE']

def test_different_existing_companion_stops_before_the_expensive_fit(tmp_path):
    source=tmp_path/'source.dcp';dcp(source);out=tmp_path/'Pair.a7look'
    companion=out.with_suffix('.dcp');companion.write_bytes(b'Existing user profile')
    before=source.read_bytes()
    with patch.object(r5fit,'fit')as fit,pytest.raises(SystemExit)as error:
        compilelook.main([str(source),'--name','Pair','--output',str(out)])
    assert error.value.code==2 and not fit.called
    assert companion.read_bytes()==b'Existing user profile'and source.read_bytes()==before and not out.exists()
