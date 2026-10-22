"""Separate changed targets from inconsistent reads; fake camera only."""
import json

import pytest

from looktool import checkpointjob, direct
from test_checkpoint import Camera, values
from test_direct import SimDirect


@pytest.mark.parametrize('expected,actual,offset',[
    (b'abcd',b'abXd','0x2'),
    (bytes(4096)+b'ab',bytes(4096)+b'aX','0x1001'),
    (b'abcd',b'abc','0x3'),
    (b'abc',b'abcd','0x3'),
    (b'',b'x','0x0'),
],ids=['byte_change','page_boundary','truncated','extended','empty'])
def test_mismatch_reports_first_byte_and_lengths(expected,actual,offset):
    assert checkpointjob.program_difference(expected,actual)==dict(
        expected_bytes=len(expected),actual_bytes=len(actual),first_difference=offset)
    assert checkpointjob.program_difference(expected,expected) is None


@pytest.mark.parametrize('changed_plan',[False,True])
def test_verification_records_whether_plan_or_second_read_differed(tmp_path,monkeypatch,changed_plan):
    camera=Camera(values())
    job=SimDirect(tmp_path/'job',factory=camera);job.root.mkdir()
    job.state=dict(phase='LOADED',mode='fl23_enable',slot=None,name=None,
        identity=camera.identity,journal=[])
    job.state_path.write_text(json.dumps(job.state))
    def plan(current,*args,**kwargs):
        target=dict(current)
        if changed_plan:target['appFw.so']=b'X'+current['appFw.so'][1:]
        return target,[{},{}],None
    monkeypatch.setattr(direct,'plan',plan)
    original_read=camera.read
    reads=0
    def read(path,*args,**kwargs):
        nonlocal reads
        if path=='/usr/lib/appFw.so':
            reads+=1
            if not changed_plan and reads==2:return b'X'+camera.files[path][1:]
        return original_read(path,*args,**kwargs)
    monkeypatch.setattr(camera,'read',read)
    with pytest.raises(direct.ContentChanged,match='first difference=0x0'):
        job.verify_direct()
    events=job.state['journal']
    assert any(e['event']=='verification_plan_diff' for e in events)==changed_plan
    mismatch=next(e['result'] for e in events if e['event']=='program_readback_mismatch')
    assert mismatch==dict(program='appFw.so',expected_bytes=40000,actual_bytes=40000,first_difference='0x0')
    assert reads==2  # Capture and the existing readback; no additional USB reads.
    assert camera.saves==[] and camera.native_calls==[]

