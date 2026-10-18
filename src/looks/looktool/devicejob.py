"""Explicit backup/fit/write/readback/reload/restore job, with durable evidence.

No device is opened at import time. Unknown native outcomes are never replayed.
"""
from datetime import datetime,timezone
import json,os,shutil,struct,uuid
from pathlib import Path
from . import calibration,device_layout,devicesettings,firmware,nameworker,native,nativebuild,project,resources,worker
from .devicesession import Camera,invoke
from .devicelock import serialized

PROGRAM_PATHS={'appFw.so':'/usr/lib/appFw.so','cpapp-b.bin':'/cp/cpapp-b.bin'}

def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_name(path.name+'.new')
    with temporary.open('w',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,indent=2,ensure_ascii=False,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)

class Job:
    def __init__(self,folder,*,factory=Camera,zig=None):
        self.root=Path(folder).resolve();self.factory=factory;self.zig=zig;self.state_path=self.root/'job.private.json'
    def save(self,phase,**values):
        self.state.update(values);self.state['phase']=phase;write_json(self.state_path,self.state)
        print('LUT:',phase,flush=True)
    def record(self,phase,**values):
        self.state.setdefault('journal',[]).append({'time':datetime.now(timezone.utc).isoformat(),'event':phase,**values})
        write_json(self.state_path,self.state)
    def raw(self,name,data):
        path=self.root/'evidence'/(str(len(self.state.get('journal',[]))).zfill(5)+'-'+uuid.uuid4().hex[:8]+'-'+name);path.parent.mkdir(exist_ok=True)
        with path.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
    def load(self):
        self.state=json.loads(self.state_path.read_text(encoding='utf-8'))
        if self.state.get('schema')!='a7c2-lut-device-job/1':raise ValueError('Unknown device job')
        second=Path(self.state['backup_copy'])
        if second==self.root or self.root in second.parents or second in self.root.parents:raise ValueError('Independent backup folders required')
        for name,expected in self.state['backup_files'].items():
            for base in [self.root/'source',second]:
                if firmware.sha((base/name).read_bytes())!=expected:raise ValueError('Body backup differs: '+name)
        for name,expected in self.state.get('artifacts',{}).items():
            if firmware.sha((self.root/name).read_bytes())!=expected:raise ValueError('Job artifact changed: '+name)
        return self
    def artifacts(self):
        result={}
        for folder in ['input','candidate','transition','worker','resource-target']:
            for path in (self.root/folder).rglob('*'):
                if path.is_file() and not any(p.startswith('zig-') for p in path.relative_to(self.root/folder).parts):
                    result[path.relative_to(self.root).as_posix()]=firmware.sha(path.read_bytes())
        self.state['artifacts']=result
    def _invoke(self,camera,kind,mode):
        if kind=='program':
            build=self.state['program_build']
            if build['unchanged']:return {'unchanged':True}
            blob=(self.root/'worker/program/program.so').read_bytes();stage='lut-program-staged.so';request='a7c2.install.request';result='a7c2.install.result';magic=b'A7INS001'
            decode=lambda raw:worker.validate_worker_report(raw,mode,build['contract'])
        elif kind=='names':
            build=self.state['name_build'];blob=(self.root/'worker/names/names.so').read_bytes();stage='lut-names-staged.so';request='a7c2.names.request';result='a7c2.names.result';magic=b'A7NAM001'
            decode=lambda raw:nameworker.validate(raw,mode,build)
        elif kind=='wbi':
            camera.core.assets();blob=(nativebuild.ROOT/'src/fl23/assets/wbi.so').read_bytes();stage='lut-program-staged.so';request='a7c2.wbi.request';result='a7c2.wbi.result';magic=b'A7WBI001'
            decode=lambda raw:camera.core.parse_native('wbi',raw,mode)
        elif kind=='runtime':
            camera.core.assets();blob=(nativebuild.ROOT/'src/fl23/assets/runtime.so').read_bytes();stage='lut-runtime-staged.so';request=None;result='a7c2.runtime.result';magic=None
            def decode(raw):
                value=camera.core.parse_native('runtime',raw)
                value.update(image_dev=raw[1608:1640].split(b'\0')[0].decode('ascii'),boot_id=raw[1768:1832].split(b'\0')[0].decode('ascii'))
                return value
        else:raise ValueError('Unknown native operation')
        if kind in ['program','names'] and firmware.sha(blob)!=build['sha256']:raise ValueError('Compiled worker changed')
        return invoke(camera,blob,stage=stage,request=request,result=result,contents=struct.pack('<8sII',magic,mode,0) if request else None,mode=mode,decode=decode,record=self.record,save_raw=lambda raw:self.raw(kind+'-'+str(mode)+'.bin',raw),extras=('a7c2.probe.result',) if kind=='runtime' else ())
    def _read_programs(self,camera,expected):
        actual={}
        for name,path in PROGRAM_PATHS.items():
            raw=camera.read(path);actual[name]=raw
            if firmware.sha(raw)!=expected[name]:raise ValueError('Complete host readback differs: '+name)
            self.raw('readback-'+name+'.bin',raw)
        self.record('complete_host_program_readback_verified',hashes={n:firmware.sha(b) for n,b in actual.items()})
        return actual
    def _resource_readback(self,camera,after):
        for spec in self.state['name_build']['files']:
            raw=camera.read('/usr/share/app/'+spec['file']);which='after' if after else 'before'
            if len(raw)!=spec[which+'_bytes'] or firmware.sha(raw)!=spec[which+'_sha256']:raise ValueError('Complete name readback differs: '+spec['file'])
        self.record('complete_name_resources_readback_verified',after=after,count=68)
    def _capture(self,camera,second):
        print('Reading full programs, saved/live settings and 68 name resources; keep USB connected.',flush=True)
        self.state['identity']=camera.identity
        runtime=self._invoke(camera,'runtime',0)
        if not runtime['boot_id'].strip():raise ValueError('Read-only boot identity unavailable')
        self.state['source_runtime']=runtime
        values={name:camera.read(path) for name,path in PROGRAM_PATHS.items()}
        samples=[]
        for sample in range(3):
            ram,saved=camera.snapshot(True),camera.snapshot(False)
            values[f'controls/{sample}-ram.bin']=ram;values[f'controls/{sample}-saved.bin']=saved
            samples.append((camera.records(ram),camera.records(saved)))
        self.state['preservation_controls']=devicesettings.controls(samples,camera.core)
        values['settings-ram.bin']=ram;values['settings-saved.bin']=saved
        for filename in nameworker.filenames():values['resources/'+filename]=camera.read('/usr/share/app/'+filename)
        values['boot-id.bin']=runtime['boot_id'].encode('ascii')
        self.state['backup_files']={}
        for name,raw in values.items():
            for base in [self.root/'source',second]:
                path=base/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
                if path.read_bytes()!=raw:raise ValueError('Independent backup readback differs')
            self.state['backup_files'][name]=firmware.sha(raw)
        self.state['identity']=camera.identity;self.save('BACKUPS_VERIFIED')
        return values
    def _fit(self,source,name,slot,model,attribution):
        source=Path(source).resolve();model=calibration.validate(model,source.suffix.lower()=='.dcp')
        input_dir=self.root/'input';input_dir.mkdir();stored=input_dir/('reference'+source.suffix.lower());stored.write_bytes(source.read_bytes())
        write_json(input_dir/'calibration.json',model)
        entry={'slot':slot,'name':name,'base':'ST','source':{'type':'dcp' if source.suffix.lower()=='.dcp' else 'cube','path':stored.name,'attribution':attribution}}
        if entry['source']['type']=='cube':
            contract=self.state['reference_contract'];entry['source'].update(input_space=contract['input_space'],output_space='srgb')
            if contract.get('bridge'):
                bridge=input_dir/'bridge.cube';bridge.write_bytes(Path(contract['bridge']).read_bytes())
                entry['source']['bridge']={'path':bridge.name,'input_space':'sony-st-srgb','output_space':contract['input_space'],'evidence':'Explicit user-supplied input-space bridge; independent color validation still required'}
        if entry['source']['type']=='dcp':entry['source']['exposure_stops']=model.get('reference_exposure_stops',0)
        render,provenance=project.reference(entry,input_dir,model)
        raw,report=native.fit_reference(render,model['response_matrix'],seed=201+slot)
        if not report['convergence']['converged']:raise ValueError('Table fit did not converge')
        candidate=self.root/'candidate';candidate.mkdir();(candidate/f'slot{slot}.bin').write_bytes(raw)
        write_json(candidate/'fit.private.json',{'source':provenance,'calibration_sha256':firmware.sha((input_dir/'calibration.json').read_bytes()),'fit':report})
        self.record('reference_converted',slot=slot,table_sha256=firmware.sha(raw),fit_error=report['synthetic_holdout'])
        return raw
    def _prepare(self,camera,name,slot,second,raw):
        values=self._capture(camera,second)
        ap,cp=values['appFw.so'],values['cpapp-b.bin'];self.state['layout']=device_layout.identify(ap,cp)
        for span in self.state['source_runtime']['spans']:
            expected=ap[span['offset']:span['offset']+span['length']].hex()
            if span['memory']!=expected or span['disk']!=expected:raise ValueError('Source AP RAM/disk differ; finish the previous reload before importing')
        f,r,after=device_layout.replace(ap,cp,{slot:raw});write_json(self.root/'transition/forward.private.json',f);write_json(self.root/'transition/reverse.private.json',r)
        self.state['source_hashes']={n:firmware.sha(values[n]) for n in PROGRAM_PATHS};self.state['target_hashes']={n:firmware.sha(after[n]) for n in PROGRAM_PATHS}
        self.state['settings_plan']=devicesettings.plan(ap,camera.records(values['settings-ram.bin']),camera.records(values['settings-saved.bin']),[slot])
        self.state['program_build']=nativebuild.build_program({n:values[n] for n in PROGRAM_PATHS},f,r,self.root/'worker/program',self.zig)
        renamed,self.state['name_build']=nameworker.prepare({n:values['resources/'+n] for n in nameworker.filenames()},{slot:name},ap,self.state['job_id'],self.root/'worker/names',self.zig,target_ap=after['appFw.so'],label_ids=self.state['layout']['label_ids'])
        folder=self.root/'resource-target';folder.mkdir()
        for n,b in renamed.items():(folder/n).write_bytes(b)
        self.artifacts();self.save('PREPARED')
        self._read_programs(camera,self.state['source_hashes'])
        self._invoke(camera,'program',0);self._invoke(camera,'names',0)
        self.save('PREFLIGHT_VERIFIED')
    def _settings(self,camera,restore=False,resume=False):
        self._validate_settings_plan(camera)
        self.save('SETTINGS_RESTORE_INTENT' if restore else 'SETTINGS_WRITE_INTENT')
        before_ram=camera.snapshot(True);before_saved=camera.snapshot(False)
        ram,saved=camera.records(before_ram),camera.records(before_saved);fields=self.state['settings_plan'];changed=False
        if any(ram[0][f['key']].data!=bytes.fromhex(f['before_ram'] if restore else f['after']) for f in fields):
            devicesettings.require_save_preserves_unsaved(ram,saved,{f['key'] for f in fields})
        expected_ram={};expected_saved={}
        for field in fields:
            key=field['key'];want=bytes.fromhex(field['before_ram'] if restore else field['after'])
            current=bytes.fromhex(field['after'] if restore else field['before_ram'])
            current_saved=bytes.fromhex(field['after'] if restore else field['before_saved'])
            allowed_ram=[current,want] if resume else [current]
            allowed_saved=[current_saved,want] if resume else [current_saved]
            if ram[0][key].data not in allowed_ram or saved[0][key].data not in allowed_saved:raise ValueError('Selected settings changed since preparation')
            current=ram[0][key].data
            expected_ram[key]=want.hex();expected_saved[key]=want.hex()
            if camera.property_read(key)!=current:raise ValueError('Independent setting read differs')
            if current!=want:
                self.record('setting_write_intent',key=key,restore=restore,before=current.hex(),after=want.hex())
                camera.property_write(key,want,{f['key'] for f in fields})
                if camera.property_read(key)!=want:raise ValueError('Selected setting readback differs')
                changed=True
        if changed or any(saved[0][f['key']].data!=bytes.fromhex(expected_saved[f['key']]) for f in fields):
            self.record('setting_save_intent',restore=restore);camera.save_settings()
        after_ram=camera.snapshot(True);after_saved=camera.snapshot(False)
        proof=self.state['preservation_controls']
        devicesettings.compare(ram,camera.records(after_ram),expected_ram,camera.core,proof,True)
        devicesettings.compare(saved,camera.records(after_saved),expected_saved,camera.core,proof,False)
        devicesettings.protected_equal(ram,camera.records(after_ram));devicesettings.protected_equal(saved,camera.records(after_saved))
        self.raw(('restore-' if restore else '')+'settings-ram.bin',after_ram);self.raw(('restore-' if restore else '')+'settings-saved.bin',after_saved)
        self.record('settings_preservation_verified',restore=restore,fields=len(fields));self.save('SETTINGS_RESTORED' if restore else 'SETTINGS_VERIFIED')
    def _validate_settings_plan(self,camera):
        source=self.root/'source'
        expected=devicesettings.plan((source/'appFw.so').read_bytes(),camera.records((source/'settings-ram.bin').read_bytes()),camera.records((source/'settings-saved.bin').read_bytes()),[self.state['slot']])
        if expected!=self.state['settings_plan']:raise ValueError('Selected settings plan differs from the original verified descriptors')
    def _reload(self,camera):
        runtime=self._invoke(camera,'runtime',0)
        if not runtime['boot_id'].strip():raise ValueError('Read-only boot identity unavailable')
        self.state['reload_before_boot_id_sha256']=firmware.sha(runtime['boot_id'].encode('ascii'))
        mode=runtime['image_mode'];backend=runtime['image_dev']
        if backend!='*wbi4\n':raise ValueError('Unknown retained-image backend')
        if mode=='2\n':self._invoke(camera,'wbi',1)
        elif mode=='0\n':self.record('retained_image_already_invalidated')
        else:raise ValueError('Unknown retained-image mode; inspect before power changes')
        if self._invoke(camera,'runtime',0)['image_mode']!='0\n':raise ValueError('Retained-image invalidation not verified')
        self.record('reload_prepared');self.save('AWAITING_RELOAD')
    def _install(self,camera):
        if self.state['phase']!='PREFLIGHT_VERIFIED':raise ValueError('New preflight is required; unknown operations cannot be repeated')
        self.state['active_operation']='install'
        self._validate_settings_plan(camera)
        self._read_programs(camera,self.state['source_hashes'])
        self._resource_readback(camera,False)
        for memory,label in [(True,'settings-ram.bin'),(False,'settings-saved.bin')]:
            baseline=camera.records((self.root/'source'/label).read_bytes());fresh=camera.records(camera.snapshot(memory))
            devicesettings.compare(baseline,fresh,{},camera.core,self.state['preservation_controls'],memory)
        self.save('NAME_WRITE_INTENT');self._invoke(camera,'names',1);self._resource_readback(camera,True);self.save('NAMES_VERIFIED')
        self.save('PROGRAM_WRITE_INTENT');self._invoke(camera,'program',1);self._read_programs(camera,self.state['target_hashes']);self.save('PROGRAMS_VERIFIED')
        self._settings(camera);self._reload(camera)
    @serialized
    def create(self,source,name,slot,calibration_path,backup_copy,*,write=False,battery=None,attribution='User-selected reference; original rights apply',input_space=None,bridge=None):
        source=Path(source).resolve()
        if source.suffix.lower() not in ['.dcp','.cube'] or not source.is_file():raise ValueError('Select an existing DCP or CUBE file')
        if not 1<=len(name.encode('utf-8'))<=63 or any(ord(c)<32 for c in name):raise ValueError('Name needs 1..63 UTF-8 bytes without controls')
        if type(slot) is not int or slot not in range(1,7):raise ValueError('Choose custom slot 1..6')
        model=json.loads(Path(calibration_path).read_text(encoding='utf-8-sig'));calibration.validate(model,Path(source).suffix.lower()=='.dcp')
        # Reject an invalid reference before USB, including prepare-only jobs.
        from .references import DcpLook,Cube
        (DcpLook if source.suffix.lower()=='.dcp' else Cube)(source)
        if source.suffix.lower()=='.cube':
            if not input_space:raise ValueError('CUBE requires --input-space sony-st-srgb, or a named input space plus --bridge. Log LUT input is not Sony ST.')
            if (input_space=='sony-st-srgb')==bool(bridge):raise ValueError('Direct ST CUBE uses no bridge; other CUBE input spaces require --bridge')
            if bridge:Cube(bridge)
        elif input_space is not None or bridge is not None:raise ValueError('DCP uses the ST rendering bridge; CUBE space options do not apply')
        if write and (type(battery) is not int or not 50<=battery<=100):raise ValueError('Actual battery percentage 50..100 is required for writes')
        second=Path(backup_copy).resolve()
        if second==self.root or second in self.root.parents or self.root in second.parents:raise ValueError('Separate original backup locations required')
        for path in [self.root,second]:
            if path.exists() and (not path.is_dir() or any(path.iterdir())):raise ValueError('Use new empty job and backup directories')
        self.root.mkdir(parents=True,exist_ok=True);second.mkdir(parents=True,exist_ok=True)
        self.state={'schema':'a7c2-lut-device-job/1','job_id':uuid.uuid4().hex[:16],'backup_copy':str(second),'name':name,'slot':slot,'journal':[],'backup_files':{},'camera_writes_requested':write}
        self.state['reference_contract']={'input_space':input_space,'bridge':str(Path(bridge).resolve()) if bridge else None}
        self.save('CREATED')
        try:
            raw=self._fit(source,name,slot,model,attribution);self.save('CONVERTED',conversion_table_sha256=firmware.sha(raw))
            with self.factory() as camera:
                self._prepare(camera,name,slot,second,raw)
                if write:self._install(camera)
        except BaseException as exc:
            prior=self.state['phase'];self.save('NEEDS_REVIEW',failed_during=prior,error=str(exc));raise
        return self.state
    @serialized
    def install(self,battery):
        self.load()
        if type(battery) is not int or not 50<=battery<=100:raise ValueError('Actual battery percentage 50..100 required')
        if self.state['phase']!='PREFLIGHT_VERIFIED':raise ValueError('Inspect existing transaction; do not replay')
        try:
            with self.factory(self.state['identity']) as camera:self._install(camera)
        except BaseException as exc:self.save('NEEDS_REVIEW',failed_during=self.state['phase'],error=str(exc));raise
        return self.state
    @serialized
    def verify(self,accept_photos=False):
        self.load()
        if self.state['phase'] not in ['AWAITING_RELOAD','RELOAD_VERIFIED','COMPLETE','RESTORED_AWAITING_RELOAD','RESTORED']:raise ValueError('A completed install/reload preparation is required')
        restore=self.state['phase'] in ['RESTORED_AWAITING_RELOAD','RESTORED']
        prior=self.state['phase']
        self._verify_runtime_ok=False
        try:return self._verify(restore,accept_photos)
        except BaseException as exc:
            if self._verify_runtime_ok:self.record('read_only_verification_rejected',error=str(exc))
            else:self.save('NEEDS_REVIEW',failed_during=prior,error=str(exc))
            raise
    def _verify(self,restore,accept_photos):
        with self.factory(self.state['identity']) as camera:
            runtime=self._invoke(camera,'runtime',0);boot=runtime['boot_id'].encode('ascii')
            self._verify_runtime_ok=True
            if not boot.strip() or firmware.sha(boot)==self.state['reload_before_boot_id_sha256']:raise ValueError('New boot not observed; do not repeat installation')
            programs=self._read_programs(camera,self.state['source_hashes'] if restore else self.state['target_hashes']);self._resource_readback(camera,not restore)
            for span in runtime['spans']:
                expected=programs['appFw.so'][span['offset']:span['offset']+span['length']].hex()
                if span['memory']!=expected or span['disk']!=expected:raise ValueError('Loaded AP spans do not match expected source')
            ram=camera.records(camera.snapshot(True));saved=camera.records(camera.snapshot(False))
            for f in self.state['settings_plan']:
                if ram[0][f['key']].data!=bytes.fromhex(f['before_ram'] if restore else f['after']) or saved[0][f['key']].data!=bytes.fromhex(f['before_saved'] if restore else f['after']):raise ValueError('Reloaded selected recipe differs')
            devicesettings.protected_equal(camera.records((self.root/'source/settings-ram.bin').read_bytes()),ram)
            devicesettings.protected_equal(camera.records((self.root/'source/settings-saved.bin').read_bytes()),saved)
            self.record('postreload_storage_and_settings_verified',boot_id_sha256=firmware.sha(boot),CP_running_memory_directly_read=False)
            if accept_photos and not restore:
                self.record('physical_acceptance_reported_by_user')
                self._verify_runtime_ok=False
                self._invoke(camera,'names',3);self._resource_readback(camera,True)
                self._verify_runtime_ok=True
        self.save(('RESTORED' if restore else 'COMPLETE') if accept_photos else ('RESTORED_AWAITING_RELOAD' if restore else 'RELOAD_VERIFIED'),user_photos_and_preview_confirmed=bool(accept_photos))
        return self.state
    @serialized
    def restore(self,battery):
        self.load()
        if type(battery) is not int or not 50<=battery<=100:raise ValueError('Actual battery percentage 50..100 required')
        if self.state['phase'] not in ['AWAITING_RELOAD','RELOAD_VERIFIED','COMPLETE','PARTIAL_SETTINGS_VERIFIED','PROGRAMS_VERIFIED','NAMES_VERIFIED']:raise ValueError('Unknown/partial transactions need inspection before restoration')
        phase=self.state['phase'];partial=phase in ['PARTIAL_SETTINGS_VERIFIED','PROGRAMS_VERIFIED']
        self.state['active_operation']='restore'
        try:
            with self.factory(self.state['identity']) as camera:
                if phase=='NAMES_VERIFIED':
                    self._read_programs(camera,self.state['source_hashes']);self._resource_readback(camera,True)
                    self.save('NAME_RESTORE_INTENT');self._invoke(camera,'names',2);self._resource_readback(camera,False);self.save('NAMES_RESTORED')
                    self._reload(camera);self.save('RESTORED_AWAITING_RELOAD');return self.state
                self._read_programs(camera,self.state['target_hashes']);self._resource_readback(camera,True)
                self._settings(camera,True,resume=partial);self.save('PROGRAM_RESTORE_INTENT');self._invoke(camera,'program',2);self._read_programs(camera,self.state['source_hashes']);self.save('PROGRAMS_RESTORED')
                self.save('NAME_RESTORE_INTENT');self._invoke(camera,'names',2);self._resource_readback(camera,False);self.save('NAMES_RESTORED')
                self._reload(camera);self.save('RESTORED_AWAITING_RELOAD')
        except BaseException as exc:self.save('NEEDS_REVIEW',failed_during=self.state['phase'],error=str(exc));raise
        return self.state
    @serialized
    def recover(self):
        """Recover evidence, never execute a loader or repeat a write."""
        self.load()
        if self.state['phase']!='NEEDS_REVIEW':return self.state
        if self.state.get('failed_during') in ['SETTINGS_WRITE_INTENT','SETTINGS_RESTORE_INTENT']:
            with self.factory(self.state['identity']) as camera:
                self._read_programs(camera,self.state['target_hashes']);self._resource_readback(camera,True)
                samples=[]
                for _ in range(3):samples.append((camera.records(camera.snapshot(True)),camera.records(camera.snapshot(False))))
                values=[]
                for ram,saved in samples:
                    row=[]
                    for f in self.state['settings_plan']:
                        key=f['key'];a,b=ram[0][key].data,saved[0][key].data
                        if a not in [bytes.fromhex(f['before_ram']),bytes.fromhex(f['after'])] or b not in [bytes.fromhex(f['before_saved']),bytes.fromhex(f['after'])]:raise ValueError('Settings recovery found a value outside this job')
                        row.append((a,b))
                    values.append(row)
                if values[0]!=values[1] or values[1]!=values[2]:raise ValueError('Selected settings still changing; do not write')
                devicesettings.protected_equal(camera.records((self.root/'source/settings-ram.bin').read_bytes()),samples[-1][0])
                for memory,baseline,actual in [(True,'settings-ram.bin',samples[-1][0]),(False,'settings-saved.bin',samples[-1][1])]:
                    expected={f['key']:actual[0][f['key']].data.hex() for f in self.state['settings_plan']}
                    devicesettings.compare(camera.records((self.root/'source'/baseline).read_bytes()),actual,expected,camera.core,self.state['preservation_controls'],memory)
                self.record('stable_partial_settings_observed_without_writes')
                self.save('PARTIAL_SETTINGS_VERIFIED')
            return self.state
        intent=next((event for event in reversed(self.state.get('journal',[])) if event['event']=='native_intent'),None)
        if intent is None:
            self.record('recovery_no_native_intent');return self.state
        result=intent['result'];kind='program' if 'install.result' in result else 'names' if 'names.result' in result else 'wbi' if 'wbi.result' in result else 'runtime' if 'runtime.result' in result else None
        if kind is None:raise ValueError('Inspect unsupported pending native operation without executing')
        mode=intent['mode'];build=self.state.get('program_build' if kind=='program' else 'name_build',{})
        blob_path=self.root/('worker/program/program.so' if kind=='program' else 'worker/names/names.so') if kind in ['program','names'] else nativebuild.ROOT/('src/fl23/assets/'+kind+'.so')
        blob=blob_path.read_bytes()
        if firmware.sha(blob)!=intent['worker_sha256']:raise ValueError('Pending worker differs; preserve original evidence')
        with self.factory(self.state['identity']) as camera:
            raw=camera.temp_read(result,True)
            if raw is None:
                # A clean read-only invocation may have finished before a host
                # verification (e.g. unchanged boot) failed. Never replay it.
                tail=self.state['journal'][self.state['journal'].index(intent)+1:]
                cleaned=any(e['event']=='native_cleanup_verified' and e['stage']==intent['stage'] and e['mode']==mode for e in tail)
                prior=self.state.get('failed_during')
                if cleaned and prior in ['AWAITING_RELOAD','RELOAD_VERIFIED','COMPLETE','RESTORED_AWAITING_RELOAD','RESTORED']:
                    self.record('read_only_check_finished_no_write_replayed');self.save(prior);return self.state
                self.record('pending_result_not_available');return self.state
            self.raw('recovered-'+kind+'-'+str(mode)+'.bin',raw)
            recovered_failure=False
            if kind in ['program','names']:
                try:
                    if kind=='program':worker.validate_worker_report(raw,mode,build['contract'])
                    else:nameworker.validate(raw,mode,build)
                except ValueError:
                    self._known_native_failure(camera,kind,mode,raw,build);recovered_failure=True
            elif kind=='wbi':camera.core.parse_native('wbi',raw,mode)
            else:camera.core.parse_native('runtime',raw)
            if 'source_hashes' in self.state and not recovered_failure:
                before=(kind=='program' and mode in [0,2]) or (kind=='names' and mode!=3) or (self.state.get('active_operation')=='restore' and kind in ['wbi','runtime'])
                # Names preflight occurs before a new program install.
                if kind=='names' and mode==0:before=True
                self._read_programs(camera,self.state['source_hashes'] if before else self.state['target_hashes'])
            if kind=='names' and not recovered_failure:self._resource_readback(camera,mode!=2 and mode!=0)
            expected={intent['stage']:blob,'libJit.so':blob,result:raw}
            if kind=='runtime':
                extra=camera.temp_read('a7c2.probe.result');camera.core.parse_native('probe',extra);expected['a7c2.probe.result']=extra
            else:
                magic=b'A7INS001' if kind=='program' else b'A7NAM001' if kind=='names' else b'A7WBI001'
                expected[result.replace('.result','.request')]=struct.pack('<8sII',magic,mode,0)
            for name,value in expected.items():
                current=camera.temp_read(name,True)
                if current is not None and current!=value:raise ValueError('Unexpected pending contents; recovery will not delete them')
            for name in reversed(list(expected)):
                if camera.temp_read(name,True) is not None:camera.temp_remove(name)
                if camera.temp_read(name,True) is not None:raise ValueError('Recovery cleanup incomplete')
            self.record('existing_result_recovered_without_reexecution',kind=kind,mode=mode)
        if recovered_failure:
            if kind=='program':self.save('NAMES_VERIFIED' if mode==1 else 'SETTINGS_RESTORED')
            elif mode==1:self.save('PREFLIGHT_VERIFIED')
            else:self.save('PARTIAL_NAMES_RESTORE_VERIFIED')
            return self.state
        # Later phases require fresh explicit continuation, never run here.
        if mode==1 and kind=='program':self.save('PROGRAMS_VERIFIED')
        elif mode==1 and kind=='names':self.save('NAMES_VERIFIED')
        elif mode==2:self.save('PROGRAMS_RESTORED' if kind=='program' else 'NAMES_RESTORED')
        elif mode==1 and kind=='wbi':
            self.save('RESTORED_AWAITING_RELOAD' if self.state.get('active_operation')=='restore' else 'AWAITING_RELOAD')
        elif mode==3 and kind=='names':
            accepted=any(e['event']=='physical_acceptance_reported_by_user' for e in self.state['journal'])
            self.save('COMPLETE' if accepted else 'RELOAD_VERIFIED',user_photos_and_preview_confirmed=accepted)
        elif kind=='runtime':
            prior=self.state.get('failed_during')
            if prior in ['AWAITING_RELOAD','RELOAD_VERIFIED','COMPLETE','RESTORED_AWAITING_RELOAD','RESTORED']:self.save(prior)
            elif prior in ['SETTINGS_VERIFIED','SETTINGS_RESTORED','PROGRAMS_RESTORED','NAMES_RESTORED']:self.save(prior)
        return self.state
    @serialized
    def resume(self,battery):
        self.load()
        if type(battery) is not int or not 50<=battery<=100:raise ValueError('Actual battery percentage 50..100 required')
        if self.state['phase'] not in ['PROGRAMS_VERIFIED','NAMES_VERIFIED','SETTINGS_VERIFIED','PARTIAL_SETTINGS_VERIFIED','SETTINGS_RESTORED','PROGRAMS_RESTORED','NAMES_RESTORED','PARTIAL_NAMES_RESTORE_VERIFIED']:
            raise ValueError('Recover the existing result first; unknown/partial settings cannot be replayed')
        try:
            with self.factory(self.state['identity']) as camera:
                if self.state.get('active_operation')=='restore':
                    self._resume_restore(camera);return self.state
                if self.state['phase']=='NAMES_VERIFIED':
                    self._read_programs(camera,self.state['source_hashes']);self._resource_readback(camera,True)
                    self.save('PROGRAM_WRITE_INTENT');self._invoke(camera,'program',1);self._read_programs(camera,self.state['target_hashes']);self.save('PROGRAMS_VERIFIED')
                else:self._read_programs(camera,self.state['target_hashes'])
                if self.state['phase'] in ['PROGRAMS_VERIFIED','PARTIAL_SETTINGS_VERIFIED']:self._settings(camera,resume=self.state['phase']=='PARTIAL_SETTINGS_VERIFIED')
                self._reload(camera)
        except BaseException as exc:self.save('NEEDS_REVIEW',failed_during=self.state['phase'],error=str(exc));raise
        return self.state
    def _resume_restore(self,camera):
        phase=self.state['phase']
        if phase in ['PARTIAL_SETTINGS_VERIFIED','SETTINGS_RESTORED']:
            self._read_programs(camera,self.state['target_hashes']);self._resource_readback(camera,True)
            if phase=='PARTIAL_SETTINGS_VERIFIED':self._settings(camera,True,resume=True)
            self.save('PROGRAM_RESTORE_INTENT');self._invoke(camera,'program',2);self._read_programs(camera,self.state['source_hashes']);self.save('PROGRAMS_RESTORED')
        if self.state['phase'] in ['PROGRAMS_RESTORED','PARTIAL_NAMES_RESTORE_VERIFIED']:
            self._read_programs(camera,self.state['source_hashes'])
            if self.state['phase']=='PROGRAMS_RESTORED':self._resource_readback(camera,True)
            self.save('NAME_RESTORE_INTENT');self._invoke(camera,'names',2);self._resource_readback(camera,False);self.save('NAMES_RESTORED')
        if self.state['phase']!='NAMES_RESTORED':raise ValueError('No proven remaining restoration phase')
        self._read_programs(camera,self.state['source_hashes']);self._resource_readback(camera,False)
        self._reload(camera);self.save('RESTORED_AWAITING_RELOAD')
    def _known_native_failure(self,camera,kind,mode,raw,build):
        """A failed, authenticated report is different from an unknown outcome.

        Advance only after full source/target classification. Recovery itself
        performs no loader invocation; a later explicit resume is required.
        """
        if mode not in [1,2]:raise ValueError('A failed preflight requires inspection')
        if kind=='program':
            if len(raw)!=240:raise ValueError('Unknown failed program ABI')
            v=worker.REPORT.unpack_from(raw)
            if v[:3]!=(b'A7IRP001',1,mode) or v[5]>=0 or any(v[i] for i in [6,8,9,10]):raise ValueError('Unverified program rollback/read-only state')
            self._read_programs(camera,self.state['source_hashes'] if mode==1 else self.state['target_hashes'])
            self._resource_readback(camera,True)
        else:
            if len(raw)!=nameworker.REPORT.size:raise ValueError('Unknown failed names ABI')
            v=nameworker.REPORT.unpack(raw)
            if v[:3]!=(b'A7NMR001',1,mode) or v[4]!=build['count'] or v[5]>=0 or any(v[i] for i in [6,8,9,10]):raise ValueError('Unverified resource rollback/read-only state')
            wanted=build['AP']
            if v[18].hex()!=wanted:raise ValueError('Failed names report AP differs')
            self._read_programs(camera,self.state['source_hashes'])
            classes=[]
            for spec in build['files']:
                blob=camera.read('/usr/share/app/'+spec['file']);digest=firmware.sha(blob)
                candidates=['before'] if mode==1 else ['before','after']
                which=next((k for k in candidates if len(blob)==spec[k+'_bytes'] and digest==spec[k+'_sha256']),None)
                if which is None:raise ValueError('Failed resource outcome is outside this job')
                classes.append(which)
            self.record('known_resource_failure_classified',files=classes)
        self.record('known_native_failure_verified_without_reexecution',kind=kind,mode=mode)
