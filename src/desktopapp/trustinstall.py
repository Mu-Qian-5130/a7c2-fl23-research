"""First C2 owner-key installation and original-trust restoration transactions.

The host builds a small in-place updater change from this body's read-only dump.
The camera only executes bounded partition reads/byte comparisons/writes.
"""
from contextlib import contextmanager
import json,os,uuid
from pathlib import Path
from .paths import write_json
from .identity import signing_paths
from . import updaterimage,trustworker

STATE='trust-install.private.json'


def validate_request(action,args):
    if not str(args.get('workspace') or '').strip():raise ValueError('请选择新的安装记录目录')
    if Path(args['workspace']).exists():raise ValueError('安装记录目录已存在，请使用新的目录并保留原始记录')
    if action=='firmware_trust_install':return
    if not str(args.get('source_workspace') or '').strip():raise ValueError('请先选择首次安装备份记录')
    source=Path(args['source_workspace'])
    state=json.loads((source/STATE).read_text(encoding='utf-8'))
    if state.get('schema')!='a7c2-first-trust/1':raise ValueError('不是机身公钥安装记录')
    if action=='firmware_trust_verify':
        if state.get('phase')!='AWAITING_RELOAD':raise ValueError('此记录没有等待重开核对的安装或恢复')
    elif state.get('mode')!='trust_install' or not state.get('backup_verified'):
        raise ValueError('请选择首次安装时保存的原始备份记录')


def durable(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())


class UsbPartition:
    camera_io=True

    def prepare(self,job):
        self.readers={}
        for at in range(0,updaterimage.PARTITION_BYTES,1048576):
            count=min(1048576,updaterimage.PARTITION_BYTES-at)
            self.readers[at]=trustworker.build(job.root/'workers'/('read-%08x'%at),0,at,count,zig=job.zig)

    @contextmanager
    def session(self,job,expected=None):
        from looktool.devicesession import Camera
        from looktool.devicejob import Job,PROGRAM_PATHS
        with Camera(expected) as camera:
            current={name:camera.read(path) for name,path in PROGRAM_PATHS.items()}
            camera.byte_checks=True;camera.pin_programs(current['appFw.so'],current['cpapp-b.bin'])
            runtime=Job._invoke(job,camera,'runtime',0)
            camera.confirm_identity(runtime)
            self.camera=camera;self.identity=dict(camera.identity);self.boot_id=runtime['boot_id']
            if getattr(job,'restore_source',None):self.cleanup_prior(job)
            yield self

    def cleanup_prior(self,job):
        """Resolve only this install's finished native operation, before a fresh restore.

        A present result was emitted after all partition I/O and fd closure. A
        missing result or a pending loader is left intact; no operation is replayed.
        """
        camera=self.camera
        stage=camera.temp_read('a7c2.trust.staged.so',True)
        result=camera.temp_read('a7c2.trust.result',True)
        chunk=camera.temp_read('a7c2.trust.chunk',True)
        if stage is None and result is None and chunk is None:return
        if camera.temp_read('libJit.so',True) is not None or stage is None or result is None:
            raise ValueError('上次公钥安装尚无完整结束结果；请保留记录，先断电重开再从原始备份恢复')
        matches=[p for p in (job.restore_source/'workers').glob('*/trust.so') if p.read_bytes()==stage]
        if len(matches)!=1 or len(result)!=trustworker.REPORT.size:
            raise ValueError('上次安装的临时文件无法与原始事务核对，请保留记录')
        config=(matches[0].parent/'trust.private.h').read_text(encoding='ascii')
        values={name:int(config.split('#define '+name+' ',1)[1].split('UL',1)[0].splitlines()[0])
            for name in ('TRUST_MODE','TRUST_OFFSET','TRUST_COUNT')}
        row=trustworker.REPORT.unpack(result)
        if row[:3]!=(b'A7TRST01',1,values['TRUST_MODE']) or row[5:7]!=(values['TRUST_OFFSET'],values['TRUST_COUNT']):
            raise ValueError('上次安装的临时结果与执行范围不同，请保留记录')
        if chunk is not None and (row[2]!=0 or len(chunk)!=row[6]):
            raise ValueError('上次安装的临时读取文件不完整，请保留记录并断电重开')
        for name,data in (('a7c2.trust.staged.so',stage),('a7c2.trust.chunk',chunk),('a7c2.trust.result',result)):
            if data is None:continue
            job.raw('prior-'+name,data)
            if camera.temp_read(name,True)!=data:raise ValueError('上次安装的临时文件仍在变化，请断电重开')
            camera.temp_remove(name)
            if camera.temp_read(name,True) is not None:raise ValueError('上次安装的临时文件清理未完成')
        job.record('prior_trust_operation_preserved_no_replay',mode=row[2],phase=row[3],writes=row[4],
            offset=row[5],count=row[6],completed=row[8],status=row[9])

    def read(self,job,offset,count):
        from looktool.devicesession import invoke
        payload=[]
        def decode(raw):
            result=trustworker.parse(raw,0,offset,count)
            data=self.camera.temp_read('a7c2.trust.chunk')
            if len(data)!=count:raise ValueError('Incomplete updater backup chunk')
            payload.append(data);return result
        invoke(self.camera,self.readers[offset].read_bytes(),stage='a7c2.trust.staged.so',request=None,
            result='a7c2.trust.result',contents=None,mode=0,decode=decode,record=job.record,
            save_raw=lambda raw:job.raw('partition-read.bin',raw),extras=('a7c2.trust.chunk',))
        return payload[0]

    def prepare_writes(self,job,rows):
        self.writers=[]
        for index,(at,before,after) in enumerate(rows):
            self.writers.append(trustworker.build(job.root/'workers'/('write-%03d'%index),2,at,len(before),before,after,job.zig))

    def write(self,job,index,offset,before,after):
        from looktool.devicesession import invoke
        return invoke(self.camera,self.writers[index].read_bytes(),stage='a7c2.trust.staged.so',request=None,
            result='a7c2.trust.result',contents=None,mode=2,decode=lambda raw:trustworker.parse(raw,2,offset,len(before)),
            record=job.record,save_raw=lambda raw:job.raw('partition-write.bin',raw))


class Installer:
    def __init__(self,folder,backend=None,zig=None):
        self.root=Path(folder).resolve();self.backend=backend or UsbPartition();self.zig=zig
        self.state_path=self.root/STATE
        self.state=dict(schema='a7c2-first-trust/1',phase='PREPARING',journal=[],camera_io=self.backend.camera_io,
            first_install_implemented=True,private_key_in_camera_files=False,updater_boot_verified=False,
            physical_tested=False,write_attempted=False)

    def record(self,event,**values):
        self.state['journal'].append(dict(event=event,**values));write_json(self.state_path,self.state)

    def save(self,phase,**values):
        self.state.update(phase=phase,**values);write_json(self.state_path,self.state)
        print('公钥安装：'+phase,flush=True)

    def raw(self,name,data):
        folder=self.root/'evidence';folder.mkdir(exist_ok=True)
        durable(folder/(uuid.uuid4().hex[:8]+'-'+name),data)

    def _hashes(self):return False

    def read_partition(self):
        data=bytearray()
        for index,at in enumerate(range(0,updaterimage.PARTITION_BYTES,1048576)):
            count=min(1048576,updaterimage.PARTITION_BYTES-at)
            chunk=self.backend.read(self,at,count)
            if len(chunk)!=count:raise ValueError('Updater partition backup is incomplete')
            data.extend(chunk)
            print('更新器读回 %d / 24'%(index+1),flush=True)
        return bytes(data)

    def run(self,*,source=None):
        self.root.mkdir(parents=True,exist_ok=False)
        mode='trust_restore' if source else 'trust_install';self.save('PREPARING',mode=mode)
        try:
            backup_state=None
            if source:
                source=Path(source).resolve();backup_state=json.loads((source/STATE).read_text(encoding='utf-8'))
                if backup_state.get('schema')!='a7c2-first-trust/1' or not backup_state.get('backup_verified'):
                    raise ValueError('请选择本机首次授信时保存的完整备份记录')
                if backup_state.get('mode')!='trust_install':raise ValueError('请选择原始的首次授信记录，而不是恢复或核对记录')
                original=(source/'original-updater.private.img').read_bytes()
                if original!=(source/'original-updater-copy.private.img').read_bytes():raise ValueError('Original updater backup copies differ')
                old_candidate=(source/'candidate-updater.private.img').read_bytes()
                if len(original)!=updaterimage.PARTITION_BYTES:raise ValueError('Original updater backup size differs')
                if len(old_candidate)!=len(original):raise ValueError('Recorded updater candidate size differs')
                expected=backup_state['identity']
                self.restore_source=source
            else:expected=None
            self.backend.prepare(self)
            self.save('READING')
            with self.backend.session(self,expected):
                captured=self.read_partition();identity=dict(self.backend.identity);boot=self.backend.boot_id
            self.save('BACKING_UP',identity=identity,source_boot_id=boot)
            if not source:original=captured
            else:durable(self.root/'current-updater.private.img',captured)
            durable(self.root/'original-updater.private.img',original)
            durable(self.root/'original-updater-copy.private.img',original)
            if (self.root/'original-updater.private.img').read_bytes()!=original or (self.root/'original-updater-copy.private.img').read_bytes()!=original:
                raise ValueError('Updater backup readback differs')
            self.save('BUILDING',backup_verified=True)
            if source:
                # Interrupted writes may leave unknown bytes only inside this job's
                # planned sectors. Re-read them and build a separate restore request.
                permitted=set()
                for at,before,after in updaterimage.spans(original,old_candidate):permitted.update(range(at//512,(at+len(before))//512))
                for at in range(0,len(original),512):
                    if at//512 not in permitted and captured[at:at+512]!=original[at:at+512]:
                        raise ValueError('Updater changed outside the recorded installation; preserve the current state')
                target=original;image_report=dict(original_trust_restore=True,source_workspace=str(source))
            else:
                _,public=signing_paths();target,image_report=updaterimage.build(original,public.read_bytes())
            durable(self.root/'candidate-updater.private.img',target)
            write_json(self.root/'image.private.json',image_report)
            rows=updaterimage.write_plan(original,captured,target)
            self.save('PLANNED',windows=[dict(offset=at,bytes=len(before)) for at,before,after in rows],
                verify_image=str(self.root/'candidate-updater.private.img'),source_workspace=str(source) if source else None)
            self.backend.prepare_writes(self,rows)
            with self.backend.session(self,identity):
                if self.read_partition()!=captured:raise ValueError('Updater changed after its backup; no partition write started')
                self.save('WRITING',source_boot_id=self.backend.boot_id)
                for index,(at,before,after) in enumerate(rows):
                    self.save('WRITING',write_attempted=True,current_window=index)
                    self.record('partition_write_intent',index=index,offset=at,bytes=len(before))
                    self.backend.write(self,index,at,before,after)
                    self.record('partition_window_readback_verified',index=index)
                    print('更新器写入与核对 %d / %d'%(index+1,len(rows)),flush=True)
                if self.read_partition()!=target:raise ValueError('Complete updater partition readback differs')
            self.save('AWAITING_RELOAD',partition_readback_verified=True,reload_required=True,
                physical_tested=self.backend.camera_io,public_key_installed=not bool(source),
                original_trust_restored=bool(source))
            return dict(self.state,workspace=str(self.root))
        except BaseException as exc:
            self.save('NEEDS_REVIEW',failed_during=self.state['phase'],error=type(exc).__name__+': '+str(exc))
            raise

    def verify(self,source):
        self.root.mkdir(parents=True,exist_ok=False)
        try:
            previous=Path(source).resolve();state=json.loads((previous/STATE).read_text(encoding='utf-8'))
            if state.get('schema')!='a7c2-first-trust/1' or state.get('phase')!='AWAITING_RELOAD':
                raise ValueError('先完成公钥安装或原厂信任恢复，再断电重开核对')
            self.save('READING_VERIFY',mode=state['mode'],source_workspace=str(previous),identity=state['identity'])
            self.backend.prepare(self)
            with self.backend.session(self,state['identity']):
                if self.backend.boot_id==state['source_boot_id']:raise ValueError('尚未观察到新的启动，请先按步骤断电重开')
                if self.read_partition()!=Path(state['verify_image']).read_bytes():raise ValueError('重开后的更新器与安装目标不同，请保留记录')
            self.save('LOADED',partition_readback_verified=True,new_boot_observed=True,
                physical_tested=self.backend.camera_io,updater_boot_verified=False,reload_required=False)
            return dict(self.state,workspace=str(self.root))
        except BaseException as exc:
            self.save('NEEDS_REVIEW',failed_during=self.state['phase'],error=type(exc).__name__+': '+str(exc))
            raise


def run(action,args,job):
    validate_request(action,args)
    installer=Installer(args['workspace'],zig=args.get('zig'))
    write_json(Path(job)/'backend-workspace.private.json',dict(workspace=str(installer.root)))
    if action=='firmware_trust_verify':result=installer.verify(args['source_workspace'])
    else:result=installer.run(source=args.get('source_workspace') if action=='firmware_trust_restore' else None)
    return result
