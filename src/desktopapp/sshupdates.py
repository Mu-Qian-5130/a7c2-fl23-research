"""Compile look/audio changes locally and publish them through pinned SSH.

Initial feature installation belongs to the local firmware builder. Updates
require that exact local baseline and change only CP tables/switches, look-title
resources and the installed native sound loader's private data files. No USB,
system account change, shell startup edit or automatic restart is performed.
"""
import base64
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import uuid

from .paths import ROOT,write_json


def allowed(path):
    if path in ('/cp/cpapp-b.bin','/setting/updater/dat4'):return True
    if path.startswith('/usr/share/app/'):
        from looktool.nameworker import filenames
        return path in {'/usr/share/app/'+name for name in filenames()}
    return path in {'/usr/share/avsystemsound/'+name for name in
                    ('custom.txt','custom-shutter.bin','custom-shutter-a.bin','custom-shutter-b.bin')}


class Connection:
    def __init__(self,ip,client_private,host_public,workspace):
        from .actions.ssh import engine
        self.ip=engine().ipv4(ip)
        self.workspace=Path(workspace);self.workspace.mkdir(parents=True,exist_ok=True)
        public=json.loads(Path(host_public).read_text(encoding='utf-8'))
        if public.get('algorithm')!='ssh-ed25519' or public.get('port')!=2222:
            raise ValueError('Select the host-public.json from this local firmware build')
        blob=base64.b64decode(public['public_key'],validate=True)
        if len(blob)!=51 or blob[:19]!=b'\0\0\0\x0bssh-ed25519\0\0\0\x20':raise ValueError('Invalid pinned SSH host key')
        known=self.workspace/'known_hosts'
        known.write_text('[%s]:2222 ssh-ed25519 %s\n'%(self.ip,base64.b64encode(blob).decode()),encoding='ascii')
        executable=shutil.which('ssh')
        if not executable:raise ValueError('电脑需要 OpenSSH 客户端')
        self.command=[executable,'-F','NUL' if sys.platform=='win32' else '/dev/null',
                      '-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes',
                      '-o','ConnectTimeout=10','-o','UserKnownHostsFile='+str(known),
                      '-p','2222','-i',str(Path(client_private).resolve()),'root@'+self.ip]

    def execute(self,command,data=None):
        done=subprocess.run([*self.command,command],input=data,capture_output=True,timeout=120)
        if done.returncode:raise RuntimeError('SSH command failed: '+done.stderr.decode(errors='replace')[-1800:])
        return done.stdout

    def read(self,path,missing=False):
        if path not in ('/proc/self/mounts','/proc/sys/kernel/random/boot_id') and not allowed(path):
            raise ValueError('File outside the SSH update scope')
        command='cat '+shlex.quote(path)
        if missing:command='if test -f '+shlex.quote(path)+'; then '+command+'; fi'
        return self.execute(command)


def baseline(folder):
    from looktool.devicesession import modules
    folder=Path(folder).resolve()
    manifest=json.loads((folder/'baseline.private.json').read_text(encoding='utf-8'))
    if (manifest.get('schema'),manifest.get('model'),manifest.get('version'))!=(
            'a7c2-ssh-update-baseline/1','ILCE-7CM2','2.01'):raise ValueError('请选择本地构建生成的 baseline 目录')
    current={name:(folder/name).read_bytes() for name in manifest['files']}
    records=modules()[1].backup_records(current['settings-ram.bin'])
    for chip,fields in enumerate(manifest['wanted']):
        for key,value in fields.items():records[chip][int(key)]=records[chip][int(key)]._replace(data=bytes.fromhex(value))
    return folder,current,records,manifest


def compile_look(folder,operations,output):
    from looktool import bundle
    folder,current,records,manifest=baseline(folder)
    options=dict(fl23=False,sound=False,looks=operations)
    options,selected=bundle.documents(options)
    target,wanted,rename=bundle.plan(current,records,options,selected)
    if target['appFw.so']!=current['appFw.so']:
        raise ValueError('所选外观需要更新基础固件；请先在电脑重新生成固件候选')
    result={}
    for name,raw in target.items():
        if raw==current[name]:continue
        path='/cp/cpapp-b.bin' if name=='cpapp-b.bin' else '/usr/share/app/'+name.split('/',1)[1] if name.startswith('resources/') else None
        if path is None or not allowed(path):raise ValueError('Look update exceeded its resource scope')
        result[path]=(current[name],raw)
    return save_package(result,output,'looks',source_baseline=folder)


def compile_sound(folder,payload,selection,csv,output):
    import targeted_sound
    folder,current,records,manifest=baseline(folder)
    programs,edits=targeted_sound.program_plan(current['appFw.so'],current['cpapp-b.bin'],selection)
    if programs['appFw.so']!=current['appFw.so']:
        raise ValueError('基础固件尚未加入自定义音效读取器；请先在电脑重新生成固件候选')
    raw=Path(payload).read_bytes()
    audio,configuration,name,rows=targeted_sound.configuration(csv,raw,selection,installed=bool(csv))
    updates={'/usr/share/avsystemsound/'+name:(None,audio),
             '/usr/share/avsystemsound/custom.txt':(csv or None,configuration)}
    if programs['cpapp-b.bin']!=current['cpapp-b.bin']:
        updates['/cp/cpapp-b.bin']=(current['cpapp-b.bin'],programs['cpapp-b.bin'])
    return save_package(updates,output,'sound',source_baseline=folder)


def compile_sound_switch(folder,selection,enabled,output):
    import candidate
    folder,current,records,manifest=baseline(folder)
    if selection=='mechanical':programs=candidate.mechanical(current['appFw.so'],current['cpapp-b.bin'],enabled)
    elif selection=='electronic':
        programs=(candidate.patch if enabled else candidate.disable)(current['appFw.so'],current['cpapp-b.bin'])
    else:raise ValueError('Select mechanical or electronic speaker sound')
    if programs['appFw.so']!=current['appFw.so']:raise ValueError('Sound switch requires a matching local firmware baseline')
    updates={} if programs['cpapp-b.bin']==current['cpapp-b.bin'] else {
        '/cp/cpapp-b.bin':(current['cpapp-b.bin'],programs['cpapp-b.bin'])}
    return save_package(updates,output,'sound-switch',source_baseline=folder)


def prepare_version_restore(connection,output,*,source_version='3.01',target_version='2.00'):
    """Use Sony's two-byte VersionFile format, not a display-string patch."""
    from .firmwarelocal import version_bytes
    major,minor=version_bytes(source_version);expected=bytes((minor,major))
    major,minor=version_bytes(target_version);target=bytes((minor,major))
    actual=connection.read('/setting/updater/dat4')
    if actual!=expected:raise ValueError('当前更新器版本不是 '+source_version+'；本次未写入版本资料')
    result=save_package({'/setting/updater/dat4':(actual,target)},output,'version',source_baseline='')
    result.update(source_version=source_version,target_version=target_version)
    write_json(Path(output)/'update.private.json',{k:v for k,v in result.items() if k!='workspace'})
    return result


def save_package(updates,output,kind,*,source_baseline):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    rows=[]
    # New audio is published first, the single referencing CSV last.
    for index,(path,(before,after)) in enumerate(sorted(updates.items(),key=lambda x:(x[0].endswith('/custom.txt'),x[0]))):
        if not allowed(path):raise ValueError('Unexpected update target')
        after_name='file-%03d.after.bin'%index;(output/after_name).write_bytes(after)
        before_name=None
        if before is not None:
            before_name='file-%03d.before.bin'%index;(output/before_name).write_bytes(before)
        rows.append(dict(path=path,before=before_name,after=after_name))
    report=dict(schema='a7c2-ssh-resource-update/1',kind=kind,phase='PREPARED',
                source_baseline=str(source_baseline),rows=rows,camera_io=False,
                physical_tested=False,reload_required=True)
    write_json(output/'update.private.json',report)
    return dict(report,workspace=str(output))


def apply(folder,connection):
    """Publish once; full staged and committed bytes are read back on the host."""
    folder=Path(folder);state=json.loads((folder/'update.private.json').read_text(encoding='utf-8'))
    if state.get('schema')!='a7c2-ssh-resource-update/1' or state.get('phase')!='PREPARED':
        raise ValueError('Preserve the previous SSH update; do not replay an attempted transaction')
    state.update(phase='ATTEMPTED',journal=[])
    def record(event,**data):
        state['journal'].append(dict(event=event,**data));write_json(folder/'update.private.json',state)
    record('intent_saved_before_ssh')
    try:
        boot=connection.read('/proc/sys/kernel/random/boot_id').decode().strip()
        if not re.fullmatch(r'[a-f0-9-]{36}',boot):raise ValueError('Missing SSH boot identity')
        state['source_boot_id']=boot
        if not state['rows']:
            state.update(phase='LOADED',camera_io=True,next_baseline=state['source_baseline'])
            record('already_matches_no_publication')
            return dict(state,workspace=str(folder))
        for row in state['rows']:
            if not allowed(row['path']):raise ValueError('Unexpected update path')
            actual=connection.read(row['path'],missing=row['before'] is None)
            expected=(folder/row['before']).read_bytes() if row['before'] else b''
            if actual!=expected:raise ValueError('相机文件与本地更新基线不一致：'+row['path'])
        mounts=connection.read('/proc/self/mounts').decode()
        affected={'/'+row['path'].split('/')[1] for row in state['rows']}
        readonly={part for line in mounts.splitlines() if len(parts:=line.split())>3
                  and (part:=parts[1]) in affected and 'ro' in parts[3].split(',')}
        # One root-owned lock per active boot. An unknown result leaves it in
        # place for review; no automatic force-unlock or repeated publication.
        lock='/tmp_wbshd/a7c2-resource-update.lock'
        connection.execute('umask 077; mkdir '+lock);record('remote_lock_created')
        for part in sorted(readonly):connection.execute('mount -o remount,rw '+part);record('remounted_rw',path=part)
        nonce=uuid.uuid4().hex[:12]
        for row in state['rows']:
            target=row['path'];staged=target+'.a7c2-'+nonce+'.new';after=(folder/row['after']).read_bytes()
            # Fixed allowlist targets determine this temporary pathname.
            command='umask 077; test ! -e '+shlex.quote(staged)+' && cat > '+shlex.quote(staged)
            record('stage_intent',path=target)
            connection.execute(command,after)
            actual=connection.execute('cat '+shlex.quote(staged))
            if actual!=after:raise ValueError('SSH staged file readback differs: '+target)
            connection.execute('chmod 644 '+shlex.quote(staged)+' && sync')
            record('publish_intent',path=target)
            connection.execute('mv -f '+shlex.quote(staged)+' '+shlex.quote(target)+' && sync')
            if connection.read(target)!=after:raise ValueError('SSH published file readback differs: '+target)
            record('published_bytes_verified',path=target)
        for part in sorted(readonly):connection.execute('mount -o remount,ro '+part);record('remounted_ro',path=part)
        connection.execute('rmdir '+lock);record('remote_lock_removed')
        state.update(phase='AWAITING_RELOAD',camera_io=True)
        write_json(folder/'update.private.json',state)
        return dict(state,workspace=str(folder))
    except BaseException as exc:
        state.update(phase='NEEDS_REVIEW',error=type(exc).__name__+': '+str(exc))
        write_json(folder/'update.private.json',state)
        raise


def verify_reload(folder,connection):
    folder=Path(folder);state=json.loads((folder/'update.private.json').read_text(encoding='utf-8'))
    if state.get('schema')!='a7c2-ssh-resource-update/1' or state.get('phase')!='AWAITING_RELOAD':
        raise ValueError('先完成所选 SSH 更新，再核对重新加载')
    boot=connection.read('/proc/sys/kernel/random/boot_id').decode().strip()
    if not re.fullmatch(r'[a-f0-9-]{36}',boot) or boot==state['source_boot_id']:
        raise ValueError('尚未观察到新的冷启动；不把磁盘读回当作已经重新加载')
    for row in state['rows']:
        if connection.read(row['path'])!=(folder/row['after']).read_bytes():
            raise ValueError('重开后的资源与本次更新目标不同：'+row['path'])
    if state['kind']=='version':
        state.update(phase='LOADED',verified_boot_id=boot,physical_official_upgrade_verified=False)
        write_json(folder/'update.private.json',state)
        return dict(state,workspace=str(folder))
    old=Path(state['source_baseline']);next_baseline=folder/'next-baseline'
    if not next_baseline.exists():
        staging=folder/('next-baseline-'+uuid.uuid4().hex[:8]+'.new')
        shutil.copytree(old,staging)
        for row in state['rows']:
            name=('cpapp-b.bin' if row['path']=='/cp/cpapp-b.bin' else
                  'resources/'+Path(row['path']).name if row['path'].startswith('/usr/share/app/') else
                  'audio/'+Path(row['path']).name)
            path=staging/name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes((folder/row['after']).read_bytes())
        staging.rename(next_baseline)
    state.update(phase='LOADED',verified_boot_id=boot,next_baseline=str(next_baseline),
                 physical_photo_verified=False)
    write_json(folder/'update.private.json',state)
    return dict(state,workspace=str(folder))


def run(action,args,job):
    """Desktop routing; compile commands are local and never create a connection."""
    from .worker import setup_runtime
    setup_runtime()
    sys.path.insert(0,str(ROOT/'src/shutter_sound'))
    output=Path(args['workspace'])
    if action=='ssh_compile_looks':
        operations=args.get('operations',[])
        if not operations or any(row.get('action')!='write' for row in operations):
            raise ValueError('添加要通过 SSH 更新的 A7Look 槽位；恢复默认请重新生成本地固件')
        result=compile_look(args['baseline'],operations,output)
    elif action=='ssh_compile_sound':
        import media
        conversion=Path(job)/'converted-audio'
        media.convert(args['source'],conversion,start=float(args.get('start',0)),
                      duration=float(args.get('duration',.08)),peak=float(args.get('peak',.4)))
        csv=Path(args['baseline'])/'audio/custom.txt'
        result=compile_sound(args['baseline'],conversion/'custom-native.private.bin',args['selection'],
                             csv.read_bytes() if csv.exists() else b'',output)
    elif action=='ssh_compile_sound_switch':
        result=compile_sound_switch(args['baseline'],args['selection'],bool(args['enabled']),output)
    elif action in ('ssh_apply_update','ssh_verify_update','ssh_connect','ssh_prepare_version'):
        connection=Connection(args['bind_ip'],args['client_private'],args['host_public'],Path(job)/'ssh-connection')
        if action=='ssh_prepare_version':
            result=prepare_version_restore(connection,output,source_version=args.get('source_version','3.01'),
                                           target_version=args.get('target_version','2.00'))
        elif action=='ssh_connect':
            response=connection.execute("printf 'A7C2_SSH_OK\\n'; /bin/busybox uname -m; /bin/busybox grep '^Uid:' /proc/self/status; cat /proc/sys/kernel/random/boot_id")
            lines=response.decode('ascii').splitlines()
            if len(lines)!=4 or lines[:2]!=['A7C2_SSH_OK','aarch64'] or not re.fullmatch(r'Uid:\s+0\s+0\s+0\s+0\s*',lines[2]) or not re.fullmatch(r'[a-f0-9-]{36}',lines[3]):
                raise ValueError('SSH architecture/root/boot identity response differs')
            result=dict(phase='SSH_VERIFIED',workspace=str(output),camera_io=True,persistent_startup=False,
                        wifi_trigger=True,
                        source_boot_id=lines[3],firmware_written=False)
        elif action=='ssh_apply_update':result=apply(output,connection)
        else:result=verify_reload(output,connection)
    else:raise ValueError('Unknown SSH resource action: '+action)
    write_json(Path(job)/'backend-workspace.private.json',dict(action=action,workspace=str(output)))
    return result
