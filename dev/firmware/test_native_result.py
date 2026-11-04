"""Completion evidence must establish full native consumption and output."""
import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('verify_native',Path(__file__).with_name('verify_native.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def evidence(**changes):
    row=dict(exception=0,input_bytes=2320,consumed=2048,output_bytes=2020,reads=1,ends=1,
             fs_writes=0,rsa_calls=1,key_redirects=2,crypto_inits=1,crypto_updates=2,crypto_finals=1,
             unexpected=0,sha256='a'*64,native_buffer_capacity=1609035776,native_ring_remainder=272,
             native_output_capacity=524288,native_output_remaining=0,consumer_failed=0,consumer_aborted=0)
    return row|changes

def test_complete_native_result():
    row=evidence()
    log='C2_NATIVE_BUFFER_CAPACITY bytes=1609035776 host_vm_allocation=true\nC2_NATIVE_RING_REMAINDER bytes=272\n'
    log+='C2_NATIVE_OUTPUT_CAPACITY bytes=524288\n'
    log+='C2_NATIVE_OUTPUT_RESULT reads=1 ends=1 remaining=0 consumer_failed=0 aborted=0\n'
    log+='C2_PIPELINE_RESULT '+' '.join(f'{k}={v}' for k,v in row.items() if not k.startswith(('native_','consumer_')))+'\n'
    assert module.parse_result(log)==row
    assert module.assess(row,returncode=0,plaintext_bytes=2020,plaintext_sha256='a'*64)

@pytest.mark.parametrize('changed',[dict(consumed=1024),dict(sha256='b'*64),dict(ends=0),
    dict(fs_writes=1),dict(unexpected=1),dict(crypto_finals=0),dict(native_ring_remainder=0),
    dict(crypto_updates=1),dict(rsa_calls=0),dict(output_bytes=0),dict(reads=0),
    dict(native_output_remaining=10),dict(native_output_capacity=0),dict(consumer_failed=1),dict(consumer_aborted=1)])
def test_incomplete_or_wrong_result_is_not_success(changed):
    assert not module.assess(evidence(**changed),returncode=0,plaintext_bytes=2020,plaintext_sha256='a'*64)

def test_timeout_or_stage_logs_are_not_completion():
    with pytest.raises(ValueError):module.parse_result('PIPELINE_PROGRESS input=0 output=4096\n')
    assert not module.assess(evidence(),returncode=124,plaintext_bytes=2020,plaintext_sha256='a'*64)

def test_rejection_must_precede_any_output():
    reject=evidence(exception=1,output_bytes=0,reads=0,ends=0,consumer_aborted=1)
    assert module.assess(reject,returncode=1,plaintext_bytes=2020,plaintext_sha256='a'*64,expected_rejection=True)
    assert not module.assess(reject|dict(output_bytes=1),returncode=1,plaintext_bytes=2020,plaintext_sha256='a'*64,expected_rejection=True)

def test_output_evidence_is_required_and_consistent():
    log='C2_NATIVE_BUFFER_CAPACITY bytes=1609035776 host_vm_allocation=true\nC2_NATIVE_RING_REMAINDER bytes=272\n'
    row=evidence()
    log+='C2_PIPELINE_RESULT '+' '.join(f'{k}={v}' for k,v in row.items() if not k.startswith(('native_','consumer_')))+'\n'
    with pytest.raises(ValueError,match='Missing native output-ring evidence'):module.parse_result(log)
    log+='C2_NATIVE_OUTPUT_CAPACITY bytes=524288\nC2_NATIVE_OUTPUT_RESULT reads=0 ends=1 remaining=0 consumer_failed=0 aborted=0\n'
    with pytest.raises(ValueError,match='Conflicting native output-ring evidence'):module.parse_result(log)


def test_connected_decode_requires_callback_and_exact_host_image():
    header='C2_CONNECTED_HEADER_CALLBACK phase=2 major=3 minor=1 model=20030014 region=00000000 cancel=1\n'
    row='C2_CONNECTED_RESULT callbacks=1 body_execution=0 body_opens=1 body_closes=1 body_bytes=100 mounts_blocked=1 metadata_reads=1 unknown_io=0\n'
    args=dict(expected_info=(3,1,0x20030014,0),expected_image_bytes=100,image_bytes=100,
              expected_sha256='a'*64,image_sha256='a'*64)
    assert module.assess_connected(header+row,**args)
    for log in [row,header+row+row,(header+row).replace('body_execution=0','body_execution=1'),
                (header+row).replace('body_bytes=100','body_bytes=99'),
                (header+row).replace('major=3','major=2'),(header+row).replace('unknown_io=0','unknown_io=1')]:
        assert not module.assess_connected(log,**args)
    assert not module.assess_connected(header+row,**(args|dict(image_sha256='b'*64)))
    rejected='C2_CONNECTED_RESULT callbacks=0 body_execution=0 body_opens=0 body_closes=0 body_bytes=0 mounts_blocked=0 metadata_reads=0 unknown_io=0\n'
    assert module.assess_connected(rejected,**(args|dict(image_bytes=0,expected_rejection=True)))
    assert not module.assess_connected(header+rejected,**(args|dict(image_bytes=0,expected_rejection=True)))
