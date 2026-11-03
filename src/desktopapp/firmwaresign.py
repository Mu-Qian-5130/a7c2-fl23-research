"""Encrypt and sign an already-built local C2 FDAT, with no device access.

Produces a research DAT for a separately initialized owner trust policy. A
cryptographically correct container does not establish target trust or boot.
"""
from __future__ import annotations

from array import array
import hashlib
import io
from pathlib import Path
import struct
import sys
import zlib

from .firmwarelocal import MODEL, tools


def crypto():
    try:
        from Cryptodome.Cipher import AES
        from Cryptodome.Hash import SHA256
        from Cryptodome.PublicKey import RSA
        from Cryptodome.Signature import pkcs1_15
        from Cryptodome.Random import get_random_bytes
    except ImportError:
        from Crypto.Cipher import AES
        from Crypto.Hash import SHA256
        from Crypto.PublicKey import RSA
        from Crypto.Signature import pkcs1_15
        from Crypto.Random import get_random_bytes
    return AES, SHA256, RSA, pkcs1_15, get_random_bytes


def encrypt_stream(source, destination, private_key, *, iv=None):
    """CXD90057 k8: 1020-byte payloads, native sums/end flag, CBC, IV, signature."""
    AES, SHA256, _, pkcs1_15, random_bytes = crypto()
    tools()
    from fwtool.sony import constants
    iv = random_bytes(16) if iv is None else iv
    if len(iv) != 16:
        raise ValueError('AES IV must contain 16 bytes')
    cbc = AES.new(constants.key_cxd90057_k8, AES.MODE_CBC, iv)
    ecb = AES.new(constants.key_aes, AES.MODE_ECB)
    digest = SHA256.new()
    plain_sha = hashlib.sha256()
    first = True
    batch = bytearray()
    data = source.read(1020)
    if not data:
        raise ValueError('Empty FDAT')
    while data:
        following = source.read(1020)
        plain_sha.update(data)
        block = struct.pack('<H', len(data) | (0 if following else 0x8000)) + data
        block += b'\xff' * (1022-len(block))
        words = array('H', block)
        if sys.byteorder != 'little':
            words.byteswap()
        batch += struct.pack('<H', sum(words) & 0xffff) + block
        if len(batch) >= 1024*4096 or not following:
            if first:
                encrypted = ecb.encrypt(bytes(batch[:512])) + cbc.encrypt(bytes(batch[512:]))
                first = False
            else:
                encrypted = cbc.encrypt(bytes(batch))
            destination.write(encrypted)
            digest.update(encrypted)
            batch.clear()
        data = following
    destination.write(iv)
    digest.update(iv)
    signature = pkcs1_15.new(private_key).sign(digest)
    if len(signature) != 256:
        raise ValueError('Expected an RSA-2048 signature')
    destination.write(signature)
    return dict(plaintext_sha256=plain_sha.hexdigest(), signed_stream_sha256=digest.hexdigest())


def verify_container(path, public_bytes, *, expected_plain_sha256=None):
    """Verify outer CRC, actual RSA signature and every native encrypted block."""
    _, SHA256, RSA, pkcs1_15, _ = crypto()
    fdat, dat, _, _ = tools()
    public = RSA.import_key(public_bytes)
    with Path(path).open('rb') as stream:
        outer = dat.readDat(stream)
        payload = outer.firmwareData
        payload.seek(0, 2)
        size = payload.tell()
        if size < 1296 or (size-272) % 1024:
            raise ValueError('Invalid signed C2 FDAT length')
        payload.seek(0)
        digest = SHA256.new()
        remaining = size-256
        while remaining:
            block = payload.read(min(4<<20,remaining))
            if not block:
                raise ValueError('Truncated signed stream')
            digest.update(block)
            remaining -= len(block)
        pkcs1_15.new(public).verify(digest,payload.read(256))
        # Use the pre-existing independent fwtool decrypter for readback.
        decoded = fdat._crypters['CXD90057_k8']().decrypt(payload)
        decoded.seek(0)
        prefix = decoded.read(fdat.FdatHeader.size)
        # fwtool's decrypted stream is sequential; its header parser needs a
        # seekable view only of the fixed header, not a second full-size copy.
        header = fdat.readFdat(io.BytesIO(prefix))
        if header.model != MODEL:
            raise ValueError('Signed candidate is not ILCE-7CM2')
        plain = hashlib.sha256()
        plain.update(prefix)
        while block := decoded.read(65536):
            plain.update(block)
        if expected_plain_sha256 and plain.hexdigest() != expected_plain_sha256:
            raise ValueError('Signed candidate plaintext readback differs')
    return dict(model='ILCE-7CM2',version=header.version,outer_crc_valid=True,
                rsa_signature_valid=True,native_block_checksums_valid=True,
                plaintext_sha256=plain.hexdigest())


def sign_candidate(plaintext, official_container, private_key_path, public_key_path, output):
    """Preserve the source DAT metadata and replace only FDAT and its outer CRC."""
    _, _, RSA, _, _ = crypto()
    fdat, dat, _, _ = tools()
    plaintext, official_container, output = map(Path, (plaintext,official_container,output))
    private = RSA.import_key(Path(private_key_path).read_bytes())
    public_bytes = Path(public_key_path).read_bytes()
    public = RSA.import_key(public_bytes)
    if not private.has_private() or public.has_private() or private.size_in_bits()!=2048:
        raise ValueError('Select a paired RSA-2048 private key and public-only PEM')
    if (private.n,private.e)!=(public.n,public.e):
        raise ValueError('Signing private key does not match the selected public key')
    with plaintext.open('rb') as source:
        header = fdat.readFdat(source)
        if header.model!=MODEL:
            raise ValueError('Select an ILCE-7CM2 FDAT')
    encrypted_size = ((plaintext.stat().st_size+1019)//1020)*1024+272
    output.parent.mkdir(parents=True,exist_ok=True)
    with official_container.open('rb') as original,output.open('xb') as dest:
        chunks,_ = dat.readChunks(original)
        if [kind for kind,_ in chunks].count(b'FDAT')!=1 or chunks[-1][0]!=b'DEND':
            raise ValueError('Expected exactly one FDAT and a final DEND')
        crc = 0
        def write(data):
            nonlocal crc
            dest.write(data)
            crc = zlib.crc32(data,crc)
        write(dat.datHeaderMagic)
        for kind,contents in chunks:
            if kind==b'DEND':
                dest.write(struct.pack('>I4sI',4,b'DEND',crc&0xffffffff))
            elif kind==b'FDAT':
                write(struct.pack('>I4s',encrypted_size,kind))
                class Sink:
                    def write(self, data):write(data)
                with plaintext.open('rb') as source:
                    result=encrypt_stream(source,Sink(),private)
            else:
                contents.seek(0,2);size=contents.tell();contents.seek(0)
                write(struct.pack('>I4s',size,kind))
                while block:=contents.read(65536):write(block)
    checked=verify_container(output,public_bytes,expected_plain_sha256=result['plaintext_sha256'])
    return dict(schema='a7c2-owner-signed-candidate/1',camera_io=False,phase='SIGNED_OFFLINE_CANDIDATE',
                candidate=str(output),public_key_sha256=hashlib.sha256(public_bytes).hexdigest(),
                trust_policy_required='same owner public-key pin installed separately',
                device_trust_initialized=False,card_flash_verified=False,device_ready=False,
                **(checked|result))
