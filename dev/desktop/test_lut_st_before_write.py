"""Selected slots become saved/runtime ST before LUT program writes; no USB."""
import copy
import struct
from unittest.mock import patch

import pytest

from looktool import bundle,checkpoint,checkpointworker,direct
from test_checkpoint import Camera,KEYS,values,fake_compile
from test_direct import SimDirect
from test_fl23_native_photo import original_camera_inputs,looks_first


@pytest.mark.parametrize('mode',['look_import','install_all'])
@pytest.mark.parametrize('failure',['none','program','settings','model'])
def test_selected_bases_are_st_before_lut_write_and_other_slots_are_kept(tmp_path,mode,failure):
    camera=Camera(values());selected=(KEYS[2],KEYS[4]);unselected=KEYS[3]
    for records in (camera.ram,camera.saved):
        for key in (*selected,unselected):records[0][key]=records[0][key]._replace(data=b'\x0b')
    camera.live_look_bases=dict.fromkeys((*selected,unselected),b'\x0b')
    def plan(current,*args,**kwargs):
        target=dict(current);target['appFw.so']=b'X'+current['appFw.so'][1:]
        fields=dict.fromkeys(selected,b'\0')
        fields.update(dict(zip(checkpoint.AP_KEYS,(b'\x0a',b'\x0b'))))
        return target,[fields,{}],None
    class Job(SimDirect):
        def sync_look_bases(self,camera,prepared,selected=None):
            if failure=='model':raise OSError('Native look model synchronization failed')
            return super().sync_look_bases(camera,prepared,selected)
        def native(self,camera,kind,operation,build=None):
            if kind=='program' and operation==1:
                for records in (camera.ram,camera.saved):
                    assert all(records[0][key].data==b'\0' for key in selected)
                    assert records[0][unselected].data==b'\x0b'
                    assert all(records[0][key].data==b'\0' for key in checkpoint.AP_KEYS)
                assert all(camera.live_look_bases[key]==b'\0' for key in selected)
                assert camera.live_look_bases[unselected]==b'\x0b'
            return super().native(camera,kind,operation,build)
    job=Job(tmp_path/mode,factory=lambda expected=None:camera)
    job.lose_after_program=failure=='program'
    original_write=camera.property_write
    def write(key,value,allowed):
        if failure=='settings' and key in selected:raise OSError('ST save failed')
        return original_write(key,value,allowed)
    with patch.object(direct,'plan',side_effect=plan),patch.object(bundle,'plan',side_effect=plan),\
            patch.object(checkpointworker,'compile_worker',side_effect=fake_compile),\
            patch.object(camera,'property_write',side_effect=write):
        def run():return job.run_direct(mode,slot=1,version='2.01',power_confirmed=True,
            bundle_options=dict(looks=[],fl23=False,sound=False))
        if failure=='none':assert run()['phase']=='AWAITING_RELOAD'
        elif failure=='program':
            with pytest.raises(TimeoutError):run()
            assert all(camera.saved[0][key].data==b'\0' for key in selected)
        else:
            with pytest.raises(OSError,match='ST save failed' if failure=='settings' else 'Native look model'):run()
            assert ('program',1) not in camera.native_calls
    assert all(records[0][unselected].data==b'\x0b' for records in (camera.ram,camera.saved))


def test_real_selected_slots_two_and_six_are_st_without_changing_other_slots(looks_first,tmp_path):
    _,_,installed,working,rows=looks_first
    records=copy.deepcopy(working);ap=installed['appFw.so']
    bases=[]
    for slot in range(1,7):
        key=struct.unpack_from('<8I',ap,0x57c6710+(slot+9)*32)[1];bases.append(key)
        records[0][key]=records[0][key]._replace(data=bytes([10+slot%2]))
    _,wanted,_=bundle.plan(installed,records,dict(fl23=False,sound=False),[rows[1],rows[5]])
    camera=Camera(values());camera.ram=copy.deepcopy(records);camera.saved=copy.deepcopy(records)
    before=copy.deepcopy(records)
    job=direct.DirectJob(tmp_path/'st-slots');job.root.mkdir();job.state=dict(journal=[])
    prepared=job.settings(camera,dict(zip(('settings-ram.bin','settings-saved.bin'),
        (camera.snapshot(True),camera.snapshot(False)))),wanted)
    with patch('looktool.runtimebindings.sync') as sync:
        job.prepare_look_settings(camera,prepared)
        sync.assert_called()
    for fields in (camera.ram,camera.saved):
        assert fields[0][bases[1]].data==fields[0][bases[5]].data==b'\0'
        for key,value in before[0].items():
            if key not in wanted[0]:assert fields[0][key]==value
        assert fields[1]==before[1]


def test_model_is_synchronized_before_final_backup_snapshot_readback(tmp_path):
    # readBackup sees the new byte immediately; an AP snapshot may still export
    # the old model value until its native setter/notifications have completed.
    camera=Camera(values());key=KEYS[2]
    camera.ram[0][key]=camera.ram[0][key]._replace(data=b'\x08')
    camera.live_look_bases={key:b'\x08'}
    snapshot=camera.snapshot
    def export(memory):
        if not memory:return snapshot(memory)
        actual=camera.ram[0][key]
        camera.ram[0][key]=actual._replace(data=camera.live_look_bases[key])
        try:return snapshot(memory)
        finally:camera.ram[0][key]=actual
    camera.snapshot=export
    job=SimDirect(tmp_path/'pending-export',factory=lambda expected=None:camera)
    job.root.mkdir();job.state=dict(journal=[])
    current={'settings-ram.bin':camera.snapshot(True),'settings-saved.bin':camera.snapshot(False)}
    prepared=job.settings(camera,current,[{key:b'\0'},{}])
    job.prepare_look_settings(camera,prepared)
    assert camera.property_read(key)==b'\0'
    assert camera.live_look_bases[key]==b'\0'
    assert camera.records(camera.snapshot(True))[0][key].data==b'\0'

