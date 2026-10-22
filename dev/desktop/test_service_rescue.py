"""A read-only session whose channel failed returns the body from 0336."""
from unittest.mock import Mock
import pytest
from looktool import devicesession

transport, _ = devicesession.modules()


@pytest.fixture
def usb(monkeypatch):
    auths = []
    def auth(driver):
        device = Mock()
        auths.append(device)
        return device
    monkeypatch.setattr(transport.sys, 'platform', 'linux')
    monkeypatch.setattr(transport, 'get_device', Mock(return_value='service-device'))
    monkeypatch.setattr(transport, 'GenericUsbDriver', lambda backend: backend)
    monkeypatch.setattr(transport, 'Bounded', lambda dev, budget=180: dev)
    monkeypatch.setattr(transport, 'SonySenserAuthDevice', auth)
    monkeypatch.setattr(transport.usb.util, 'dispose_resources', lambda dev: None)
    return auths


def session():
    value = transport.Session()
    value.dev = 'dead-channel'
    value.auth = Mock()
    value.channel = Mock()
    value.camera = Mock()
    value.backend = Mock()
    return value


def test_failed_read_only_session_sends_stop_on_a_fresh_handle(usb):
    value = session()
    value.channel.sendSenserPacket.side_effect = transport.SenserProtocolError('Wrong senser sequence')
    with pytest.raises(transport.SenserProtocolError):
        value.read('/tmp/jiritsu/../../usr/share/app/string_arabic_horizontal.uxc')
    assert not value.healthy and not value.mutating
    value.__exit__(None, None, None)
    value.auth.stop.assert_not_called()          # the broken channel is not reused
    assert len(usb) == 1 and usb[0].stop.called  # a fresh handle exits service mode


@pytest.mark.parametrize('write', ['temp', 'remove', 'cp', 'ap', 'save'])
def test_session_that_sent_any_write_is_never_auto_stopped(usb, write):
    value = session()
    value.channel.sendSenserPacket.return_value = (0, bytes(4))
    if write == 'temp': value.temp('a7c2.probe.result', b'x')
    elif write == 'remove': value.temp('a7c2.probe.result', remove=True)
    elif write == 'cp': value.cp_write(transport.core.CP_KEYS[0], bytes(8192))
    elif write == 'ap': value.ap_write(transport.core.AP_KEYS[0], b'\0')
    else: value.call(Mock(__name__='saveBackup'), 0x02cf)
    assert value.mutating
    value.healthy = False
    value.__exit__(None, None, None)
    assert usb == []


def test_recovery_session_never_auto_stops(usb, monkeypatch):
    value = transport.RecoverySession({'model': 'other'})
    with pytest.raises(ValueError):
        value.__enter__()
    assert value.mutating
