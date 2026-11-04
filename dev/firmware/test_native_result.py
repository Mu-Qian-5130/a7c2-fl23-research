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
