"""Real SSH calls to the AArch64 fixed command in a private network namespace."""
import base64
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import time


def run(folder,qemu,artifacts,binary,ap_source):
    folder=Path(folder);folder.mkdir(exist_ok=False);qemu=str(qemu);artifacts=Path(artifacts);binary=str(binary)
    camera=folder/'camera';shutil.copytree(Path(binary).parent/'info',camera)
    (camera/'usr/lib').mkdir(parents=True,exist_ok=True)
    shutil.copyfile(ap_source,camera/'usr/lib/appFw.so')
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
            # Exercise the actual public CLI with every shipped .a7look, not a dummy wire payload.
            from desktopapp import sshupdates
            from looktool import device_layout,lookfile,nameworker,photoio,resources
            spec=importlib.util.spec_from_file_location('camera_cli',root/'dev/ssh/camera.py')
            cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
            baseline=Path(binary).parent/'info'
            cp=(baseline/'cp/cpapp-b.bin').read_bytes()
            ap=Path(ap_source).read_bytes()
            ids=device_layout.structural_ap(ap)['label_ids'];bank=photoio.neutral_bank(cp)
            originals={name:(baseline/'usr/share/app'/name).read_bytes() for name in nameworker.filenames()}
            assets=sorted((root/'desktop-assets/presets').rglob('*.a7look'))
            assets+=sorted((root/'desktop-assets/profile-library-v1').rglob('*.a7look'))
            assert assets,'No real .a7look assets found'
            previous_connection=sshupdates.Connection;previous_argv=sys.argv
            try:
                sshupdates.Connection=FixtureConnection
                for index,source in enumerate(assets):
                    slot=index%6+1;document=lookfile.read(source);title=document['name']
                    (camera/'cp/cpapp-b.bin').write_bytes(cp)
                    for filename,data in originals.items():(camera/'usr/share/app'/filename).write_bytes(data)
                    (camera/'setting/a7c2-api.task').unlink(missing_ok=True)
                    workspace=folder/('a7look-cli-'+str(index))
                    sys.argv=[str(root/'dev/ssh/camera.py'),'--ip',address,'--client-private',str(client),
                        '--host-public',str(public),'--workspace',str(workspace),'look',str(slot),str(source)]
                    with contextlib.redirect_stdout(io.StringIO()) as output:status=cli.main()
                    assert status==0 and json.loads(output.getvalue())['state']=='pending_reload'
                    expected=device_layout.replace(ap,cp,{slot:lookfile.writer_document(document)},hash_checks=False,
                        native_photo={slot:document.get('native_photo')},native_bank=bank,transitions=False)[2]
                    assert (camera/'cp/cpapp-b.bin').read_bytes()==expected['cpapp-b.bin'],str(source)
                    for filename,data in originals.items():
                        assert (camera/'usr/share/app'/filename).read_bytes()==resources.rename(data,{slot:title},ids)[0],filename
                    assert not list(workspace.rglob('*.bin')),'Unexpected intermediate binary file'
                    record('ssh-cli-a7look-'+source.relative_to(root/'desktop-assets').as_posix())
            finally:
                sshupdates.Connection=previous_connection;sys.argv=previous_argv
            report['a7look_files']=len(assets)
            report['name_resources_per_file']=len(originals)
            report['full_cp_compared']=True
            report['intermediate_look_files']=False
            # Layout changes must be refused before changing CP, titles or audio.
            from looktool import photobuild
            def reset(raw):
                (camera/'cp/cpapp-b.bin').write_bytes(raw)
                (camera/'setting/a7c2-api.task').unlink(missing_ok=True)
            def inventory():
                return {p.relative_to(camera).as_posix():p.read_bytes() for area in ('cp','usr/share','setting')
                        for p in (camera/area).rglob('*') if p.is_file()}
            for label,offset,replacement,args,data in (
                ('photo-header',photobuild.DATA_FILE,b'BAD!',('look',6,'Test'),bytes(1324)),
                ('sound-front',0x39358e,b'\xab\xcd',('sound','both','off'),None),
                ('custom-sound-gate',0x393570,b'\xff',('sound','electronic','custom'),bytes(1024)),
                ('segment-mapping',0x2012c,bytes(4),('look',6,'Test'),bytes(1324))):
                raw=bytearray(cp);raw[offset:offset+len(replacement)]=replacement;reset(raw);before=inventory()
                assert call(connection,*args,payload=data)['state']=='failed'
                assert inventory()==before,label;record('reject-before-write-'+label)
            reset(cp[:-1]);before=inventory()
            assert call(connection,'look',6,'Test',payload=bytes(1324))['error']=='layout-size'
            assert inventory()==before;record('reject-before-write-truncated-cp')
            reset(cp);shared=camera/'tmp_wbshd/a7c2-resource-update.lock';shared.mkdir();before=inventory()
            try:assert call(connection,'look',6,'Test',payload=bytes(1324))['error']=='busy'
            finally:shared.rmdir()
            assert inventory()==before;record('legacy-and-api-share-update-lock')
            reset(cp);before=inventory();filler=folder/'space-fixture'
            try:
                space=os.statvfs(camera/'usr');amount=max(0,(space.f_bavail-4)*space.f_frsize)
                with filler.open('wb') as f:os.posix_fallocate(f.fileno(),0,amount)
                assert call(connection,'look',6,'Test',payload=bytes(1324))['error']=='no-space'
                assert inventory()==before;record('low-space-refused-before-resource-write')
            finally:filler.unlink(missing_ok=True)
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
