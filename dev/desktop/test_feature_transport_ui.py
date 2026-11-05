"""Shared editors keep host conversion and route only explicit camera actions."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6 import QtWidgets as W
from desktopapp import window,worker,sshupdates
from desktopapp.actions import sound,catalog


@pytest.fixture
def view():
    app=W.QApplication.instance() or W.QApplication([])
    with patch.object(window,'load_settings',return_value={}):result=window.Window()
    yield result
    result.close()


def test_normal_navigation_exposes_separate_editors_and_settings(view):
    assert [(view.nav_items[i].text(),view.nav_items[i].isHidden()) for i in (4,6,10)]==[
        ('滤镜',False),('快门音效',False),('连接设置',False)]
    assert [view.nav.item(i).text() for i in range(7)]==[
        '安装驱动','首次授信','生成固件','滤镜','快门音效','一键恢复','连接设置']
    for page in (1,11,9,4,6,2,10):
        view.select_page(page)
        assert view.pages.currentIndex()==page
    assert not hasattr(view,'ssh_look_editor')
    assert all(key in view.fields for key in ('sound_source','sound_work','ssh_update_ip'))


@pytest.mark.parametrize('transport',['usb','ssh'])
@pytest.mark.parametrize('selection',['electronic','mechanical','both'])
def test_custom_sound_uses_same_workspace_and_checkbox_targets(view,transport,selection):
    view.sound_transport.select(transport)
    view.sound_electronic.setChecked(selection in ('electronic','both'))
    view.sound_mechanical.setChecked(selection in ('mechanical','both'))
    with patch.object(view,'launch') as launch:view.save_sound()
    action,args=launch.call_args.args
    assert action==('ssh_sound_custom' if transport=='ssh' else 'sound_install')
    assert args['selection' if transport=='ssh' else 'sound_target']==selection
    assert args['sound_workspace' if transport=='ssh' else 'workspace']==view.text('sound_work')


@pytest.mark.parametrize('transport',['usb','ssh'])
def test_zero_targets_never_launches_a_camera_action(view,transport):
    view.sound_transport.select(transport)
    view.sound_electronic.setChecked(False);view.sound_mechanical.setChecked(False)
    with patch.object(view,'launch') as launch,patch.object(W.QMessageBox,'information'):
        view.save_sound()
    launch.assert_not_called()


@pytest.mark.parametrize('transport',['usb','ssh'])
@pytest.mark.parametrize('selection',['electronic','mechanical'])
@pytest.mark.parametrize('enabled',[False,True])
def test_independent_switches_follow_selected_transport(view,transport,selection,enabled):
    view.sound_transport.select(transport)
    with patch.object(view,'launch') as launch:view.switch_sound(selection,enabled)
    action,args=launch.call_args.args
    if transport=='ssh':
        assert action=='ssh_sound_switch' and args['selection']==selection and args['enabled']==enabled
    else:assert action==('sound_mechanical_' if selection=='mechanical' else 'sound_')+('on' if enabled else 'off')


@pytest.mark.parametrize('transport',['usb','ssh'])
def test_filter_batch_preserves_same_operations(view,transport):
    view.look_transport.select(transport)
    view.look_editor.set_operations([dict(slot=3,action='restore')])
    with patch.object(view,'launch') as launch:view.launch_look_changes()
    action,args=launch.call_args.args
    assert action==('ssh_save_looks' if transport=='ssh' else 'direct_looks_import')
    assert args['operations']==[dict(slot=3,action='restore')]


def test_host_processing_buttons_remain_offline_in_ssh_mode(view):
    view.sound_transport.select('ssh')
    for action in ('sound_import','sound_generate','sound_volume'):
        assert action not in catalog.CAMERA_ACTIONS and action not in catalog.POWER_ACTIONS
        buttons=view.findChildren(W.QPushButton,'action_'+action)
        assert buttons
        for button in buttons:
            with patch.object(view,'launch') as launch:button.click()
            assert launch.call_args.args[0]==action


@pytest.mark.parametrize('selection',['electronic','mechanical','both'])
def test_ssh_sends_exact_current_volume_payload_once(tmp_path,selection):
    root=tmp_path/'sound'
    sound.run('sound_generate',dict(workspace=str(root),frequency=660,duration=.08))
    original=sound.converted_file(root).read_bytes()
    sound.run('sound_volume',dict(workspace=str(root),decibels=-3))
    adjusted=sound.converted_file(root).read_bytes()
    assert adjusted!=original
    # An old unresolved camera transaction must not alter host selection.
    (root/'sound.private.json').write_text('old unreadable camera record')
    args=dict(workspace=str(tmp_path/'update'),sound_workspace=str(root),selection=selection,bind_ip='192.168.1.2',power_confirmed=True)
    with patch.object(sshupdates,'Connection') as connection,patch('desktopapp.cameraapi.call',return_value=dict(state='pending_reload')) as call:
        result=worker.run('ssh_sound_custom',args,tmp_path/'job')
    assert call.call_count==1
    assert call.call_args.args[1:]==('sound',selection,'custom')
    assert call.call_args.kwargs['payload']==adjusted
    assert result['reload_required'] and result['phase']=='AWAITING_RELOAD'
    with patch.object(sshupdates,'Connection') as connection:
        with pytest.raises(FileExistsError):worker.run('ssh_sound_custom',args,tmp_path/'retry')
    connection.assert_not_called()


def test_missing_conversion_is_rejected_before_ssh_connection(tmp_path):
    with patch.object(sshupdates,'Connection') as connection:
        with pytest.raises(ValueError,match='导入'):
            worker.run('ssh_sound_custom',dict(workspace=str(tmp_path/'update'),sound_workspace=str(tmp_path/'sound'),
                selection='both',bind_ip='192.168.1.2',power_confirmed=True),tmp_path/'job')
    connection.assert_not_called()


def test_ssh_filter_compiles_all_slots_then_applies_once(tmp_path):
    operations=[dict(slot=1,action='restore'),dict(slot=3,action='restore')]
    args=dict(workspace=str(tmp_path/'update'),baseline='baseline',operations=operations,bind_ip='192.168.1.2',power_confirmed=True)
    with patch.object(sshupdates,'compile_look') as compile,patch.object(sshupdates,'Connection') as connection,\
         patch('desktopapp.cameraapi.call',return_value=dict(state='idle')),\
         patch.object(sshupdates,'apply',return_value=dict(phase='AWAITING_RELOAD')) as apply:
        worker.run('ssh_save_looks',args,tmp_path/'job')
    compile.assert_called_once_with('baseline',operations,Path(args['workspace']))
    apply.assert_called_once_with(Path(args['workspace']),connection.return_value)


def test_ssh_timeout_preserves_unknown_result_without_retry(tmp_path):
    args=dict(workspace=str(tmp_path/'update'),selection='mechanical',enabled=False,bind_ip='192.168.1.2',power_confirmed=True)
    with patch.object(sshupdates,'Connection'),patch('desktopapp.cameraapi.call',side_effect=TimeoutError('lost response')) as call:
        with pytest.raises(TimeoutError):worker.run('ssh_sound_switch',args,tmp_path/'job')
    assert call.call_count==1
    assert json.loads((Path(args['workspace'])/'command.private.json').read_text())['phase']=='NEEDS_REVIEW'


@pytest.mark.parametrize('state,phase',[('active','LOADED'),('pending_reload','AWAITING_RELOAD'),('idle','IDLE')])
def test_task_query_reports_camera_state(tmp_path,state,phase):
    with patch.object(sshupdates,'Connection'),patch('desktopapp.cameraapi.call',return_value=dict(state=state)) as call:
        result=worker.run('ssh_sound_task',dict(workspace=str(tmp_path/'unused'),bind_ip='192.168.1.2'),tmp_path/'job')
    assert call.call_args.args[1:] == ('task',)
    assert result['phase']==phase


def test_sound_generation_volume_reset_and_preview_share_selected_file(tmp_path):
    root=tmp_path/'sound'
    result=sound.run('sound_generate',dict(workspace=str(root),frequency=880,duration=.08))
    original=sound.converted_file(root).read_bytes()
    assert not result['camera_io'] and Path(result['preview'])==sound.converted_file(root,'preview.private.wav')
    sound.run('sound_volume',dict(workspace=str(root),decibels=3))
    sound.run('sound_volume',dict(workspace=str(root),reset=True))
    assert sound.converted_file(root).read_bytes()==original


def test_sound_reload_advances_cp_and_audio_but_keeps_filter_references(tmp_path):
    source=tmp_path/'baseline';(source/'resources').mkdir(parents=True)
    (source/'cpapp-b.bin').write_bytes(b'old CP')
    (source/'resources/title.dat').write_bytes(b'current look names')
    (source/'audio').mkdir();(source/'audio/custom-shutter-a.bin').write_bytes(b'old sound')
    output=tmp_path/'job';output.mkdir()
    class Connection:
        def read(self,path,missing=False):
            return {'/cp/cpapp-b.bin':b'CP with current sound',
                '/usr/share/avsystemsound/custom.txt':b'current CSV',
                '/usr/share/avsystemsound/custom-shutter-b.bin':b'current sound'}.get(path,b'')
    target=Path(sshupdates.sound_baseline(source,output,Connection()))
    assert (target/'cpapp-b.bin').read_bytes()==b'CP with current sound'
    assert (target/'resources/title.dat').read_bytes()==b'current look names'
    assert (target/'audio/custom.txt').read_bytes()==b'current CSV'
    assert not (target/'audio/custom-shutter-a.bin').exists()
    assert (source/'cpapp-b.bin').read_bytes()==b'old CP'


def test_pending_sound_task_stops_filter_publication(tmp_path):
    args=dict(workspace=str(tmp_path/'update'),baseline='baseline',operations=[dict(slot=1,action='restore')],
        bind_ip='192.168.1.2',power_confirmed=True)
    with patch.object(sshupdates,'Connection'),patch('desktopapp.cameraapi.call',return_value=dict(state='pending_reload')),\
         patch.object(sshupdates,'compile_look') as compile,patch.object(sshupdates,'apply') as apply:
        with pytest.raises(ValueError,match='断电重开'):worker.run('ssh_save_looks',args,tmp_path/'job')
    compile.assert_not_called();apply.assert_not_called()


def test_unverified_filter_update_stops_sound_before_connecting(tmp_path):
    prior=tmp_path/'look';prior.mkdir()
    (prior/'update.private.json').write_text(json.dumps(dict(phase='AWAITING_RELOAD')))
    args=dict(workspace=str(tmp_path/'update'),selection='electronic',enabled=True,
        bind_ip='192.168.1.2',previous_look_update=str(prior),power_confirmed=True)
    with patch.object(sshupdates,'Connection') as connection:
        with pytest.raises(ValueError,match='滤镜页核对'):worker.run('ssh_sound_switch',args,tmp_path/'job')
    connection.assert_not_called()


def test_host_only_prepared_filter_does_not_block_sound(tmp_path):
    prior=tmp_path/'look';prior.mkdir()
    (prior/'update.private.json').write_text(json.dumps(dict(phase='PREPARED')))
    args=dict(workspace=str(tmp_path/'update'),selection='electronic',enabled=True,
        bind_ip='192.168.1.2',previous_look_update=str(prior),power_confirmed=True)
    with patch.object(sshupdates,'Connection'),patch('desktopapp.cameraapi.call',return_value=dict(state='pending_reload')) as call:
        result=worker.run('ssh_sound_switch',args,tmp_path/'job')
    assert result['phase']=='AWAITING_RELOAD' and call.call_count==1


@pytest.mark.parametrize('selection',['electronic','mechanical','both'])
def test_usb_consumes_same_adjusted_payload_before_device_boundary(tmp_path,selection):
    import targeted_sound,trial
    root=tmp_path/'sound'
    sound.run('sound_generate',dict(workspace=str(root),frequency=880,duration=.08))
    sound.run('sound_volume',dict(workspace=str(root),decibels=-3))
    adjusted=sound.converted_file(root).read_bytes()
    class CameraBoundary(Exception):pass
    with patch.object(targeted_sound,'configuration',wraps=targeted_sound.configuration) as configuration,\
         patch.object(trial,'factory',side_effect=CameraBoundary) as factory:
        with pytest.raises(CameraBoundary):sound.run('sound_install',dict(workspace=str(root),sound_target=selection,firmware='2.01',power_confirmed=True))
    assert configuration.call_args.args[1:]==(adjusted,selection)
    factory.assert_called_once()
