"""Current-request replacement, terminal-report ownership and JIT-free planning."""
import builtins
import json
from pathlib import Path
import struct
import threading
from unittest.mock import Mock, patch

import pytest
import boot_sound
import boot_trial
import replacement
import sound_cli
import trial


IDENTITY=dict(model='ILCE-7CM2',serial_sha256='fixture')
BOOT1=b'11111111-1111-1111-1111-111111111111'
BOOT2=b'22222222-2222-2222-2222-222222222222'


def camera(files):
    obj=Mock();obj.identity=dict(IDENTITY)
    obj.__enter__=Mock(return_value=obj);obj.__exit__=Mock(return_value=False)
    obj.read.side_effect=lambda path,missing=False:files.get(path)
    obj.temp_read.side_effect=lambda name,missing=False:files.get('/tmp/jiritsu/'+name)
    obj.temp_remove.side_effect=lambda name:files.pop('/tmp/jiritsu/'+name,None)
    return obj


@pytest.mark.parametrize('command',['install','audition'])
@pytest.mark.parametrize('pending',['missing_job','failed_job','no_pending'])
def test_new_selection_archives_history_and_reuses_one_live_connection(tmp_path,command,pending):
    root,state=sound_cli.workspace(tmp_path/'sound',True,tmp_path/'backup')
    old=root/'jobs/old';old.mkdir(parents=True)
    if pending=='failed_job':trial.save(old,dict(identity=IDENTITY,phase='needs_review',journal=[]))
    if pending!='no_pending':state['pending']=dict(command=command,job=str(old),outcome='needs_review')
    state.update(native_job=str(old),native_identity=dict(IDENTITY,serial_sha256='stale'))
    files={'/proc/sys/kernel/random/boot_id':BOOT1};cam=camera(files)
    with replacement.CurrentRequest(root,state,command):
        assert state['pending'] is None and 'native_job' not in state and 'native_identity' not in state
        with patch.object(trial,'factory',return_value=cam) as connect:
            with replacement.BorrowedCamera(replacement.active(),None) as first:
                with replacement.BorrowedCamera(replacement.active(),IDENTITY) as second:assert first is second
            connect.assert_called_once()
        cam.__exit__.assert_not_called()
    cam.__exit__.assert_called_once()
    assert old.is_dir()


def test_only_actual_concurrent_request_is_locked(tmp_path):
    errors=[]
    def compete():
        try:
            with replacement.command_lock(tmp_path/'sound'):pass
        except RuntimeError as exc:errors.append(str(exc))
    with replacement.command_lock(tmp_path/'sound'):
        thread=threading.Thread(target=compete);thread.start();thread.join()
        assert len(errors)==1
    with replacement.command_lock(tmp_path/'sound'):pass


@pytest.mark.parametrize('phase',[0,2,3,4,5,6,7,8,9,11,12,13,14,15,16,17,18,19])
def test_intermediate_pcm_reports_are_never_treated_as_completed(phase):
    raw=bytearray(208);struct.pack_into('<8sIIq',raw,0,b'A7PCM001',1,phase,0)
    assert not replacement.complete_report(raw,0)


@pytest.mark.parametrize('phase,status',[(10,0),(10,-5),(1,-17)])
def test_success_and_terminal_failed_pcm_reports_can_be_accounted(phase,status):
    raw=bytearray(208);struct.pack_into('<8sIIq',raw,0,b'A7PCM001',1,phase,status)
    assert replacement.complete_report(raw,0)


def test_unknown_sound_worker_gets_one_actionable_reconnect_then_current_request(tmp_path):
    root,state=sound_cli.workspace(tmp_path/'sound',True,tmp_path/'backup')
    files={'/proc/sys/kernel/random/boot_id':BOOT1,'/tmp/jiritsu/shutter.staged.so':b'old-worker',
           '/tmp/jiritsu/libJit.so':b'old-worker','/tmp/jiritsu/shutter.custom.lease':b'old-marker'}
    cam=camera(files)
    with patch.object(trial,'factory',return_value=cam):
        with pytest.raises(replacement.ReconnectRequired):
            with replacement.CurrentRequest(root,state,'install') as request:request.open(None)
        cam.temp_remove.assert_not_called()
        files['/proc/sys/kernel/random/boot_id']=BOOT2
        with replacement.CurrentRequest(root,state,'install') as request:assert request.open(None) is cam
    assert not any(k.startswith('/tmp/') for k in files)
    assert 'replacement_stop' not in state


def test_in_progress_owned_pcm_report_is_preserved(tmp_path):
    root,state=sound_cli.workspace(tmp_path/'sound',True,tmp_path/'backup')
    old=root/'jobs/old';old.mkdir(parents=True)
    import hashlib
    worker=b'old-worker';raw=bytearray(208);struct.pack_into('<8sIIq',raw,0,b'A7PCM001',1,18,0)
    trial.save(old,dict(identity=IDENTITY,journal=[dict(event='native_stage_intent',stage='shutter.staged.so',
        request=None,result='shutter.probe.result',mode=0,worker_sha256=hashlib.sha256(worker).hexdigest())]))
    files={'/proc/sys/kernel/random/boot_id':BOOT1,'/tmp/jiritsu/shutter.staged.so':worker,
           '/tmp/jiritsu/shutter.probe.result':bytes(raw)}
    cam=camera(files)
    with patch.object(trial,'factory',return_value=cam),pytest.raises(replacement.ReconnectRequired):
        with replacement.CurrentRequest(root,state,'audition') as request:request.open(None)
    cam.temp_remove.assert_not_called()


def test_production_sound_planner_handles_stock_mixed_and_installed_without_jit():
    edits=boot_sound.expected_windows()
    source=bytearray(max(at+len(old) for at,old,new in edits)+4)
    for at,old,new in edits:source[at:at+len(old)]=old
    real_import=builtins.__import__
    def no_jit(name,*args,**kwargs):
        if name.split('.')[0] in ('unicorn','keystone'):raise AssertionError('Production sound must not use JIT')
        return real_import(name,*args,**kwargs)
    with patch('builtins.__import__',side_effect=no_jit),patch.object(boot_sound,'execute',side_effect=AssertionError('JIT')):
        target,csv,planned,report=boot_sound.plan(bytes(source),bytes(64),current=True)
        assert planned==edits and report['emulator_executed'] is False
        at,old,new=edits[0];source[at:at+len(new)]=new
        mixed,_,remaining,_=boot_sound.plan(bytes(source),bytes(64),current=True)
        assert mixed==target and len(remaining)==len(edits)-1
        assert boot_sound.plan(target,bytes(64),current=True)[2]==[]
        source[at]^=1
        with pytest.raises(ValueError,match='conflict'):boot_sound.plan(bytes(source),bytes(64),current=True)


@pytest.mark.parametrize('old_csv',[b'',b'broken private CSV'])
def test_files_only_previous_attempt_is_replaced_using_current_files(tmp_path,old_csv):
    csv=tmp_path/'csv';csv.write_bytes(b'new')
    files={boot_trial.PATHS[1]:old_csv,'/usr/share/avsystemsound/.a7c2-sound-audio.tmp':b'old-partial'}
    cam=camera(files);components=dict(csv=str(csv))
    with patch.object(boot_trial.files_worker,'build',return_value=tmp_path/'worker') as build:
        result=boot_trial.update_plan(cam,tmp_path,components,bytes(64),None)
    assert result['paths'][0].endswith('custom-shutter-a.bin')
    assert build.call_args.kwargs['previous_csv']==old_csv
    assert build.call_args.kwargs['temporary_files']==[b'old-partial',None]
    assert result['files'] and result['publish_files']


@pytest.mark.parametrize('success',[False,True])
def test_complete_raw_pcm_report_is_reconciled_without_replaying_worker(tmp_path,success):
    import buffer_trial
    root,state=sound_cli.workspace(tmp_path/'sound',True,tmp_path/'backup')
    old=root/'jobs/old';old.mkdir(parents=True)
    import hashlib
    worker=b'finished-worker';raw=bytearray(208)
    struct.pack_into('<8sIIq',raw,0,b'A7PCM001',1,10,0 if success else -5)
    struct.pack_into('<I',raw,132,64)
    if success:
        struct.pack_into('<6I',raw,88,0,0xffffffff,1,1,1,0)
        struct.pack_into('<8I',raw,112,0,0,0,0,1,64,1,0)
        struct.pack_into('<4I',raw,192,0,0,0xffffffff,1)
    token=bytes(range(16)).hex()
    marker=buffer_trial.marker_bytes(buffer_trial.parse(raw),token)
    original=dict(identity=dict(IDENTITY,old_optional_field=True),lease_token_hex=token,
        journal=[dict(event='native_stage_intent',stage='shutter.staged.so',request=None,
            result='shutter.probe.result',mode=0,worker_sha256=hashlib.sha256(worker).hexdigest())])
    trial.save(old,original);before=(old/'job.private.json').read_bytes()
    files={'/proc/sys/kernel/random/boot_id':BOOT1,'/tmp/jiritsu/shutter.staged.so':worker,
           '/tmp/jiritsu/shutter.probe.result':bytes(raw),'/tmp/jiritsu/shutter.custom.lease':marker}
    cam=camera(files)
    with patch.object(trial,'factory',return_value=cam):
        with replacement.CurrentRequest(root,state,'install') as request:request.open(None)
    assert not any(k.startswith('/tmp/') for k in files)
    assert (old/'job.private.json').read_bytes()==before
    cam.temp_write.assert_not_called()


def test_actual_save_prepare_uses_byte_planner_instead_of_emulator(tmp_path):
    source=bytearray(boot_sound.PATH+len(boot_sound.OLD_PATH))
    for at,old,new in boot_sound.expected_windows():source[at:at+len(old)]=old
    with patch.object(boot_sound,'verify',side_effect=AssertionError('No production emulation')), \
         patch.object(boot_trial.candidate,'patch',return_value={'cpapp-b.bin':b'cp'}), \
         patch('looktool.nativebuild.compile_worker'), \
         patch.object(boot_trial,'program_worker',return_value={'path':'program'}), \
         patch.object(boot_trial.files_worker,'build',return_value=tmp_path/'files'):
        target,parts=boot_trial.prepare(bytes(source),b'cp',bytes(64),tmp_path/'build')
    assert boot_sound.installed(target['appFw.so'])
    assert len(parts['restore_windows'])==len(boot_sound.expected_windows())
