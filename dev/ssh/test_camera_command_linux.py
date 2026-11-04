"""Real SSH calls to the AArch64 fixed command in a private network namespace."""
import base64
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import time


def run(folder,qemu,artifacts,binary):
    folder=Path(folder);folder.mkdir(exist_ok=False);qemu=str(qemu);artifacts=Path(artifacts);binary=str(binary)
    camera=folder/'camera';shutil.copytree(Path(binary).parent/'info',camera)
    os.chmod(folder,0o700)
    root=Path(__file__).resolve().parents[2];sys.path[:0]=[str(root/'src'),str(root/'src/looks')]
    from desktopapp.cameraapi import call,COMMAND
    from desktopapp.sshupdates import Connection
    def command(argv):return subprocess.run(argv,check=True,capture_output=True,text=True,timeout=20)
    command(['ip','link','set','lo','up'])
    address='10.84.0.1';command(['ip','addr','add',address+'/32','dev','lo'])
    client=folder/'client';command(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(client)])
    (folder/'authorized_keys').write_bytes(client.with_suffix('.pub').read_bytes());os.chmod(folder/'authorized_keys',0o600)
    command([qemu,str(artifacts/'dropbearkey'),'-t','ed25519','-f',str(folder/'hostkey')])
    os.chmod(folder/'hostkey',0o600)
    blob=b'\0\0\0\x0bssh-ed25519\0\0\0\x20'+(folder/'hostkey').read_bytes()[-32:]
    public=folder/'host-public.json';public.write_text(json.dumps(dict(algorithm='ssh-ed25519',public_key=base64.b64encode(blob).decode(),port=2222)))
    class FixtureConnection(Connection):
        def execute_api(self,command,data=None):
            fixed=COMMAND
            assert command.startswith(fixed+' ')
            prefix='env A7C2_TEST_ROOT='+shlex.quote(str(camera))+' '+shlex.quote(qemu)+' '+shlex.quote(binary)
            return super().execute_api(prefix+command[len(fixed):],data)
    rows=[];report=dict(camera_io=False,real_ssh=True,aarch64_command=True,complete=False,passed=False,cases=rows)
    def record(name):rows.append(name);print(name,flush=True)
    with (folder/'ssh.log').open('w') as log:
        server=subprocess.Popen([qemu,str(artifacts/'dropbear'),'-F','-p',address+':2222','-r',str(folder/'hostkey'),'-D','.',
                                 '-P',str(folder/'server.pid'),'-K','0','-I','0'],cwd=folder,stdout=log,stderr=log)
        try:
            for _ in range(80):
                if server.poll() is not None:raise RuntimeError('SSH server stopped')
                try:
                    with socket.create_connection((address,2222),timeout=.1):break
                except OSError:time.sleep(.05)
            connection=FixtureConnection(address,client,public,folder/'connection')
            info=call(connection,'info');assert info['slots']==[1,2,3,4,5,6] and 'version' not in info;record('ssh-info')
            assert call(connection,'task')['state']=='idle';record('ssh-task-idle')
            title="SSH Test ' $(printf BAD)"
            assert call(connection,'look',2,title,payload=bytes(1324))['state']=='pending_reload';record('ssh-look-small-payload')
            from looktool.resources import decode
            title_id=0x0200ab2d
            names=decode((camera/'usr/share/app/string_english_horizontal.uxc').read_bytes())
            assert names['entries'][title_id]['text']==title;record('ssh-name-shell-characters-preserved')
            assert call(connection,'task')['state']=='pending_reload';record('ssh-task-pending')
            rejected=call(connection,'sound','electronic','off');assert rejected=={'state':'failed','error':'pending-reload'};record('ssh-structured-failure')
            (camera/'proc/sys/kernel/random/boot_id').write_text('00000000-0000-0000-0000-000000000002\n')
            assert call(connection,'task')['state']=='active';record('ssh-task-new-boot-observed')
            assert call(connection,'sound','electronic','custom',payload=bytes(1024))['state']=='pending_reload';record('ssh-custom-audio')
            report.update(passed=True,complete=True)
        except BaseException as exc:
            report['error']=type(exc).__name__+': '+str(exc);raise
        finally:
            server.terminate()
            try:server.wait(timeout=5)
            except subprocess.TimeoutExpired:server.kill();server.wait()
            (folder/'result.private.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':print(json.dumps(run(*sys.argv[1:]),indent=2))
