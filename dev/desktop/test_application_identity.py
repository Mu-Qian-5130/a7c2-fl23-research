"""Automatic signing is stable and sends public material only to camera policy files."""
from pathlib import Path
from unittest.mock import patch
import pytest
from Cryptodome.PublicKey import RSA
from desktopapp import identity,firmwaretrust


def test_generated_signing_identity_is_persistent(tmp_path):
    private,public=identity.ensure_signing(tmp_path)
    original=private.read_bytes()
    again=identity.ensure_signing(tmp_path)
    assert again==(private,public) and private.read_bytes()==original
    assert RSA.import_key(original).has_private()
    assert not RSA.import_key(public.read_bytes()).has_private()


def test_mismatched_key_does_not_silently_replace_identity(tmp_path):
    private,public=identity.ensure_signing(tmp_path)
    public.write_bytes(RSA.generate(2048).public_key().export_key())
    with pytest.raises(ValueError):identity.ensure_signing(tmp_path)
    assert private.exists()


def test_trust_preparation_uses_only_public_key(tmp_path):
    from desktopapp import firmwaretrust
    pair=identity.ensure_signing(tmp_path/'identity')
    source=tmp_path/'source';(source/'usr/lib').mkdir(parents=True)
    names=('libsdfileinputupdaterapi.so','libseninputupdaterapi.so','libupdaterapi.so','libuudfileinputupdaterapi.so')
    for name in names:(source/'usr/lib'/name).write_bytes(b'original')
    with patch.object(firmwaretrust,'signing_paths',return_value=pair),patch('importlib.util.module_from_spec') as create:
        module=create.return_value;module.LIBRARIES=names;module.pin_library.return_value=(b'patched',{})
        with patch('importlib.util.spec_from_file_location') as spec:
            report=firmwaretrust.prepare(dict(updater_root=source,workspace=tmp_path/'output'),tmp_path)
    assert not report['first_install_implemented'] and not report['camera_io']
    assert (tmp_path/'output/etc/VerificationKey.pem').read_bytes()==pair[1].read_bytes()
    assert not any(b'PRIVATE KEY' in p.read_bytes() for p in (tmp_path/'output').rglob('*') if p.is_file())
