"""Transport checkboxes, packaged library resolution and version-only recovery."""
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from PySide6 import QtWidgets as W
from desktopapp import window,profilelibrary,worker,sshupdates
from desktopapp.actions import catalog
from test_ssh_updates import Connection


@pytest.fixture
def view():
    app=W.QApplication.instance() or W.QApplication([])
    with patch.object(window,'load_settings',return_value={}):result=window.Window()
    result.timer.stop()
    yield result
    result.close()


@pytest.mark.parametrize('key',['look','sound'])
def test_transport_uses_two_mutually_exclusive_checkboxes(view,key):
    control=getattr(view,key+'_transport')
    assert len(control.findChildren(W.QCheckBox))==2
    assert not control.findChildren(W.QComboBox)
    assert control.value()=='usb'
    control.ssh.click()
    assert control.ssh.isChecked() and not control.usb.isChecked() and control.value()=='ssh'
    control.ssh.click()
    assert control.ssh.isChecked()
    control.usb.click()
    assert control.usb.isChecked() and not control.ssh.isChecked()


@pytest.mark.parametrize('external_catalog',[False,True])
def test_frozen_library_resolves_existing_catalog(monkeypatch,tmp_path,external_catalog):
    packaged=tmp_path/'_internal/desktop-assets/profile-library-v1';packaged.mkdir(parents=True)
    (packaged/'catalog.json').write_text('{}')
    external=tmp_path/'Profiles';external.mkdir()
    if external_catalog:(external/'catalog.json').write_text('{}')
    monkeypatch.setattr(profilelibrary,'ROOT',tmp_path/'_internal')
    monkeypatch.setattr(profilelibrary.sys,'frozen',True,raising=False)
    monkeypatch.setattr(profilelibrary.sys,'platform','win32')
    monkeypatch.setattr(profilelibrary.sys,'executable',str(tmp_path/'A7C2Tools.exe'))
    assert profilelibrary.location()==(external if external_catalog else packaged)


def test_missing_library_is_reported_without_opening_empty_folder(view,tmp_path):
    with patch.object(profilelibrary,'location',return_value=tmp_path/'missing'),\
         patch.object(window.QtGui.QDesktopServices,'openUrl') as opening,patch.object(W.QMessageBox,'warning') as warning:
        view.open_profile_library()
    opening.assert_not_called();warning.assert_called_once()


def test_open_library_uses_resolved_folder_and_reports_shell_failure(view,tmp_path):
    (tmp_path/'catalog.json').write_text('{}')
    with patch.object(profilelibrary,'location',return_value=tmp_path),\
         patch.object(window.QtGui.QDesktopServices,'openUrl',return_value=False) as opening,patch.object(W.QMessageBox,'warning') as warning:
        view.open_profile_library()
    assert Path(opening.call_args.args[0].toLocalFile())==tmp_path
    warning.assert_called_once()


def test_recovery_button_routes_one_version_transaction_with_separate_record(view):
    button=view.findChild(W.QPushButton,'action_ssh_restore_version')
    with patch.object(view,'launch') as launch:button.click()
    action,args=launch.call_args.args
    assert action=='ssh_restore_version' and args['source_version']=='3.01'
    assert 'version-restore' in args['workspace']
    assert action in catalog.CAMERA_ACTIONS and action in catalog.POWER_ACTIONS
    assert view.findChild(W.QPushButton,'action_firmware_factory_build') is not None


@pytest.mark.parametrize('version,before',[('3.01',b'\x01\x03'),('3.02',b'\x02\x03')])
def test_version_recovery_only_changes_native_version_file(tmp_path,version,before):
    connection=Connection({'/setting/updater/dat4':before})
    args=dict(workspace=str(tmp_path/'version'),firmware='2.01',source_version=version,
        bind_ip='192.168.1.2',client_private=None,host_public=None,power_confirmed=True)
    with patch.object(sshupdates,'Connection',return_value=connection):result=worker.run('ssh_restore_version',args,tmp_path/'job')
    assert result['phase']=='AWAITING_RELOAD' and result['version_only']
    assert result['factory_restored'] is False and result['updater_trust_restored'] is False
    assert connection.files['/setting/updater/dat4']==b'\0\x02'
    assert [row['path'] for row in result['rows']]==['/setting/updater/dat4']
    connection.boot='00000000-0000-0000-0000-000000000002'
    with patch.object(sshupdates,'Connection',return_value=connection):verified=worker.run('ssh_verify_update',args,tmp_path/'verify')
    assert verified['phase']=='LOADED' and verified['factory_restored'] is False
    assert verified['updater_trust_restored'] is False and verified['physical_official_upgrade_verified'] is False


def test_unexpected_source_version_does_not_write(tmp_path):
    connection=Connection({'/setting/updater/dat4':b'\x01\x02'})
    args=dict(workspace=str(tmp_path/'version'),firmware='2.01',source_version='3.01',
        bind_ip='192.168.1.2',client_private=None,host_public=None,power_confirmed=True)
    with patch.object(sshupdates,'Connection',return_value=connection):
        with pytest.raises(ValueError,match='不是'):worker.run('ssh_restore_version',args,tmp_path/'job')
    assert connection.files['/setting/updater/dat4']==b'\x01\x02'
    assert not connection.commands


def test_version_action_requires_existing_power_confirmation(tmp_path):
    with patch.object(sshupdates,'Connection') as connection:
        with pytest.raises(ValueError):worker.run('ssh_restore_version',dict(workspace=str(tmp_path/'unused')),tmp_path)
    connection.assert_not_called()
