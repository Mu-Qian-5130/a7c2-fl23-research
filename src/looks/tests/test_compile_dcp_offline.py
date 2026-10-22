"""DCP conversion evaluates its look locally and never invokes Lightroom."""
import json,struct
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import pytest
from looktool import compilelook,lookfile,photoformat,measuredmodel,rawidentity
from test_photoformat import curve


def dcp(path,*,matrix=1,look=True):
    records=[(50708,2,b'Sony ILCE-7CM2\0'),(50936,2,b'Offline fixture\0'),
        (50942,2,b'Fixture copyright\0'),(50940,11,struct.pack('<4f',0,0,1,1)),
        (50721,10,struct.pack('<18i',*([matrix,1]*9)))]
    if look:records.extend([(50981,4,struct.pack('<3I',1,2,1)),(50982,11,struct.pack('<6f',0,1,1,10,.9,.95))])
    sizes={2:1,4:4,10:8,11:4}
    header=bytearray(b'II'+struct.pack('<HIH',0x4352,8,len(records)))
    start=8+2+12*len(records)+4;payload=bytearray()
    for tag,kind,raw in records:
        header.extend(struct.pack('<HHI',tag,kind,len(raw)//sizes[kind]))
        if len(raw)<=4:header.extend(raw.ljust(4,b'\0'))
        else:header.extend(struct.pack('<I',start+len(payload)));payload.extend(raw)
    path.write_bytes(header+bytes(4)+payload);return path


def test_local_dcp_targets_are_finite_and_disclose_approximation(tmp_path):
    path=dcp(tmp_path/'fixture.dcp')
    source=np.array([[.1,.2,.3],[.8,.6,.4],[.3,.3,.3]])
    target,report,profile=compilelook.dcp_targets(source,path)
    assert target.shape==source.shape and np.isfinite(target).all()
    assert ((target>=0)&(target<=1)).all()
    assert report['renderer']=='builtin-DCP-look-tone'
    assert report['Lightroom_reference_used'] is False
    assert report['full_adobe_renderer'] is False
    assert 50721 in report['ignored_calibration_tags']
    assert profile['profile']=='Offline fixture'


def test_donor_sensor_matrix_is_not_used_as_the_sony_color_transform(tmp_path):
    one=dcp(tmp_path/'one.dcp',matrix=1);two=dcp(tmp_path/'two.dcp',matrix=999)
    source=np.array([[.1,.2,.3],[.8,.6,.4]])
    first=compilelook.dcp_targets(source,one)[0];second=compilelook.dcp_targets(source,two)[0]
    np.testing.assert_array_equal(first,second)


def test_tone_only_dcp_is_supported(tmp_path):
    path=dcp(tmp_path/'tone.dcp',look=False)
    target,report,_=compilelook.dcp_targets(np.array([[.2,.4,.6]]),path)
    assert np.isfinite(target).all() and report['look_dimensions'] is None


def test_offline_compiler_writes_supported_a7look_without_renderer_config(tmp_path):
    source=dcp(tmp_path/'source.dcp');original=source.read_bytes()
    calibration=tmp_path/'response.npz';calibration.write_bytes(b'fixture')
    bank=photoformat.PhotoBank(curve(),curve(),bytes(576),bytes(64))
    colors=np.array([[.2,.3,.4],[.5,.6,.7]])
    model=SimpleNamespace(metadata=dict(physical_scope='Synthetic fixture'),
        arrays=dict(baseline_bank=np.frombuffer(bank.pack(),dtype=np.uint8)),
        virtual_samples=lambda count:(colors,colors))
    def fit(*args,**kwargs):
        source.write_bytes(b'original source changed after snapshot')
        return np.zeros((405,3)),dict(native_controls=[0]*17,
            final_optimizer=dict(optimizer_converged=True))
    output=tmp_path/'offline.a7look'
    with patch.object(measuredmodel,'Response',return_value=model),patch.object(compilelook,'fit',side_effect=fit), \
         patch('subprocess.Popen',side_effect=AssertionError('No external renderer allowed')), \
         patch('urllib.request.urlopen',side_effect=AssertionError('No network allowed')):
        assert compilelook.main([str(source),'--name','Offline','--output',str(output),
            '--calibration',str(calibration),'--config',str(tmp_path/'missing.json')])==0
    doc=lookfile.read(output)
    assert len(lookfile.writer_document(doc))==1215
    assert doc['native_photo']['runtime_basis']
    assert doc['validation']['metrics']['Lightroom_reference_used'] is False
    assert rawidentity.source_bytes(doc['raw_profile'])==original
    assert doc['method']=='builtin-DCP-look-tone-measured-native-four-stage-v1'


def test_unsupported_dcp_fails_without_calling_renderer(tmp_path):
    path=tmp_path/'broken.dcp';path.write_bytes(b'not a DCP')
    with patch('subprocess.Popen',side_effect=AssertionError('No renderer')):
        with pytest.raises(ValueError):compilelook.dcp_targets(np.array([[.2,.3,.4]]),path)
