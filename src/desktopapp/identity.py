"""Application signing identity. Private signing material stays on the host."""
import os
from pathlib import Path
from .paths import ROOT,data_root

SSH_USER='root'
SSH_PASSWORD='A7C2Tools'


def ensure_signing(folder):
    from Cryptodome.PublicKey import RSA
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    private=folder/'firmware.private.pem';public=folder/'firmware.public.pem'
    if not private.exists():
        key=RSA.generate(2048)
        with private.open('xb') as stream:stream.write(key.export_key(format='PEM',pkcs=8))
    key=RSA.import_key(private.read_bytes())
    if not key.has_private() or key.size_in_bits()!=2048:raise ValueError('Application signing identity is invalid')
    expected=key.public_key().export_key(format='PEM')
    if public.exists():
        actual=RSA.import_key(public.read_bytes())
        if actual.has_private() or (actual.n,actual.e)!=(key.n,key.e):raise ValueError('Application signing public key differs')
    else:
        with public.open('xb') as stream:stream.write(expected)
    return private,public


def signing_paths():
    bundled=ROOT/'desktop-assets/identity'
    if (bundled/'firmware.private.pem').is_file():return ensure_signing(bundled)
    return ensure_signing(os.environ.get('A7C2_DISTRIBUTION_IDENTITY') or data_root()/'identity')
