"""Empty/wrong trust sources stop locally; preparation is not device enrollment."""
import json
from unittest.mock import Mock,patch
import pytest
from PySide6 import QtWidgets as W
from desktopapp import firmwaretrust,window,jobs

LIBRARIES=('libsdfileinputupdaterapi.so','libseninputupdaterapi.so','libupdaterapi.so','libuudfileinputupdaterapi.so')


def source_fixture(tmp_path):
    source=tmp_path/'source';(source/'usr/lib').mkdir(parents=True)
    for name in LIBRARIES:(source/'usr/lib'/name).write_bytes(b'synthetic source')
    return source


@pytest.mark.parametrize('source',['',' ',None])
def test_empty_source_never_becomes_working_directory(tmp_path,source):
    target=tmp_path/'output'
    with patch.object(firmwaretrust,'signing_paths') as keys:
        with pytest.raises(ValueError,match='请先选择更新器解包目录'):
            firmwaretrust.prepare(dict(updater_root=source,workspace=str(target)),tmp_path)
    keys.assert_not_called()
    assert not target.exists()


def test_non_directory_and_missing_source_files_are_explained(tmp_path):
    with pytest.raises(ValueError,match='不存在'):firmwaretrust.validate_source(tmp_path/'absent')
    path=tmp_path/'file';path.write_text('fixture')
    with pytest.raises(ValueError,match='不是文件夹'):firmwaretrust.validate_source(path)
    source=tmp_path/'incomplete';source.mkdir()
    with pytest.raises(ValueError,match='不是完整的 C2 更新器解包根目录') as error:
        firmwaretrust.validate_source(source)
    assert all(name in str(error.value) for name in LIBRARIES)


@pytest.mark.parametrize('output',['',' '])
def test_empty_output_stops_before_key_generation(tmp_path,output):
    source=source_fixture(tmp_path)
    with patch.object(firmwaretrust,'signing_paths') as keys:
        with pytest.raises(ValueError,match='请选择新的输出目录'):
            firmwaretrust.prepare(dict(updater_root=str(source),workspace=output),tmp_path)
    keys.assert_not_called()


def test_existing_output_is_preserved(tmp_path):
    source=source_fixture(tmp_path);target=tmp_path/'output';target.mkdir()
    (target/'evidence.txt').write_bytes(b'keep original evidence')
    with patch.object(firmwaretrust,'signing_paths') as keys:
        with pytest.raises(ValueError,match='输出目录已存在'):
            firmwaretrust.prepare(dict(updater_root=str(source),workspace=str(target)),tmp_path)
    keys.assert_not_called()
    assert (target/'evidence.txt').read_bytes()==b'keep original evidence'


@pytest.fixture
def view(monkeypatch,tmp_path):
    app=W.QApplication.instance() or W.QApplication([])
    monkeypatch.setattr(window,'load_settings',lambda:{})
    monkeypatch.setattr(window,'data_root',lambda:tmp_path/'app')
    result=window.Window();result.timer.stop()
    yield result
    result.close()


def test_blank_source_blocks_only_advanced_offline_preparation(view):
    assert not view.trust_prepare_button.isEnabled()
    assert view.trust_install_button.isEnabled()
    assert not view.trust_restore_button.isEnabled()
    assert not view.trust_verify_button.isEnabled()
    assert 'USB' in view.trust_install_button.text()
    assert '请先选择' in view.trust_hint.text()


def test_ui_recognizes_valid_source_and_preserves_output_rule(view,tmp_path):
    source=source_fixture(tmp_path)
    view.trust_advanced.setChecked(True)
    view.fields['trust_source'].setText(str(source))
    assert view.trust_prepare_button.isEnabled()
    view.fields['trust_output'].setText(str(tmp_path))
    assert not view.trust_prepare_button.isEnabled()
    assert '已存在' in view.trust_hint.text()
    assert view.trust_install_button.isEnabled()


def test_direct_gui_launch_checks_source_before_creating_worker(view,tmp_path):
    with patch.object(jobs,'new_job') as job,patch.object(W.QMessageBox,'information') as popup:
        view.launch('firmware_trust_prepare',dict(updater_root='',workspace=str(tmp_path/'output')))
    job.assert_not_called();popup.assert_called_once()
    assert '请先选择' in popup.call_args.args[2]


def test_other_job_completion_does_not_enable_empty_trust_action(view,tmp_path):
    job=tmp_path/'job';job.mkdir()
    (job/'status.private.json').write_text(json.dumps(dict(phase='SUCCEEDED',action='compile_look',result={})))
    view.current_job=job;view.process=Mock()
    view.finished(0,None)
    assert not view.trust_prepare_button.isEnabled()
    assert view.trust_install_button.isEnabled()
