"""Replace a completed owned lease, and retire an EEXIST no-op accurately."""
import json
from pathlib import Path
import struct
import sys
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import buffer_trial as bt
import sound_cli as cli
import trial


def successful_report():
    raw=bytearray(208)
    struct.pack_into('<8sIIq',raw,0,b'A7PCM001',1,10,0)
    for at,handle in ((24,1),(56,0x8001)):
        struct.pack_into('<IIQIIII',raw,at,0x70817,handle,0x400000+handle*64,51200,0,0,0)
    struct.pack_into('<6I',raw,88,0,0xffffffff,1,1,1,0)
    struct.pack_into('<8I',raw,112,0,0,0,0,1,3776,1,0)
    raw[144:192]=bytes(48)
    struct.pack_into('<4I',raw,192,0,0,0xffffffff,1)
    return bytes(raw)


@pytest.fixture
def scenario(tmp_path):
    root,state=cli.workspace(tmp_path/'sound',True,tmp_path/'backup')
    previous=tmp_path/'legacy';previous.mkdir()
    identity=dict(model='ILCE-7CM2',serial_sha256='synthetic')
    completed=successful_report()
    result=bt.parse(completed)
    assert result['temporary_pcm_registered']
    old=dict(schema='a7c2-empty-sound-buffer-trial/1',identity=identity,result=result,
             lease_token_hex=bytes(range(16)).hex())
    trial.save(previous,old)
    (previous/'report.private.bin').write_bytes(completed)
    marker=bt.initial_marker(old)
    failed=root/'jobs'/'failed';failed.mkdir(parents=True)
    raw=bytearray(marker[:208]);struct.pack_into('<8sIIq',raw,0,b'A7PCM001',1,1,-17)
    rejected=bt.parse(raw)
    events=[dict(event=kind,stage='shutter.staged.so',mode=0) for kind in (
        'native_stage_intent','native_intent','native_result_verified','native_cleanup_verified')]
    events[2]['result']=rejected
    record=dict(schema='a7c2-empty-sound-buffer-trial/1',phase='needs_review',
        camera_firmware_written=False,result=rejected,journal=events,identity=identity)
    trial.save(failed,record);(failed/'report.private.bin').write_bytes(raw)
    state.update(audio_job=str(failed),pending=dict(command='audition',job=str(failed)),
                 legacy_audio_jobs=[str(previous)])
    cli.save(root,state)
    memory={'marker':marker}
    camera=Mock(identity=identity)
    camera.read.side_effect=lambda *a:memory['marker']
    camera.temp_read.return_value=None
    camera.temp_remove.side_effect=lambda name:memory.update(marker=None)
    return root,state,previous,failed,record,bytes(raw),camera,memory


def test_exact_current_eexist_is_proven_before_any_allocation(scenario):
    root,state,previous,failed,record,raw,camera,memory=scenario
    before=(failed/'job.private.json').read_bytes()
    assert bt.preallocation_marker_rejection(record,raw)
    assert cli.retire_readonly_failure(root,state)
    assert state['pending'] is None and state['audio_job'] is None
    assert (failed/'job.private.json').read_bytes()==before
    assert not camera.read.called


@pytest.mark.parametrize('damage',['cleanup','status','AP_called','CP_called','transfer_called','report'])
def test_mutating_or_unknown_attempt_is_not_retried(scenario,damage):
    root,state,previous,failed,record,raw,camera,memory=scenario
    raw=bytearray(raw)
    if damage=='cleanup':record['journal'].pop()
    elif damage=='status':struct.pack_into('<q',raw,16,-5)
    elif damage=='report':raw=raw[:60]
    else:
        at=dict(AP_called=96,CP_called=100,transfer_called=136)[damage]
        struct.pack_into('<I',raw,at,1)
    trial.save(failed,record);(failed/'report.private.bin').write_bytes(raw)
    assert not cli.retire_readonly_failure(root,state)
    assert state['pending']


def test_completed_owned_marker_is_replaced_without_cold_confirmation_or_buffer_release(scenario):
    root,state,previous,failed,record,raw,camera,memory=scenario
    before=(previous/'job.private.json').read_bytes();marker=memory['marker']
    result=bt.replace_completed_marker(camera,root,[failed,previous])
    assert result['completed_prior_marker_replaced']
    assert result['previous_cp_handle_released'] is False
    camera.temp_remove.assert_called_once_with('shutter.custom.lease')
    assert (root/'replaced-marker.before.private.bin').read_bytes()==marker
    assert (previous/'job.private.json').read_bytes()==before
    assert memory['marker'] is None
    camera.temp_write.assert_not_called()


@pytest.mark.parametrize('damage',['token','body','missing_report','incomplete_report','active_worker'])
def test_unknown_or_active_marker_is_preserved(scenario,damage):
    root,state,previous,failed,record,raw,camera,memory=scenario
    if damage=='token':memory['marker']=memory['marker'][:-1]+b'X'
    elif damage=='body':camera.identity=dict(camera.identity,serial_sha256='different')
    elif damage=='missing_report':(previous/'report.private.bin').unlink()
    elif damage=='incomplete_report':(previous/'report.private.bin').write_bytes(raw)
    else:camera.temp_read.return_value=b'ongoing-worker'
    with pytest.raises(ValueError):bt.replace_completed_marker(camera,root,[previous])
    camera.temp_remove.assert_not_called()
    assert memory['marker']


def test_absent_marker_needs_no_previous_job(scenario):
    root,state,previous,failed,record,raw,camera,memory=scenario
    memory['marker']=None
    assert bt.replace_completed_marker(camera,root,[])['previous_marker_absent']
    camera.temp_remove.assert_not_called()


def test_cli_uses_new_job_and_passes_completed_evidence_after_noop_failure(scenario):
    root,state,previous,failed,record,raw,camera,memory=scenario
    native=root/'native';native.mkdir()
    trial.save(native,dict(phase='written',identity=camera.identity,complete_readback_and_settings_verified=True,electronic_only_gate=True))
    state['native_job']=str(native)
    converted=root/'converted';converted.mkdir()
    (converted/'custom-native.private.bin').write_bytes(bytes(64));state['conversion']=str(converted)
    def adopt(job,*args,**kwargs):
        value=dict(phase='written',identity=camera.identity,complete_readback_and_settings_verified=True,
                   adopted_existing_enabled=True)
        Path(job).mkdir(parents=True);trial.save(job,value);return value
    with patch.object(trial,'preflight',side_effect=adopt),patch.object(bt,'run',return_value=dict(phase='temporary_pcm_registered_cold_reload_required_after_test')) as run:
        cli.audition(root,state)
    assert run.call_args.args[0]!=failed
    assert str(previous) in run.call_args.kwargs['replace_jobs']
    assert state['pending'] is None
