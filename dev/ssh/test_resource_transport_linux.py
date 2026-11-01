"""Exercise production SSH publication over host loopback in an E-backed lab.

Only test paths are relocated. OpenSSH, pinned host-key checking, the actual
static AArch64 Dropbear and binary transfers run normally. Not physical Wi-Fi.
"""
import base64
import json
import os
import re
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time


def run(root,artifacts,qemu):
    from desktopapp import sshupdates
    root=Path(root);root.mkdir(parents=True,exist_ok=False);os.chmod(root,0o700)
    artifacts=Path(artifacts);qemu=str(qemu)
    def command(argv):return subprocess.run(argv,capture_output=True,text=True,check=True,timeout=30)
    key=root/'client'
    command(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)])
    (root/'authorized_keys').write_bytes(key.with_suffix('.pub').read_bytes());os.chmod(root/'authorized_keys',0o600)
    command([qemu,str(artifacts/'dropbearkey'),'-t','ed25519','-f',str(root/'hostkey')])
    os.chmod(root/'hostkey',0o600)
    blob=b'\0\0\0\x0bssh-ed25519\0\0\0\x20'+(root/'hostkey').read_bytes()[-32:]
    public=root/'host-public.json';public.write_text(json.dumps(dict(algorithm='ssh-ed25519',port=2222,public_key=base64.b64encode(blob).decode())))
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    with (root/'server.log').open('w+') as log:
        server=subprocess.Popen([qemu,str(artifacts/'dropbear'),'-F','-p',f'127.0.0.1:{port}',
            '-r',str(root/'hostkey'),'-D','.', '-P',str(root/'server.pid'),'-I','60'],
            cwd=root,stdout=log,stderr=log,start_new_session=True)
        try:
            for attempt in range(100):
                if server.poll() is not None:raise RuntimeError('Test server exited')
                try:
                    with socket.create_connection(('127.0.0.1',port),timeout=.1):break
                except OSError:time.sleep(.05)
            fixture=root/'camera';fixture.mkdir()
            values={'/cp/cpapp-b.bin':b'Original CP fixture\0'+bytes(range(256))*500,
                    '/proc/sys/kernel/random/boot_id':b'00000000-0000-0000-0000-000000000001\n',
                    '/proc/self/mounts':b'rootfs / rootfs rw 0 0\n'}
            for path,raw in values.items():
                local=fixture/path.lstrip('/');local.parent.mkdir(parents=True,exist_ok=True);local.write_bytes(raw)
            (fixture/'tmp_wbshd').mkdir()
            class FixtureConnection(sshupdates.Connection):
                def execute(self,command,data=None):
                    for path in ('/proc/sys/kernel/random/boot_id','/proc/self/mounts','/tmp_wbshd','/usr','/cp'):
                        pattern=re.escape(path)+r'(?=/|[\s\x27\x22;]|$)'
                        command=re.sub(pattern,lambda match:str(fixture/path.lstrip('/')),command)
                    return super().execute(command,data)
            connection=FixtureConnection('192.0.2.1',key,public,root/'connection')
            connection.command[connection.command.index('2222')]=str(port)
            connection.command[-1]='root@127.0.0.1'
            (root/'connection/known_hosts').write_text(f'[127.0.0.1]:{port} ssh-ed25519 '+base64.b64encode(blob).decode()+'\n')
            before=values['/cp/cpapp-b.bin'];after=bytes(b^0x5a for b in before)
            baseline=root/'baseline';baseline.mkdir();(baseline/'cpapp-b.bin').write_bytes(before)
            (baseline/'baseline.private.json').write_text('{}')
            update=root/'update'
            sshupdates.save_package({'/cp/cpapp-b.bin':(before,after)},update,'looks',source_baseline=baseline)
            result=sshupdates.apply(update,connection)
            assert result['phase']=='AWAITING_RELOAD'
            assert (fixture/'cp/cpapp-b.bin').read_bytes()==after
            (fixture/'proc/sys/kernel/random/boot_id').write_text('00000000-0000-0000-0000-000000000002\n')
            result=sshupdates.verify_reload(update,connection)
            assert result['phase']=='LOADED'
            assert Path(result['next_baseline'],'cpapp-b.bin').read_bytes()==after
            report=dict(camera_io=False,actual_openssh=True,actual_aarch64_dropbear=True,host_loopback_only=True,
                        file_fixtures=True,physical_wifi_verified=False,binary_bytes=len(after),
                        staged_and_committed_readback=True,next_baseline_verified=True)
            (root/'result.private.json').write_text(json.dumps(report,indent=2))
            print(json.dumps(report,indent=2),flush=True)
        finally:
            os.killpg(server.pid,signal.SIGTERM)
            try:server.wait(timeout=10)
            except subprocess.TimeoutExpired:os.killpg(server.pid,signal.SIGKILL);server.wait(timeout=5)


if __name__=='__main__':run(*sys.argv[1:])
