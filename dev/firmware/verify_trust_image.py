"""Run the original RSA functions from the actual prepared updater image."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from desktopapp.updaterimage import partition_files,squash_files


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('image','identity','updater-root','harness','qemu','workspace'):
        parser.add_argument('--'+name,required=True,type=Path)
    args=parser.parse_args();args.workspace.mkdir(parents=True,exist_ok=False)
    from Cryptodome.PublicKey import RSA
    from Cryptodome.Signature import pkcs1_15
    from Cryptodome.Hash import SHA256
    files=squash_files(partition_files(args.image.read_bytes())['/boot/initrd.img'])
    public=files['/etc/VerificationKey.pem'][-1]
    private=RSA.import_key((args.identity/'firmware.private.pem').read_bytes())
    assert RSA.import_key(public).n==private.n
    payload=b'C2-INSTALLED-TRUST-IMAGE\0'+bytes(range(256))*17
    signature=pkcs1_15.new(private).sign(SHA256.new(payload))
    fixture={'payload.bin':payload,'tampered.bin':payload[:-1]+bytes([payload[-1]^1]),
        'payload.sig':signature,'wrong.sig':signature[:-1]+bytes([signature[-1]^1]),
        'public.pem':public,'encoding.pem':public+b'\n',
        'factory.pem':(args.updater_root/'etc/VerificationKey.pem').read_bytes()}
    for name,value in fixture.items():(args.workspace/name).write_bytes(value)
    cases=[('valid','payload.bin','payload.sig','public.pem',True,True),
        ('tampered_payload','tampered.bin','payload.sig','public.pem',False,True),
        ('wrong_signature','payload.bin','wrong.sig','public.pem',False,True),
        ('factory_key','payload.bin','payload.sig','factory.pem',False,False),
        ('changed_encoding','payload.bin','payload.sig','encoding.pem',False,False),
        ('missing_key','payload.bin','payload.sig','missing.pem',False,False)]
    environment=dict(os.environ,LD_LIBRARY_PATH=str(args.updater_root/'usr/lib')+':/usr/aarch64-linux-gnu/lib')
    rows=[]
    for path,value in files.items():
        if not path.startswith('/usr/lib/lib') or 'inputupdaterapi.so' not in path and path!='/usr/lib/libupdaterapi.so':continue
        library=args.workspace/Path(path).name;library.write_bytes(value[-1])
        for name,data,sig,key,accepted,rsa in cases:
            process=subprocess.run([str(args.qemu),'-L','/usr/aarch64-linux-gnu',str(args.harness),str(library),
                str(args.workspace/data),str(args.workspace/sig),str(args.workspace/key),'00'*20],
                env=environment,capture_output=True,text=True,timeout=45)
            passed=((process.returncode==0)==accepted and ('TRACE rsa_enter' in process.stderr)==rsa
                and 'TRACE trust_' not in process.stderr and 'UNEXPECTED_FACTORY' not in process.stderr)
            rows.append(dict(library=library.name,case=name,passed=passed,returncode=process.returncode,
                stdout=process.stdout,stderr=process.stderr))
            print(library.name,name,'PASS' if passed else 'FAIL',flush=True)
    report=dict(camera_io=False,actual_installer_image=True,private_key_in_image=False,
        original_rsa_executed=True,cases=rows,passed=len(rows)==24 and all(row['passed'] for row in rows))
    (args.workspace/'result.private.json').write_text(json.dumps(report,indent=2)+'\n')
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
