"""The shared custom-sound entry forwards the selected capture target."""
from unittest.mock import patch
import pytest
from PySide6 import QtWidgets as W
from desktopapp import window
from desktopapp.actions import sound


@pytest.fixture(scope='module')
def app():return W.QApplication.instance() or W.QApplication([])


def test_local_firmware_dependencies_and_mandatory_voice_cleanup(app):
    with patch.object(window,'load_settings',return_value={}):view=window.Window()
    assert view.local_voice.isChecked() and not view.local_voice.isEnabled()
    assert not hasattr(view,'local_precapture')
    assert not any('预拍摄' in box.text() for box in view.pages.widget(9).findChildren(W.QCheckBox))
    assert view.firmware_args()['precapture'] is False
    assert all(box.isChecked() for box in (view.local_fl23,view.local_wb,view.local_sound,view.local_looks,
        view.local_vertical,view.local_presets,view.local_ssh))
    assert view.local_ssh.text()=='加入索尼云创内置接口'
    assert view.local_looks.text()=='应用自定义外观'
    assert not any(key in view.fields for key in ('firmware_client_key','firmware_signing_private','firmware_signing_public','ssh_update_private','ssh_host_public'))
    assert not view.nav_items[2].isHidden() and view.nav_items[2].text()=='一键恢复'
    assert view.firmware_args()['automatic_identity']
    view.local_ssh.setChecked(True)
    assert view.firmware_args()['custom_looks'] and view.firmware_args()['ssh']
    view.local_looks.setChecked(False)
    assert not view.local_ssh.isEnabled() and not view.local_ssh.isChecked()
    assert view.local_looks_panel.isHidden()
    assert view.firmware_args()['preset_pack'] is None
    view.local_looks.setChecked(True)
    assert view.local_ssh.isEnabled() and view.local_presets.isEnabled()
    view.local_vertical.setChecked(True)
    assert view.firmware_args()['vertical'] and view.firmware_args()['voice_cleanup']
    view.close()


@pytest.mark.parametrize('selection',['mechanical','electronic','both'])
def test_save_button_sends_the_current_target(app,selection):
    with patch.object(window,'load_settings',return_value={}):view=window.Window()
    view.sound_electronic.setChecked(selection in ('electronic','both'))
    view.sound_mechanical.setChecked(selection in ('mechanical','both'))
    button=next(b for b in view.findChildren(W.QPushButton) if b.text()=='保存到所选快门')
    with patch.object(view,'launch') as launch:button.click()
    assert launch.call_args.args[0]=='sound_install'
    assert launch.call_args.args[1]['sound_target']==selection
    assert all(view.findChild(W.QPushButton,'switch_'+selection+'_'+operation) is not None
        for selection in ('mechanical','electronic') for operation in ('on','off'))
    view.close()


def test_targeted_save_does_not_fall_through_to_the_legacy_electronic_installer():
    with patch('targeted_sound.run',return_value=dict(sound_target='mechanical')) as save:
        result=sound.run('sound_install',dict(sound_target='mechanical',workspace='selected'))
    assert result['sound_target']=='mechanical'
    assert save.call_args.args[0]['sound_target']=='mechanical'
