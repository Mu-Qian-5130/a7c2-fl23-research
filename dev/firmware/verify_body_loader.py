"""Check original C2 body-loader header callbacks in an offline AArch64 VM.

Uses a native work buffer and ring, original header checks and RVchk4PI, an
explicit 2.01 metadata fixture, and absent marker-file fixtures. Mounts fail;
the callback cancels before body execution. This is not a complete updater.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


def body_layout(header, size):
    count=int.from_bytes(header[0x38:0x3c],'little')
    prefix=int.from_bytes(header[0x30:0x34],'little')
    if not 0<count<=28 or not 512<=prefix<=size:raise ValueError('Invalid FDAT filesystem layout')
    for i in range(count):
        at=0x40+16*i
        if header[at]==0x55:
            offset=int.from_bytes(header[at+4:at+8],'little')
            length=int.from_bytes(header[at+8:at+12],'little')
            if offset<512 or not length or offset+length>prefix:raise ValueError('Invalid user body extent')
            return prefix,offset,length
    raise ValueError('No user body filesystem in FDAT')


def slice_digest(path,offset,length):
    result=hashlib.sha256()
    with path.open('rb') as stream:
        stream.seek(offset)
        while length:
            data=stream.read(min(length,1<<20))
            if not data:raise ValueError('Truncated body-image input')
            result.update(data);length-=len(data)
    return result.hexdigest()


def assess_image(log, *, returncode, prefix, image_bytes, actual_bytes, expected_sha256, actual_sha256):
    rows=re.findall(r'^C2_BODY_IMAGE_RESULT exception=(\d+) prefix=(\d+) fed=(\d+) written=(\d+) remaining=(\d+) opens=(\d+) closes=(\d+) unknown=(\d+) unexpected_writes=(\d+)$',log,re.M)
    return (returncode==0 and len(rows)==1
            and tuple(map(int,rows[0]))==(0,prefix,prefix,image_bytes,0,1,1,0,0)
            and image_bytes==actual_bytes and expected_sha256==actual_sha256)


def assess(log, *, mode, returncode, expected_info):
    rows=re.findall(r'^C2_BODY_LOADER_RESULT mode=(\w+) exception=(\d+) callbacks=(\d+) body_calls=(\d+) mounts_blocked=(\d+) version_reads=(\d+) writes=(\d+) unknown_io=(\d+) remaining=(\d+)$',log,re.M)
    callbacks=re.findall(r'^C2_BODY_HEADER_CALLBACK phase=(\d+) major=(\d+) minor=(\d+) model=([0-9a-f]{8}) region=([0-9a-f]{8}) cancel=(\d+)$',log,re.M)
    if returncode or len(rows)!=1 or rows[0][0]!=mode:return False
    exception,count,body,mounts,versions,writes,unknown,remaining=map(int,rows[0][1:])
    valid=mode=='valid'
    if mode not in ('valid','bad_crc','truncated'):return False
    if (exception,count,body,mounts,versions,writes,unknown,remaining)!=(int(not valid),int(valid),0,int(valid),int(valid),0,0,511 if mode=='truncated' else 0):return False
    if not valid:return not callbacks
    if len(callbacks)!=1:return False
    phase,major,minor,model,region,cancel=callbacks[0]
    return (int(phase),int(major),int(minor),int(model,16),int(region,16),int(cancel))==(2,*expected_info,1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--updater-root',type=Path,required=True)
    parser.add_argument('--plaintext',type=Path,required=True)
    parser.add_argument('--workspace',type=Path,required=True,help='New directory for build and evidence')
    parser.add_argument('--qemu',required=True)
    parser.add_argument('--wsl-distro',default='Ubuntu-22.04')
    args=parser.parse_args()
    if not args.updater_root.is_dir() or not args.plaintext.is_file():parser.error('Selected inputs do not exist')
    with args.plaintext.open('rb') as stream:header=stream.read(512)
    if len(header)!=512:parser.error('Plaintext does not contain a complete header')
    expected_info=(header[0x21],header[0x20],int.from_bytes(header[0x24:0x28],'little'),int.from_bytes(header[0x28:0x2c],'little'))
    work=args.workspace.resolve();work.mkdir(parents=True,exist_ok=False)
    windows=os.name=='nt'
    def native(path):
        path=Path(path).resolve()
        return '/mnt/'+path.drive[0].lower()+'/'+path.as_posix().split(':/',1)[1] if windows else str(path)
    def command(argv,output,timeout=120):
        if windows:argv=['wsl','-d',args.wsl_distro,'--',*argv]
        with output.open('w',encoding='utf-8') as log:
            result=subprocess.run(argv,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
        return result.returncode,output.read_text(encoding='utf-8',errors='replace')
    sources=Path(__file__).resolve().parent/'native'
    c_object=work/'body.o';bridge=work/'bridge.o';binary=work/'body_loader'
    image_object=work/'image.o';image_binary=work/'body_image'
    builds=[['aarch64-linux-gnu-gcc','-O2','-fexceptions','-c',native(sources/'verify_body_loader.c'),'-o',native(c_object)],
            ['clang','--target=aarch64-linux-gnu','-x','c++','-nostdinc++','-O2','-fno-stack-protector','-fPIC','-fno-rtti','-c',native(sources/'verify_bridge.cc'),'-o',native(bridge)],
            ['aarch64-linux-gnu-gcc','-rdynamic','-o',native(binary),native(c_object),native(bridge),'-ldl','/usr/aarch64-linux-gnu/lib/libstdc++.so.6','-lgcc_s'],
            ['aarch64-linux-gnu-gcc','-O2','-fexceptions','-c',native(sources/'verify_body_image.c'),'-o',native(image_object)],
            ['aarch64-linux-gnu-gcc','-rdynamic','-o',native(image_binary),native(image_object),native(bridge),'-pthread','-ldl','/usr/aarch64-linux-gnu/lib/libstdc++.so.6','-lgcc_s']]
    report=dict(schema='a7c2-body-loader-validation/1',camera_io=False,device_ready=False,
                native_header_callback=True,current_version_fixture='2.01',mounts_blocked=True,
                marker_files_fixture='absent',body_execution=False,full_updater_manager_executed=False,cases=[])
    try:
        for i,argv in enumerate(builds):
            code,_=command(argv,work/f'build-{i}.log')
            if code:raise RuntimeError('Diagnostic compilation failed; see build logs')
        fixture=work/'current-version.fixture.bin';fixture.write_bytes(bytes((1,2)))
        qemu=args.qemu
        if windows and re.match(r'^[A-Za-z]:[\\/]',qemu):qemu=native(qemu)
        libs=native(args.updater_root/'usr/lib')
        for mode in ('valid','bad_crc','truncated'):
            code,log=command(['env','LD_LIBRARY_PATH='+libs+':/usr/aarch64-linux-gnu/lib',
                'TMPDIR='+native(work),'timeout','--signal=TERM','--kill-after=5s','20s',qemu,
                '-L','/usr/aarch64-linux-gnu',native(binary),libs+'/libupdatertalk.so',
                libs+'/libsdfileinputupdaterapi.so',native(args.plaintext),native(fixture),mode],work/f'{mode}.log',timeout=35)
            report['cases'].append(dict(mode=mode,returncode=code,
                passed=assess(log,mode=mode,returncode=code,expected_info=expected_info)))
        prefix,offset,length=body_layout(header,args.plaintext.stat().st_size)
        image=work/'bodyimg.private.img'
        code,log=command(['env','LD_LIBRARY_PATH='+libs+':/usr/aarch64-linux-gnu/lib',
            'TMPDIR='+native(work),'timeout','--signal=TERM','--kill-after=5s','20s',qemu,
            '-L','/usr/aarch64-linux-gnu',native(image_binary),libs+'/libupdatertalk.so',
            libs+'/libsdfileinputupdaterapi.so',native(args.plaintext),native(image)],work/'body-image.log',timeout=35)
        expected_digest=slice_digest(args.plaintext,offset,length)
        actual_bytes=image.stat().st_size if image.exists() else 0
        actual_digest=slice_digest(image,0,actual_bytes) if image.exists() else ''
        report['body_image']=dict(returncode=code,prefix=prefix,offset=offset,expected_bytes=length,
            actual_bytes=actual_bytes,expected_sha256=expected_digest,actual_sha256=actual_digest,
            passed=assess_image(log,returncode=code,prefix=prefix,image_bytes=length,actual_bytes=actual_bytes,
                                expected_sha256=expected_digest,actual_sha256=actual_digest))
        report['passed']=len(report['cases'])==3 and all(row['passed'] for row in report['cases']) and report['body_image']['passed']
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc:
        report.update(passed=False,error=type(exc).__name__+': '+str(exc))
    (work/'result.private.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
