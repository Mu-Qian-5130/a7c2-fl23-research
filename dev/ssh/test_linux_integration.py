"""Real static AArch64 Dropbear under QEMU, with host loopback only.

Run on Linux: python3 test_linux_integration.py ARTIFACTS QEMU_AARCH64
No camera or local network discovery. A temporary client/host key is deleted
with the test directory; SSH command and PTY tests reach the host test shell.
"""
import json
import base64
import os
import pty
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time


def run(artifacts,qemu,hostkey=None):
    if os.geteuid()!=0:raise RuntimeError('Run this root-bound debug-server test as root in the Linux test VM')
    artifacts=Path(artifacts).resolve();qemu=str(Path(qemu).resolve())
    with tempfile.TemporaryDirectory(prefix='a7c2-ssh-integration-') as temporary:
        root=Path(temporary);os.chmod(root,0o700)
        def command(args,**kwargs):return subprocess.run(args,capture_output=True,text=True,timeout=20,**kwargs)
        key=root/'client'
        done=command(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)])
        assert done.returncode==0,done.stderr
        (root/'authorized_keys').write_bytes(key.with_suffix('.pub').read_bytes());os.chmod(root/'authorized_keys',0o600)
        if hostkey:(root/'hostkey').write_bytes(Path(hostkey).read_bytes())
        else:
            done=command([qemu,str(artifacts/'dropbearkey'),'-t','ed25519','-f',str(root/'hostkey')])
            assert done.returncode==0,done.stderr
        os.chmod(root/'hostkey',0o600)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        host_blob=b'\0\0\0\x0bssh-ed25519\0\0\0\x20'+(root/'hostkey').read_bytes()[-32:]
        (root/'known_hosts').write_text('[127.0.0.1]:%d ssh-ed25519 %s\n'%(port,base64.b64encode(host_blob).decode()))
        with (root/'server.log').open('w+') as log:
            server=subprocess.Popen([qemu,str(artifacts/'dropbear'),'-F','-p',f'127.0.0.1:{port}',
                '-r',str(root/'hostkey'),'-D','.', '-P',str(root/'server.pid'),'-I','30'],
                stdout=log,stderr=log,start_new_session=True,cwd=root)
            try:
                for attempt in range(100):
                    if server.poll() is not None:break
                    try:
                        with socket.create_connection(('127.0.0.1',port),timeout=.1):break
                    except OSError:time.sleep(.05)
                base=['ssh','-F','/dev/null','-o','BatchMode=yes','-o','IdentitiesOnly=yes',
                    '-o','StrictHostKeyChecking=yes','-o',f'UserKnownHostsFile={root}/known_hosts',
                    '-o','ConnectTimeout=5','-p',str(port),'-i',str(key),'root@127.0.0.1']
                done=command(base+['printf A7C2_SSH_COMMAND_OK'])
                if done.returncode:log.flush();raise AssertionError((done.stderr,(root/'server.log').read_text()))
                assert done.stdout=='A7C2_SSH_COMMAND_OK',done.stdout
                master,slave=pty.openpty()
                try:
                    done=command(base[:-1]+['-tt',base[-1],'test -t 0 && printf A7C2_SSH_PTY_OK'],stdin=slave)
                finally:os.close(slave);os.close(master)
                if not (done.returncode==0 and 'A7C2_SSH_PTY_OK' in done.stdout):
                    log.flush();raise AssertionError((done.returncode,done.stdout,done.stderr,(root/'server.log').read_text()))
                wrong=root/'wrong'
                assert command(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(wrong)]).returncode==0
                rejected=list(base);rejected[rejected.index(str(key))]=str(wrong)
                done=command(rejected+['printf MUST_NOT_EXECUTE'])
                assert done.returncode!=0 and 'MUST_NOT_EXECUTE' not in done.stdout
                assert 'publickey' in done.stderr,done.stderr
                wrong_user=[arg.replace('root@127.0.0.1','nobody@127.0.0.1') for arg in base]
                done=command(wrong_user+['printf MUST_NOT_EXECUTE'])
                assert done.returncode!=0 and 'MUST_NOT_EXECUTE' not in done.stdout
                return dict(camera_io=False,aarch64_emulated=True,ssh_command='passed',pty='passed',
                    unlisted_key_rejected=True,other_username_rejected=True,physical_camera_login_verified=False)
            finally:
                if server.poll() is None:os.killpg(server.pid,signal.SIGTERM)
                server.wait(timeout=5)


if __name__=='__main__':print(json.dumps(run(*sys.argv[1:]),indent=2))
