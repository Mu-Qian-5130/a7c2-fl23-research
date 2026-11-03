"""Validate a signed C2 candidate through original updater code in user-mode QEMU.

Uses the original SD BufferManager, RingBuffer, execWriteFirm, RSA and block
checks. AES slot 8 is an explicit software service fixture; the downstream
writer is replaced by a SHA-256 sink. No physical card or device is opened.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]


def digest(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while data:=stream.read(4<<20):result.update(data)
    return result.hexdigest()


def parse_result(log):
    rows=re.findall(r'^C2_PIPELINE_RESULT (.+)$',log,re.M)
    if len(rows)!=1:raise ValueError('Native decoder did not produce exactly one completion result')
    result={k:(v if k=='sha256' else int(v)) for k,v in re.findall(r'(\w+)=([0-9a-f]+)',rows[0])}
    required={'exception','input_bytes','consumed','output_bytes','blocks','ends','fs_writes',
              'rsa_calls','key_redirects','crypto_inits','crypto_updates','crypto_finals','unexpected','sha256'}
    if result.keys()!=required or not re.fullmatch(r'[0-9a-f]{64}',result['sha256']):
        raise ValueError('Native decoder returned an incomplete result')
    capacities=re.findall(r'^C2_NATIVE_BUFFER_CAPACITY bytes=(\d+) ',log,re.M)
    remainders=re.findall(r'^C2_NATIVE_RING_REMAINDER bytes=(\d+)',log,re.M)
    if len(capacities)!=1 or len(remainders)!=1:raise ValueError('Missing native ring-buffer evidence')
    result['native_buffer_capacity']=int(capacities[0])
    result['native_ring_remainder']=int(remainders[0])
    return result


def assess(result, *, returncode, plaintext_bytes, plaintext_sha256, expected_rejection=False):
    if result['fs_writes'] or result['unexpected']:
        return False
    if expected_rejection:
        return (returncode==1 and result['exception']==1 and result['output_bytes']==0
                and result['blocks']==0 and result['ends']==0)
    return (returncode==0 and result['exception']==0 and result['rsa_calls']==1
            and result['output_bytes']==plaintext_bytes and result['sha256']==plaintext_sha256
            and result['ends']==1 and result['key_redirects']==2
            and result['crypto_inits']==result['crypto_finals']==1
            and result['crypto_updates']==result['blocks'] and result['blocks']>0
            and result['consumed']==result['input_bytes']-272
            and result['native_ring_remainder']==272
            and result['native_buffer_capacity']>=result['input_bytes'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--updater-root',type=Path,required=True,help='Original extracted C2 updater initrd')
    parser.add_argument('--policy-library',type=Path,required=True,help='C2 owner-policy SD updater library')
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--public-key',type=Path,required=True)
    parser.add_argument('--plaintext',type=Path,required=True,help='Exact expected FDAT before encryption')
    parser.add_argument('--workspace',type=Path,required=True,help='New directory for build and evidence')
    parser.add_argument('--qemu',required=True,help='qemu-aarch64 or full path; Windows uses WSL')
    parser.add_argument('--wsl-distro',default='Ubuntu-22.04')
    parser.add_argument('--mode',choices=['valid','tamper_cipher'],default='valid')
    parser.add_argument('--expect-rejection',action='store_true')
    args=parser.parse_args()
    if args.mode!='valid' and not args.expect_rejection:
        parser.error('A mutation run requires --expect-rejection')
    paths=[args.updater_root,args.policy_library,args.candidate,args.public_key,args.plaintext]
    if not all(p.exists() for p in paths):parser.error('One or more selected inputs do not exist')
    work=args.workspace.resolve();work.mkdir(parents=True,exist_ok=False)
    windows=os.name=='nt'
    def native(path):
        path=Path(path).resolve()
        if windows:return '/mnt/'+path.drive[0].lower()+'/'+path.as_posix().split(':/',1)[1]
        return str(path)
    def command(argv,*,timeout=120,output=None):
        if windows:argv=['wsl','-d',args.wsl_distro,'--',*argv]
        if output is not None:
            with output.open('w',encoding='utf-8') as log:
                p=subprocess.run(argv,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
            return subprocess.CompletedProcess(argv,p.returncode,output.read_text(encoding='utf-8',errors='replace'))
        return subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                              encoding='utf-8',errors='replace',timeout=timeout)
    build_log=work/'build.log'
    def build(argv):
        p=command(argv)
        with build_log.open('a',encoding='utf-8') as log:log.write(p.stdout)
        if p.returncode:raise RuntimeError('Native validator compilation failed; see build.log')
    sources=Path(__file__).resolve().parent/'native'
    c_obj=work/'verify_pipeline.o';bridge_obj=work/'verify_bridge.o';binary=work/'verify_pipeline'
    build(['aarch64-linux-gnu-gcc','-O2','-fno-stack-protector','-fexceptions','-c',native(sources/'verify_pipeline.c'),'-o',native(c_obj)])
    build(['clang','--target=aarch64-linux-gnu','-x','c++','-nostdinc++','-O2','-fno-stack-protector','-fPIC','-fno-rtti',
           '-c',native(sources/'verify_bridge.cc'),'-o',native(bridge_obj)])
    build(['aarch64-linux-gnu-gcc','-rdynamic','-o',native(binary),native(c_obj),native(bridge_obj),
           '-ldl','/usr/aarch64-linux-gnu/lib/libstdc++.so.6','-lgcc_s'])
    sys.path.insert(0,str(ROOT/'src/desktopapp/vendor'))
    from fwtool.sony import constants
    slot=work/'aes-slot8.fixture.bin';slot.write_bytes(constants.key_cxd90057_k8)
    qemu=args.qemu
    if windows and re.match(r'^[A-Za-z]:[\\/]',qemu):qemu=native(qemu)
    original_libs=native(args.updater_root/'usr/lib')
    argv=['env','LD_LIBRARY_PATH='+original_libs+':/usr/aarch64-linux-gnu/lib',
          'TMPDIR='+native(work),'timeout','--signal=TERM','--kill-after=5s','600s',
          qemu,'-L','/usr/aarch64-linux-gnu',native(binary),
          native(args.policy_library),native(args.candidate),native(args.public_key),native(slot),args.mode,original_libs]
    report=dict(schema='a7c2-native-decoder-validation/1',camera_io=False,device_ready=False,
                native_source_buffer=True,native_decoder_control=True,software_slot8_service=True,
                destination='hash-only sink',physical_ram_verified=False,sd_driver_verified=False,
                full_updater_manager_executed=False,mode=args.mode,expected_rejection=args.expect_rejection)
    status=work/'result.private.json'
    try:
        p=command(argv,timeout=660,output=work/'native.log')
        report.update(returncode=p.returncode,result=parse_result(p.stdout),
                      expected_plaintext_bytes=args.plaintext.stat().st_size,
                      expected_plaintext_sha256=digest(args.plaintext))
        report['passed']=assess(report['result'],returncode=p.returncode,
            plaintext_bytes=report['expected_plaintext_bytes'],plaintext_sha256=report['expected_plaintext_sha256'],
            expected_rejection=args.expect_rejection)
    except subprocess.TimeoutExpired as exc:
        output=exc.stdout or b''
        if isinstance(output,bytes):output=output.decode('utf-8',errors='replace')
        if output:(work/'native.log').write_text(output,encoding='utf-8')
        report.update(passed=False,error='Native validator exceeded its observation window')
    except Exception as exc:
        report.update(passed=False,error=type(exc).__name__+': '+str(exc))
    status.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
