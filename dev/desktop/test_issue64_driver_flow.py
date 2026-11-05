"""Issue 64 host regressions: synthetic devices and driver files, no real USB."""
import io,json
from contextlib import contextmanager,redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock,patch
import pytest
from PySide6 import QtWidgets as W
from desktopapp import window
from desktopapp.platforms import usb_drivers as drivers
from looktool.devicesession import modules

t,_=modules()


@pytest.fixture
def clock(monkeypatch):
    now=[0.0]
    monkeypatch.setattr(t.time,'monotonic',lambda:now[0])
    monkeypatch.setattr(t.time,'sleep',lambda seconds:now.__setitem__(0,now[0]+seconds))
    return now


def test_uninstall_includes_inactive_exact_camera_packages(tmp_path):
    for n in (31,32):(tmp_path/('oem%d.inf'%n)).write_text('[Models]\nCamera=Install,USB\\VID_054C&PID_0336\n')
    (tmp_path/'oem33.inf').write_text('[Models]\nOther=Install,USB\\VID_1234&PID_5678\n')
    (tmp_path/'oem34.inf').write_text('[Models]\nCamera=Install,USB\\VID_054C&PID_0336\nOther=Install,USB\\VID_1234&PID_5678\n')
    (tmp_path/'oem35.inf').write_text('[Models]\nCamera=Install,USB\\VID_054C&PID_0336\nGeneric=Install,USB\\Class_FF\n')
    (tmp_path/'usbstor.inf').write_text('[Models]\nCamera=Install,USB\\VID_054C&PID_0336\n')
    rows=[dict(id='USB\\VID_054C&PID_0336\\synthetic',inf='oem32.inf')]
    assert drivers.uninstall_plan(rows,{'0336'},tmp_path)==['oem31.inf','oem32.inf']
    assert drivers.uninstall_plan([],{'0336'},tmp_path)==['oem31.inf','oem32.inf']


def test_inactive_package_shared_with_other_devices_is_not_deleted(tmp_path):
    (tmp_path/'oem31.inf').write_text('[Models]\nCamera=Install,USB\\VID_054C&PID_0336\n')
    rows=[dict(id='USB\\VID_1234&PID_5678\\other',inf='oem31.inf')]
    with pytest.raises(ValueError,match='shared'):drivers.uninstall_plan(rows,{'0336'},tmp_path)


def test_normal_return_requires_observed_normal_identity(clock,monkeypatch):
    states=iter([['0336'],[],['0d68'],['0e8a']])
    monkeypatch.setattr(t,'_sony_pids',lambda:next(states))
    with patch.object(t,'get_device') as opening:
        assert t.wait_normal_return(2)
    opening.assert_not_called()
    assert clock[0]==.75


@pytest.mark.parametrize('pids,expected',[(['0336'],False),([],False),(['0e8a'],True)])
def test_stalled_stop_is_not_exit_proof(clock,monkeypatch,pids,expected):
    auth=t.SonySenserAuthDevice.__new__(t.SonySenserAuthDevice)
    auth.driver=SimpleNamespace(vendorRequestOut=Mock(side_effect=t.GenericUsbException('synthetic stall')))
    auth.start=Mock();auth.authenticate=Mock()
    monkeypatch.setattr(t,'_sony_pids',lambda:pids)
    output=io.StringIO()
    with patch.object(t.sys,'platform','win32'),patch.object(t,'get_device',return_value=object()),\
         patch.object(t,'Bounded',return_value=object()),patch.object(t,'GenericUsbDriver',return_value=auth.driver),\
         patch.object(t,'SonySenserAuthDevice',return_value=auth),patch.object(t.usb.util,'dispose_resources') as dispose,\
         redirect_stdout(output):
        assert t._rescue_service() is expected
    assert auth.driver.vendorRequestOut.call_count==1
    dispose.assert_called_once()
    assert ('已确认' in output.getvalue()) is expected
    assert clock[0]<=10


@pytest.mark.parametrize('returned',[False,True])
def test_driver_preparation_checks_return_after_session_closes(monkeypatch,tmp_path,returned):
    from looktool import devicesession
    events=[]
    @contextmanager
    def camera():
        events.append('connected')
        yield SimpleNamespace(identity=dict(model='ILCE-7CM2'))
        events.append('session-ended')
    def normal():
        assert events[-1]=='session-ended'
        events.append('observed-normal')
        return returned
    monkeypatch.setattr(drivers.sys,'platform','win32')
    monkeypatch.setattr(drivers,'is_admin',lambda:True)
    monkeypatch.setattr(drivers,'installer',lambda:None)
    monkeypatch.setattr(drivers,'install',lambda *args,**kwargs:dict(driver_changed=False))
    monkeypatch.setattr(devicesession,'Camera',camera)
    monkeypatch.setattr(t,'wait_normal_return',normal)
    if returned:assert drivers.prepare(tmp_path)['normal_returned']
    else:
        with pytest.raises(drivers.ServiceExitUnconfirmed,match='取下电池'):drivers.prepare(tmp_path)
    assert t.SERVICE_DRIVER_SETUP is None and t.SERVICE_DRIVER_PRESENT is None


@pytest.mark.parametrize('action,result',[('driver_install',dict(driver_changed=True,pid='0e8a')),
    ('usb_prepare',dict(service_connected=True,normal_returned=True))])
def test_finished_driver_step_shows_camera_power_cycle(monkeypatch,tmp_path,action,result):
    app=W.QApplication.instance() or W.QApplication([])
    monkeypatch.setattr(window,'load_settings',lambda:{})
    monkeypatch.setattr(window,'data_root',lambda:tmp_path/'app')
    view=window.Window();view.timer.stop()
    job=tmp_path/'job';job.mkdir()
    (job/'status.private.json').write_text(json.dumps(dict(phase='SUCCEEDED',action=action,result=result)))
    view.current_job=job;view.process=Mock()
    with patch.object(W.QMessageBox,'information') as popup:view.finished(0,None)
    assert popup.call_count==1
    assert '相机断电重开' in popup.call_args.args[1]
    assert '取下电池至少 1 分钟' in popup.call_args.args[2]
    assert '抢点' in popup.call_args.args[2]
    view.close()


def test_exit_unconfirmed_does_not_suggest_reinstalling_drivers(monkeypatch,tmp_path):
    app=W.QApplication.instance() or W.QApplication([])
    monkeypatch.setattr(window,'load_settings',lambda:{})
    monkeypatch.setattr(window,'data_root',lambda:tmp_path/'app')
    view=window.Window();view.timer.stop()
    job=tmp_path/'job';job.mkdir()
    (job/'status.private.json').write_text(json.dumps(dict(phase='FAILED',action='usb_prepare',
        error_type='ServiceExitUnconfirmed',error='未确认退出 0336，请断电重开')))
    view.current_job=job;view.process=Mock()
    with patch.object(W.QMessageBox,'warning') as popup:view.finished(2,None)
    popup.assert_called_once()
    assert window.DRIVER_HINT not in view.status.text()
    view.close()


def test_exit_unconfirmed_survives_administrator_process_boundary(tmp_path):
    (tmp_path/'status.private.json').write_text(json.dumps(dict(phase='FAILED',error_type='ServiceExitUnconfirmed',
        error='驱动已检查，但未回到 0E8A')))
    with pytest.raises(drivers.ServiceExitUnconfirmed,match='未回到'):drivers.elevated_result(tmp_path,2)
