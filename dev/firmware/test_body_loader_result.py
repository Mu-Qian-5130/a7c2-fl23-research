"""A callback probe must stop before body execution and retain failure stages."""
import importlib.util
from pathlib import Path

import pytest

spec=importlib.util.spec_from_file_location('verify_body_loader',Path(__file__).with_name('verify_body_loader.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
INFO=(3,1,0x20030014,0)
CALLBACK='C2_BODY_HEADER_CALLBACK phase=2 major=3 minor=1 model=20030014 region=00000000 cancel=1\n'


def result(mode='valid',**changes):
    valid=mode=='valid'
    row=dict(exception=int(not valid),callbacks=int(valid),body_calls=0,mounts_blocked=int(valid),
             version_reads=int(valid),writes=0,unknown_io=0,remaining=511 if mode=='truncated' else 0)|changes
    return (CALLBACK if valid else '')+'C2_BODY_LOADER_RESULT mode='+mode+' '+ ' '.join(f'{k}={v}' for k,v in row.items())+'\n'


@pytest.mark.parametrize('mode',['valid','bad_crc','truncated'])
def test_expected_native_path(mode):
    assert module.assess(result(mode),mode=mode,returncode=0,expected_info=INFO)


@pytest.mark.parametrize('changes',[dict(body_calls=1),dict(writes=1),dict(unknown_io=1),
                                  dict(callbacks=0),dict(mounts_blocked=0),dict(version_reads=0)])
def test_unexpected_path_is_rejected(changes):
    assert not module.assess(result(**changes),mode='valid',returncode=0,expected_info=INFO)


def test_callback_identity_and_completion_are_required():
    for log in (result().replace('major=3','major=2'),result().replace('cancel=1','cancel=0'),
                result()+result(),CALLBACK):
        assert not module.assess(log,mode='valid',returncode=0,expected_info=INFO)
    assert not module.assess(result(),mode='valid',returncode=124,expected_info=INFO)
    assert not module.assess(CALLBACK+result('bad_crc'),mode='bad_crc',returncode=0,expected_info=INFO)


def test_body_extent_and_native_extraction_evidence(tmp_path):
    header=bytearray(512)
    header[0x30:0x34]=(1024).to_bytes(4,'little')
    header[0x38:0x3c]=(1).to_bytes(4,'little');header[0x40]=0x55
    header[0x44:0x48]=(512).to_bytes(4,'little');header[0x48:0x4c]=(512).to_bytes(4,'little')
    assert module.body_layout(header,1024)==(1024,512,512)
    path=tmp_path/'fixture.bin';path.write_bytes(b'a'*512+b'b'*512)
    assert module.slice_digest(path,512,512)==module.hashlib.sha256(b'b'*512).hexdigest()
    log='C2_BODY_IMAGE_RESULT exception=0 prefix=1024 fed=1024 written=512 remaining=0 opens=1 closes=1 unknown=0 unexpected_writes=0\n'
    args=dict(returncode=0,prefix=1024,image_bytes=512,actual_bytes=512,expected_sha256='a'*64,actual_sha256='a'*64)
    assert module.assess_image(log,**args)
    for changed in [dict(returncode=124),dict(actual_bytes=511),dict(actual_sha256='b'*64)]:
        assert not module.assess_image(log,**(args|changed))
    for bad in [log.replace('remaining=0','remaining=1'),log.replace('unexpected_writes=0','unexpected_writes=1'),log+log]:
        assert not module.assess_image(bad,**args)
    with pytest.raises(ValueError,match='Truncated'):module.slice_digest(path,512,513)
    header[0x48:0x4c]=(513).to_bytes(4,'little')
    with pytest.raises(ValueError,match='extent'):module.body_layout(header,1025)
