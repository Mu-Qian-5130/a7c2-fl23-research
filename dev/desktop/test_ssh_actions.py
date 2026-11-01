"""Desktop SSH routing and privacy boundaries, using the real preparation code."""
import base64
import json
from pathlib import Path
from unittest.mock import patch

from desktopapp.actions import catalog,ssh
from desktopapp import worker,jobs


def test_prepare_is_offline_and_deployment_is_explicit(tmp_path):
    assert 'ssh_prepare' not in catalog.CAMERA_ACTIONS
    assert 'ssh_verify_login' not in catalog.CAMERA_ACTIONS
    assert {'ssh_start','ssh_status','ssh_stop'}<=catalog.CAMERA_ACTIONS
    assert 'ssh_start' in catalog.POWER_ACTIONS
    engine=ssh.engine()
    engine.prepare=lambda *args,**kw:dict(phase='PREPARED',camera_ip='192.0.2.1')
    with patch.object(ssh,'engine',return_value=engine):
        result=worker.run('ssh_prepare',dict(firmware='2.01',workspace=str(tmp_path/'session'),
                          bind_ip='192.0.2.1',client_key='owner.pub'),tmp_path)
    assert result['phase']=='PREPARED' and result['camera_io'] is False
    assert not result['firmware_written'] and not result['persistent_startup']


def test_worker_routes_existing_session_and_pins_host_on_login(tmp_path):
    engine=ssh.engine();calls=[]
    def device(folder,action):calls.append(action);return dict(phase='LISTENING' if action!='stop' else 'STOPPED',camera_ip='192.0.2.1')
    engine.run_device=device
    engine.verify_login=lambda *args:dict(phase='SSH_VERIFIED',camera_ip='192.0.2.1',ssh_login_verified=True)
    args=dict(firmware='2.01',workspace=str(tmp_path/'session'),power_confirmed=True,client_private='owner-private')
    with patch.object(ssh,'engine',return_value=engine):
        for action in ('ssh_start','ssh_status','ssh_stop','ssh_verify_login'):
            result=worker.run(action,args,tmp_path)
            assert result['firmware_written'] is False
    assert calls==['start','status','stop']
    assert result['phase']=='SSH_VERIFIED' and result['ssh_login_verified']


def test_diagnostic_export_never_includes_ssh_host_key(tmp_path,monkeypatch):
    folder=tmp_path/'session';folder.mkdir();(folder/'hostkey').write_bytes(b'private host key sentinel')
    run=tmp_path/'run';run.mkdir()
    (run/'request.private.json').write_text(json.dumps(dict(action='ssh_start',arguments=dict(workspace=str(folder)))))
    (run/'backend-workspace.private.json').write_text(json.dumps(dict(action='ssh_start',workspace=str(folder))))
    import zipfile
    jobs.export_support(run,tmp_path/'diagnostics.zip')
    with zipfile.ZipFile(tmp_path/'diagnostics.zip') as archive:
        assert not any('hostkey' in name for name in archive.namelist())
        assert all(b'private host key sentinel' not in archive.read(name) for name in archive.namelist())


def test_ssh_slot_editor_defaults_to_the_supported_write_action():
    from PySide6.QtWidgets import QApplication
    from desktopapp.lookeditor import LookEditor
    app=QApplication.instance() or QApplication([])
    editor=LookEditor(write_only=True)
    row=editor.add_row(3)
    assert row.value()['action']=='write' and row.value()['slot']==3
    assert not row.action.model().item(0).isEnabled()
    editor.close()
