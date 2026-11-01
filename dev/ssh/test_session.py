"""Host transaction boundaries for the experimental SSH path; no physical USB."""
import importlib.util
import json
from pathlib import Path
import struct
from unittest.mock import patch

import pytest

spec=importlib.util.spec_from_file_location('ssh_session',Path(__file__).with_name('session.py'))
ssh=importlib.util.module_from_spec(spec);spec.loader.exec_module(ssh)


def test_public_key_does_not_accept_private_material_or_authorized_key_options():
    import base64
    blob=b'\0\0\0\x0bssh-ed25519\0\0\0\x20'+bytes(range(32))
    key=b'ssh-ed25519 '+base64.b64encode(blob)+b' owner\n'
    assert ssh.public_key(key)==key.removesuffix(b' owner\n')+b'\n'
    for bad in (b'-----BEGIN OPENSSH PRIVATE KEY-----',b'command="sh" '+key,b'ssh-ed25519 !!!',b'ssh-ed25519 AAAA'):
        with pytest.raises(ValueError):ssh.public_key(bad)


@pytest.mark.parametrize('ip',['0.0.0.0','127.0.0.1','224.0.0.1','192.168.1.2;reboot','::1'])
def test_invalid_bind_addresses_rejected(ip):
    with pytest.raises(ValueError):ssh.ipv4(ip)


def test_listener_requires_exact_address_port_and_listen_state():
    assert ssh.listening(b'header\n 0: 6301A8C0:08AE 00000000:0000 0A rest\n','192.168.1.99')
    for raw in (b'header\n 0: 6301A8C0:0016 00000000:0000 0A\n',
                b'header\n 0: 6301A8C0:08AE 00000000:0000 01\n'):
        assert not ssh.listening(raw,'192.168.1.99')


def test_report_failure_and_partial_acknowledgement_never_count_as_success():
    valid=ssh.REPORT.pack(b'A7SSR001',1,3,0,100,0)
    assert ssh.parse(valid,3)['pid']==100
    for raw in (valid[:-1],ssh.REPORT.pack(b'A7SSR001',1,3,-110,100,0)):
        with pytest.raises(ValueError):ssh.parse(raw,3)
    with pytest.raises(ValueError):ssh.parse(valid,4)


def test_proc_report_requires_complete_bounded_contents_not_stat_size():
    parts=[b'00000000-0000-0000-0000-000000000001\n']+[b'x']*6
    data=b''.join(parts)
    raw=ssh.REPORT.pack(b'A7SSR001',1,6,0,0,len(data))+struct.pack('<7I',*[len(p) for p in parts])+data
    assert ssh.parse(raw,6)['snapshots'][ssh.PROC_PATHS[0]].endswith('0001\n')
    with pytest.raises(ValueError):ssh.parse(raw[:-1],6)


def test_host_journal_is_saved_before_usb_and_unknown_attempt_is_not_replayed(tmp_path):
    state={'schema':'a7c2-temporary-ssh/1','phase':'PREPARED','session_path':'/tmp_wbshd/a7c2-ssh-'+'a'*16}
    calls=[]
    class Camera:
        def __init__(self,*args):
            recorded=json.loads((tmp_path/'session.private.json').read_text())
            assert recorded['phase']=='START_ATTEMPTED'
            calls.append('open')
        def __enter__(self):raise TimeoutError('simulated USB authentication failure')
        def __exit__(self,*args):pass
    with patch.object(ssh,'load',return_value=(tmp_path,state)):
        with pytest.raises(TimeoutError):ssh.run_device(tmp_path,'start',camera_factory=Camera)
        assert state['phase']=='NEEDS_REVIEW'
        with pytest.raises(ValueError,match='never replay'):ssh.run_device(tmp_path,'start',camera_factory=Camera)
    assert calls==['open']


def test_persistence_is_not_enabled_by_emulation_or_a_missing_acceptance_receipt(tmp_path):
    state={'ssh_login_verified':False,'source_boot_id':'camera-boot'}
    with patch.object(ssh,'load',return_value=(tmp_path,state)):
        report=ssh.persistence_readiness(tmp_path)
    assert not report['ready_for_startup_design'] and not report['startup_implemented']
    assert 'physical SSH login with pinned host key' in report['missing_physical_evidence']
    assert report['camera_io'] is False


def test_login_verification_pins_host_key_and_compares_the_usb_boot(tmp_path):
    (tmp_path/'hostkey').write_bytes(bytes(51)+bytes(range(32)))
    state={'phase':'LISTENING','bind_ip':'192.168.1.99','source_boot_id':'expected-boot'}
    with patch.object(ssh,'load',return_value=(tmp_path,state)),patch.object(ssh.shutil,'which',return_value='ssh'), \
         patch.object(ssh.subprocess,'run') as runner:
        runner.return_value.returncode=0
        runner.return_value.stdout='A7C2_SSH_OK\naarch64\nUid:\t0\t0\t0\t0\nwrong-boot\n';runner.return_value.stderr=''
        with pytest.raises(ValueError):ssh.verify_login(tmp_path,'client-key')
        assert not state.get('ssh_login_verified')
        runner.return_value.stdout='A7C2_SSH_OK\naarch64\nUid:\t0\t0\t0\t0\nexpected-boot\n'
        assert ssh.verify_login(tmp_path,'client-key')['ssh_login_verified']
    command=runner.call_args.args[0]
    assert 'StrictHostKeyChecking=yes' in command
    assert '/bin/busybox id ' not in command[-1]
    assert (tmp_path/'known_hosts').read_text().startswith('[192.168.1.99]:2222 ssh-ed25519 ')
