"""Prevent packaging an old WBI with new programs; check nonblocking SSH dispatch."""
import hashlib
import io
import os
from pathlib import Path
import signal
import subprocess
import tarfile
import time
import zlib

import pytest
from desktopapp import firmwarelocal, firmwarewbi, sshboot


def test_wbi_full_extent_and_sum_update(tmp_path):
    # Cross the streaming boundary and retain a nonzero final byte.
    payload=b'WBI2'+bytes(range(256))*17000+b'last-byte\xff'
    source=tmp_path/'original.img';source.write_bytes(payload)
    output=tmp_path/'modified.img'
    report=firmwarewbi.invalidate_packaged_wbi(source,output)
    actual=output.read_bytes()
    assert source.read_bytes()==payload
    assert actual==b'WBI3'+payload[4:]
    assert report['changed_offsets']==[3] and report['all_other_bytes_preserved']
    assert report['bytes']==len(payload)
    assert report['source_sha256']==hashlib.sha256(payload).hexdigest()
    assert report['output_sha256']==hashlib.sha256(actual).hexdigest()
    manifest=('0,%08x,%08x,000001a4,0,0,root,root,-1,-1,dev/nflasha5,\r\n'
              '0,12345678,00000200,000001a4,0,0,root,root,-1,-1,dev/nflasha3,\r\n')%(zlib.crc32(payload),len(payload))
    revised,changes=firmwarelocal.rewrite_sum(manifest.encode(),{firmwarewbi.IMAGE_NAME:output})
    rows=revised.decode().splitlines()
    assert changes==[firmwarewbi.IMAGE_NAME]
    assert rows[0].split(',')[1]==report['output_crc32']==f'{zlib.crc32(actual):08x}'
    assert rows[1]==manifest.splitlines()[1]
    assert revised.endswith(b'\r\n')


@pytest.mark.parametrize('payload',[b'WBI2',b'WBI3'+bytes(508),b'BAD!'+bytes(508)])
def test_invalid_wbi_cannot_create_an_output(tmp_path,payload):
    source=tmp_path/'source';source.write_bytes(payload);output=tmp_path/'output'
    with pytest.raises(ValueError):firmwarewbi.invalidate_packaged_wbi(source,output)
    assert not output.exists() and source.read_bytes()==payload


def test_wbi_refuses_same_or_existing_output(tmp_path):
    source=tmp_path/'source';source.write_bytes(b'WBI2'+bytes(508))
    with pytest.raises(ValueError):firmwarewbi.invalidate_packaged_wbi(source,source)
    output=tmp_path/'output';output.write_bytes(b'preserve')
    with pytest.raises(FileExistsError):firmwarewbi.invalidate_packaged_wbi(source,output)
    assert output.read_bytes()==b'preserve' and source.read_bytes().startswith(b'WBI2')


@pytest.mark.parametrize('kind',['r5-copy','factory','blank','zero-payload-with-WBI3','changed-tail','stale-crc','missing'])
def test_final_package_audits_actual_wbi_and_crc(kind,tmp_path):
    before=b'WBI2'+bytes(range(256))*4
    original=tmp_path/'original.img';original.write_bytes(before)
    image=b'WBI3'+before[4:]
    if kind=='factory':image=before
    elif kind=='blank':image=bytes(len(before))
    elif kind=='zero-payload-with-WBI3':image=b'WBI3'+bytes(len(before)-4)
    elif kind=='changed-tail':image=image[:-1]+bytes([image[-1]^1])
    crc=zlib.crc32(image) if kind!='stale-crc' else 123
    manifest=f'0,{crc:08x},{len(image):08x},000001a4,0,0,root,root,-1,-1,dev/nflasha5,\n'.encode()
    raw=io.BytesIO()
    with tarfile.open(fileobj=raw,mode='w')as archive:
        for name,payload in [(firmwarewbi.IMAGE_NAME,image),(firmwarewbi.SUM_NAME,manifest)]:
            if kind=='missing' and name==firmwarewbi.IMAGE_NAME:continue
            member=tarfile.TarInfo(name);member.size=len(payload);archive.addfile(member,io.BytesIO(payload))
    raw.seek(0)
    with tarfile.open(fileobj=raw,mode='r:')as archive:
        if kind=='r5-copy':
            report=firmwarewbi.audit_packaged_wbi(archive,original)
            assert report['changed_offsets']==[3] and report['crc32']==f'{crc:08x}'
        else:
            with pytest.raises(ValueError):firmwarewbi.audit_packaged_wbi(archive,original)


def test_ssh_only_adds_async_dispatch_after_vendor_boot():
    original=b'#!/bin/busybox sh\nif true; then\n    /usr/bin/bootin.elf &\nfi\necho continue\n'
    revised=sshboot.patch_startup(original)
    addition=b'    /usr/lib/a7c2-tools/ssh/wifi-ssh </dev/null >/dev/null 2>&1 &\n'
    assert revised.replace(addition,b'')==original
    assert revised.index(b'bootin.elf &')<revised.index(b'wifi-ssh')
    assert b'sleep' not in revised and b'wait' not in revised and b'a7c2-api' not in revised
    with pytest.raises(ValueError):sshboot.patch_startup(revised)


@pytest.mark.skipif(os.name!='posix',reason='Executes the real shell background semantics on Linux')
def test_blocking_ssh_does_not_block_startup(tmp_path):
    boot=tmp_path/'bootin';boot.write_text('#!/bin/sh\nexit 0\n');boot.chmod(0o755)
    receiver=tmp_path/'receiver';receiver.write_text('#!/bin/sh\nexec sleep 30\n');receiver.chmod(0o755)
    original=b'#!/bin/sh\n    /usr/bin/bootin.elf &\necho MAIN_CONTINUED\n'
    script=sshboot.patch_startup(original).decode().replace('/usr/bin/bootin.elf',str(boot)).replace('/usr/lib/a7c2-tools/ssh/wifi-ssh',str(receiver))
    # Record the actual background PID after the generated statement.
    script=script.replace('echo MAIN_CONTINUED',f'echo $! > {tmp_path}/receiver.pid\necho MAIN_CONTINUED')
    log=tmp_path/'console';started=time.monotonic()
    with log.open('wb') as output:
        process=subprocess.Popen(['/bin/sh','-c',script],stdout=output,stderr=output,start_new_session=True)
        try:
            assert process.wait(timeout=3)==0
            assert time.monotonic()-started<3 and b'MAIN_CONTINUED' in log.read_bytes()
            os.kill(int((tmp_path/'receiver.pid').read_text()),0)
        finally:
            try:os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
