"""Exercise real DAT, FDAT and cryptographic boundaries with synthetic content."""
import io
from pathlib import Path
import struct
import sys
import zlib

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from desktopapp.firmwaresign import crypto, encrypt_stream, sign_candidate, verify_container
from desktopapp.firmwarelocal import MODEL, tools


@pytest.fixture(scope='module')
def keys():
    _,_,RSA,_,_=crypto()
    a,b=RSA.generate(2048),RSA.generate(2048)
    return a,b


def plain_fdat(extra):
    fdat,_,_,_=tools()
    out=io.BytesIO()
    fdat.writeFdat(fdat.FdatFile(MODEL,0x20,'3.01',False,io.BytesIO(extra),io.BytesIO(b'aux')),out)
    return out.getvalue()


@pytest.mark.parametrize('length',[1,1019,1020,1021,3071])
def test_native_block_boundaries(length,keys):
    fdat,_,_,_=tools()
    raw=bytes(i%251 for i in range(length))
    out=io.BytesIO()
    encrypt_stream(io.BytesIO(raw),out,keys[0],iv=bytes(range(16)))
    decoded=fdat._crypters['CXD90057_k8']().decrypt(io.BytesIO(out.getvalue()))
    assert decoded.read()==raw


def fixture_files(tmp_path,keys):
    _,dat,_,_=tools()
    public=keys[0].public_key().export_key()+b'\n'
    plain=tmp_path/'candidate.bin';plain.write_bytes(plain_fdat(bytes(range(256))*13))
    original=tmp_path/'official-template.dat'
    with original.open('w+b') as stream:
        dat.writeDat(dat.DatFile([(0x054c,0x0e8a)],[(0x054c,0x0336)],False,io.BytesIO(b'template')),stream)
    priv=tmp_path/'private.pem';priv.write_bytes(keys[0].export_key())
    pub=tmp_path/'public.pem';pub.write_bytes(public)
    return plain,original,priv,pub,tmp_path/'owner.RESEARCH.DAT'


def test_signed_dat_roundtrip_and_metadata(tmp_path,keys):
    files=fixture_files(tmp_path,keys)
    report=sign_candidate(*files)
    assert report['rsa_signature_valid'] and report['native_block_checksums_valid']
    assert report['plaintext_byte_readback'] and report['plaintext_bytes']==files[0].stat().st_size
    assert not any('sha256' in key or 'hash' in key for key in report)
    assert report['version']=='3.01'
    assert not report['device_ready'] and not report['device_trust_initialized']
    _,dat,_,_=tools()
    with files[-1].open('rb') as stream:
        out=dat.readDat(stream)
        assert out.normalUsbDescriptors==[(0x054c,0x0e8a)]
        assert out.updaterUsbDescriptors==[(0x054c,0x0336)]
    # An attacker can repair the outer CRC; it must still fail actual RSA.
    raw=bytearray(files[-1].read_bytes())
    at=raw.index(b'FDAT')+4
    raw[at+100]^=1
    struct.pack_into('>I',raw,len(raw)-4,zlib.crc32(raw[:-12])&0xffffffff)
    files[-1].write_bytes(raw)
    with pytest.raises(ValueError):verify_container(files[-1],files[3].read_bytes())


def test_wrong_key_pair_rejected_before_output(tmp_path,keys):
    files=fixture_files(tmp_path,keys)
    files[3].write_bytes(keys[1].public_key().export_key())
    with pytest.raises(ValueError,match='does not match'):sign_candidate(*files)
    assert not files[-1].exists()


def test_wrong_verification_key_rejected(tmp_path,keys):
    files=fixture_files(tmp_path,keys)
    sign_candidate(*files)
    with pytest.raises(ValueError):verify_container(files[-1],keys[1].public_key().export_key())


@pytest.mark.parametrize('change',['byte','short','long'])
def test_plaintext_readback_compares_all_bytes_and_length(tmp_path,keys,change):
    files=fixture_files(tmp_path,keys)
    sign_candidate(*files)
    raw=files[0].read_bytes()
    changed=raw[:-1]+bytes((raw[-1]^1,)) if change=='byte' else raw[:-1] if change=='short' else raw+b'\0'
    files[0].write_bytes(changed)
    with pytest.raises(ValueError,match='plaintext readback differs'):
        verify_container(files[-1],files[3].read_bytes(),expected_plaintext=files[0])


def test_desktop_build_finalizes_with_the_real_signer(tmp_path,keys):
    from desktopapp.firmwarelocal import finish_signing
    plain,original,priv,pub,_=fixture_files(tmp_path,keys)
    report=dict(signed=False,card_flash_ready=False)
    finish_signing(dict(sony_firmware=str(original),signing_private_key=str(priv),
                       signing_public_key=str(pub)),plain,tmp_path,report)
    assert report['signed'] and not report['card_flash_ready']
    assert report['signature_validation']['rsa_signature_valid']
    assert Path(report['candidate']).name=='candidate.RESEARCH.DAT'
