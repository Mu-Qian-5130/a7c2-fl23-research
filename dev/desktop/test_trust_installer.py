"""Installer action boundaries, record selection and native result failures."""
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from desktopapp import trustworker,trustinstall,updaterimage,worker,jobs,reloadguide
from test_trust_prepare_inputs import view


@pytest.mark.parametrize('action',('firmware_trust_install','firmware_trust_restore','firmware_trust_verify'))
def test_dispatch_and_camera_categories(action,tmp_path):
    assert action in jobs.CAMERA_ACTIONS
    assert (action in jobs.POWER_ACTIONS)==(action!='firmware_trust_verify')
    with patch.object(trustinstall,'run',return_value={'camera_io':False}) as dispatch:
        assert worker.run(action,{'power_confirmed':True},tmp_path)=={'camera_io':False}
    dispatch.assert_called_once_with(action,{'power_confirmed':True},tmp_path)


@pytest.mark.parametrize('offset,count',((-512,512),(1,512),(0,513),(25100288,512),(0,0)))
def test_native_ranges_rejected_before_compilation(offset,count):
    with pytest.raises(ValueError):trustworker.header(0,offset,count)


@pytest.mark.parametrize('field,value',((0,b'WRONG001'),(3,3),(7,0),(8,511),(9,-5),(10,1000),(11,-5),(12,-5)))
def test_native_report_cannot_turn_incomplete_write_into_success(field,value):
    row=[b'A7TRST01',1,2,9,1,512,512,25100288,512,0,0,0,0]
    row[field]=value
    with pytest.raises(ValueError):trustworker.parse(trustworker.REPORT.pack(*row),2,512,512)


def record(folder,**values):
    folder.mkdir()
    state=dict(schema='a7c2-first-trust/1',mode='trust_install',phase='AWAITING_RELOAD',
        backup_verified=True,write_attempted=True,**values)
    (folder/trustinstall.STATE).write_text(json.dumps(state))


def test_record_selection_does_not_lose_original_on_restore_and_verify(view,tmp_path):
    original=tmp_path/'install';record(original)
    latest=tmp_path/'restored';record(latest)
    state=json.loads((latest/trustinstall.STATE).read_text());state['mode']='trust_restore'
    (latest/trustinstall.STATE).write_text(json.dumps(state))
    view.settings.update(trust_install_work=str(original),trust_latest_work=str(latest))
    view.fields['trust_record'].setText(str(original))
    assert view.trust_verify_source()==str(latest)
    assert view.trust_verify_button.isEnabled() and view.trust_restore_button.isEnabled()
    assert not view.trust_install_button.isEnabled()
    state['phase']='LOADED';(latest/trustinstall.STATE).write_text(json.dumps(state))
    view.refresh_trust_controls()
    assert view.trust_install_button.isEnabled() and not view.trust_verify_button.isEnabled()
    assert view.text('trust_record')==str(original)


def test_failed_install_with_unknown_write_cannot_be_started_again(view,tmp_path):
    original=tmp_path/'install';record(original)
    state=json.loads((original/trustinstall.STATE).read_text());state['phase']='NEEDS_REVIEW'
    (original/trustinstall.STATE).write_text(json.dumps(state))
    view.fields['trust_record'].setText(str(original))
    assert not view.trust_install_button.isEnabled()
    assert view.trust_restore_button.isEnabled() and not view.trust_verify_button.isEnabled()


def test_preflight_preserves_existing_record_and_requires_explicit_source(tmp_path):
    with pytest.raises(ValueError,match='已存在'):
        trustinstall.validate_request('firmware_trust_install',dict(workspace=str(tmp_path)))
    with pytest.raises(ValueError,match='先选择'):
        trustinstall.validate_request('firmware_trust_restore',dict(workspace=str(tmp_path/'new')))
    assert list(tmp_path.iterdir())==[]


def test_changed_sectors_are_bounded_and_checksum_is_last(monkeypatch):
    original=bytes(updaterimage.PARTITION_BYTES);target=bytearray(original)
    target[512:512+20000]=b'x'*20000;target[50000]=1
    monkeypatch.setattr(updaterimage,'checksum_sectors',lambda raw:{1})
    rows=updaterimage.write_plan(original,original,bytes(target))
    assert rows[-1][0]==512
    rebuilt=bytearray(original)
    for offset,before,after in rows:
        assert offset%512==0 and len(before)%512==0 and len(before)<=16384
        assert rebuilt[offset:offset+len(before)]==before
        rebuilt[offset:offset+len(after)]=after
    assert rebuilt==target


def test_trust_reload_guidance_separates_readback_from_sd_acceptance():
    for mode in ('trust_install','trust_restore'):
        message=reloadguide.text(mode=mode)
        assert '首次授信' in message and '核对只读取' in message and '实际卡刷' in message


@pytest.mark.parametrize('incomplete',('missing_result','pending_loader','foreign_worker','changed_result',None))
def test_explicit_restore_resolves_only_own_finished_temporary(incomplete,tmp_path):
    source=tmp_path/'original';folder=source/'workers/write-000';folder.mkdir(parents=True)
    (folder/'trust.so').write_bytes(b'own compiled worker')
    (folder/'trust.private.h').write_text(trustworker.header(2,512,512,b'a'*512,b'b'*512))
    row=[b'A7TRST01',1,2,9,1,512,512,25100288,512,0,0,0,0]
    if incomplete=='changed_result':row[5]=1024
    files={'a7c2.trust.staged.so':b'own compiled worker','a7c2.trust.result':trustworker.REPORT.pack(*row)}
    if incomplete=='missing_result':files.pop('a7c2.trust.result')
    if incomplete=='pending_loader':files['libJit.so']=b'own compiled worker'
    if incomplete=='foreign_worker':files['a7c2.trust.staged.so']=b'other worker'
    class Camera:
        def temp_read(self,name,missing=False):return files.get(name)
        def temp_remove(self,name):files.pop(name)
    transaction=trustinstall.Installer(tmp_path/'restore')
    transaction.root.mkdir();transaction.restore_source=source
    backend=trustinstall.UsbPartition();backend.camera=Camera()
    initial=dict(files)
    if incomplete:
        with pytest.raises(ValueError):backend.cleanup_prior(transaction)
        assert files==initial
    else:
        backend.cleanup_prior(transaction)
        assert not files
        assert len(list((transaction.root/'evidence').iterdir()))==2
        assert transaction.state['journal'][-1]['writes']==1
