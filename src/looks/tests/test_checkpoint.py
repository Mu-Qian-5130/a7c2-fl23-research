"""Initial checkpoint restoration across multiple later LUT edits. No USB."""
import copy
import hashlib
import json
from pathlib import Path
import re
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from looktool import checkpoint,checkpointworker,checkpointjob,firmware,nameworker,resources
from test_device_components import resource_fixture
from test_device_job import Prop,core

BODY={'model':'ILCE-7CM2','serial_sha256':hashlib.sha256(b'01020304').hexdigest()}
KEYS=[*checkpoint.AP_KEYS,*range(0x02cf2000,0x02cf2036)]

def stock_names():
    count=2860
    raw=bytearray(b'uxc\x07\0\0\0\0'+struct.pack('<HHI',8,5,count|(count<<12))+b'\xff\xff'*count)
    struct.pack_into('<H',raw,16,0);raw.extend(struct.pack('<I',0x1e00a000)+b'Native\0\0')
    return bytes(raw)

def values(resource=None):
    props=[{str(k):['00',0] for k in KEYS},{str(k):['0102',0] for k in checkpoint.CP_KEYS}]
    props[0][str(0x00e70003)]=['01020304',2]
    raw=json.dumps(props).encode()
    return {'appFw.so':bytes(40000),'cpapp-b.bin':bytes(40000),
        'settings-ram.bin':raw,'settings-saved.bin':raw,
        **{'resources/'+n:resource or stock_names() for n in nameworker.filenames()}}

def records(raw):return [{int(k):Prop(bytes.fromhex(v[0]),v[1]) for k,v in p.items()} for p in json.loads(raw)]

class Camera:
    def __init__(self,initial):
        self.identity=dict(BODY);self.core=core;self.files={}
        for n,p in checkpoint.PROGRAM_PATHS.items():self.files[p]=initial[n]
        for n in nameworker.filenames():self.files['/usr/share/app/'+n]=initial['resources/'+n]
        self.ram=records(initial['settings-ram.bin']);self.saved=records(initial['settings-saved.bin'])
        self.mode='2\n';self.saves=[];self.native_calls=[]
        self.link=SimpleNamespace(cp_read=lambda k:self.ram[1][k].data,cp_write=lambda k,v:self._set(1,k,v),
            call=lambda f,*a:f(*a),camera=SimpleNamespace(saveBackup=self.save_group))
    def _set(self,chip,key,value):self.ram[chip][key]=Prop(value,self.ram[chip][key].attr)
    def __call__(self,expected=None):checkpoint.same_body(self.identity,expected);return self
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def read(self,path,missing=False):return self.files.get(path)
    def temp_read(self,name,missing=False):return self.files.get('/tmp/jiritsu/'+name)
    def temp_remove(self,name):self.files.pop('/tmp/jiritsu/'+name,None)
    def snapshot(self,memory):
        return json.dumps([{str(k):[v.data.hex(),v.attr] for k,v in p.items()} for p in (self.ram if memory else self.saved)]).encode()
    records=staticmethod(records)
    def property_read(self,k):return self.ram[0][k].data
    def property_write(self,k,v,allowed):
        if k not in allowed:raise AssertionError('Unselected write')
        self._set(0,k,v)
    def save_group(self,group):
        self.saves.append(group);chip=int(group==0x02a4)
        for k,v in self.ram[chip].items():
            if k>>16==group:self.saved[chip][k]=v

def fake_compile(source,header,destination,zig=None,**kw):
    Path(destination).write_bytes(b'simulated-worker')

class SimRollback(checkpointjob.Rollback):
    lose_after_program=False
    corrupt_name=False
    def native(self,camera,kind,mode,build=None):
        camera.native_calls.append((kind,mode));self.record('simulated_native',kind=kind,mode=mode)
        if kind=='purge':
            stale=[p for p in camera.files if p.startswith('/usr/share/app/.a7c2-')]
            for p in stale:camera.files.pop(p)
            return {'mode':5,'matched':len(stale),'removed':len(stale)}
        if kind=='runtime':
            return {'image_mode':camera.mode,'spans':[{'offset':0,'length':16,'memory':camera.files['/usr/lib/appFw.so'][:16].hex(),'disk':camera.files['/usr/lib/appFw.so'][:16].hex()}]}
        if kind=='wbi':
            if mode:camera.mode='0\n'
            return {}
        if kind=='program':
            text=Path(build['path']).with_suffix('.private.h').read_text()
            for at,length,chip,index in re.findall(r'\{(\d+)UL,(\d+),(\d+),old_(\d+),new_\d+\}',text):
                name=list(checkpoint.PROGRAM_PATHS)[int(chip)];path=checkpoint.PROGRAM_PATHS[name];at=int(at);length=int(length)
                parse=lambda label:bytes(map(int,re.search(label+'_'+index+r'\[\]=\{([^}]*)\}',text)[1].split(',')))
                old,new=parse('old'),parse('new')
                if camera.files[path][at:at+length]!=old:raise ValueError('Stale native byte window')
                if mode:camera.files[path]=camera.files[path][:at]+new+camera.files[path][at+length:]
            if mode and self.lose_after_program:raise TimeoutError('simulated lost completion')
        if kind=='names' and mode==2:
            _,target=checkpoint.read(self.root/'target.private.zip')
            for n in build['files']:camera.files['/usr/share/app/'+n]=target['resources/'+n]
            if self.corrupt_name:camera.files['/usr/share/app/'+build['files'][0]]+=b'bad'
        return {}

class CheckpointTests(unittest.TestCase):
    def test_native_program_report_uses_status_and_byte_counts_not_hashes(self):
        from looktool.worker import REPORT
        build={'windows':3,'sizes':[123,456]}
        raw=REPORT.pack(b'A7IRP001',1,1,9,3,0,0,0,0,0,0,42,11,12,123,456)+bytes(128)
        self.assertEqual(checkpointworker.program_report(raw,1,build)['windows'],3)
        broken=bytearray(raw);struct.pack_into('<q',broken,24,-5)
        with self.assertRaises(ValueError):checkpointworker.program_report(bytes(broken),1,build)
        with self.assertRaises(ValueError):checkpointworker.program_report(raw,0,build)
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.original=values();self.archive=self.root/'backup2/checkpoint.private.zip'
        checkpoint.write(self.archive,self.original,BODY,provenance={'type':'test-initial'})
        self.compiler=patch.object(checkpointworker,'compile_worker',side_effect=fake_compile);self.compiler.start();self.addCleanup(self.compiler.stop)
        self.keys=patch.object(checkpoint,'recipe_keys',return_value=KEYS);self.keys.start();self.addCleanup(self.keys.stop)
    def camera_after_updates(self):
        c=Camera(self.original)
        for n,p in checkpoint.PROGRAM_PATHS.items():
            data=bytearray(c.files[p]);data[0:100]=bytes([3])*100;data[10000:22000]=bytes([4])*12000;c.files[p]=bytes(data)
        for n in nameworker.filenames():
            path='/usr/share/app/'+n
            for names in [{1:'CC',5:'GR Positive'},{2:'NC'},{5:'Astia',6:'GR Negative'}]:c.files[path]=resources.rename(c.files[path],names)[0]
        for k in KEYS:c._set(0,k,b'\x09')
        for k in checkpoint.CP_KEYS:c._set(1,k,b'\x08\x08')
        c.ram[0][0x02cf3000]=Prop(b'unrelated-latest',0);c.saved=copy.deepcopy(c.ram)
        return c
    def test_multiple_lut_updates_one_complete_rollback_without_hash_gate(self):
        c=self.camera_after_updates();job=SimRollback(self.root/'rollback',factory=c)
        with patch.object(firmware,'sha',side_effect=AssertionError('No SHA admission')):
            state=job.run(self.archive.parent,100,'2.01')
            self.assertEqual(state['phase'],'RESTORED_AWAITING_RELOAD')
            self.assertEqual(job.verify(True)['phase'],'COMPLETE')
        for n,p in checkpoint.PROGRAM_PATHS.items():self.assertEqual(c.files[p],self.original[n])
        for n in nameworker.filenames():self.assertEqual(c.files['/usr/share/app/'+n],self.original['resources/'+n])
        self.assertTrue(all(c.property_read(k)==b'\0' for k in KEYS))
        self.assertEqual(c.property_read(0x02cf3000),b'unrelated-latest')
        # Both old and initial checkpoints remain independently readable.
        _,before=checkpoint.read(job.root/'before.private.zip');self.assertNotEqual(before['cpapp-b.bin'],self.original['cpapp-b.bin'])
        self.assertEqual(checkpoint.read(self.archive)[1],self.original)
        self.assertGreater(len(state['programs']),1)
    def test_preflight_error_writes_nothing(self):
        c=self.camera_after_updates();old=copy.deepcopy(c.files)
        path='/usr/share/app/'+nameworker.filenames()[0]
        changed=bytearray(c.files[path]);changed[-4:]=b'\0'*4;c.files[path]=bytes(changed)
        # Make a non-reconstructable native record change, rather than a name
        # append (which can be removed by truncation).
        at=16+2*2866;data=bytearray(c.files[path]);data[at+4]^=1;c.files[path]=bytes(data)
        before=copy.deepcopy(c.files);job=SimRollback(self.root/'bad',factory=c)
        with self.assertRaises(ValueError):job.run(self.archive,100,'2.01')
        self.assertEqual(c.files,before);self.assertEqual(c.saves,[]);self.assertEqual(c.native_calls,[])
    def test_unknown_program_result_stops_without_names_or_settings(self):
        c=self.camera_after_updates();job=SimRollback(self.root/'unknown',factory=c);job.lose_after_program=True
        with self.assertRaises(TimeoutError):job.run(self.archive,100,'2.01')
        self.assertEqual(job.state['phase'],'NEEDS_REVIEW');self.assertEqual(c.saves,[])
        self.assertNotIn(('names',2),c.native_calls)
        with self.assertRaises(ValueError):job.run(self.archive,100,'2.01')
    def test_readback_mismatch_stops_before_settings(self):
        c=self.camera_after_updates();job=SimRollback(self.root/'bad-readback',factory=c);job.corrupt_name=True
        with self.assertRaisesRegex(ValueError,'name readback'):job.run(self.archive,100,'2.01')
        self.assertEqual(c.saves,[]);self.assertEqual(job.state['phase'],'NEEDS_REVIEW')
    def test_mode_zero_does_not_repeat_retained_image_drop(self):
        c=self.camera_after_updates();c.mode='0\n';job=SimRollback(self.root/'zero',factory=c)
        job.run(self.archive,100,'2.01');self.assertFalse(any(k=='wbi' for k,m in c.native_calls))
    def test_unchanged_saved_look_fields_need_no_group_save_or_unsaved_gate(self):
        c=self.camera_after_updates();original=records(self.original['settings-saved.bin'])
        for chip,selected in [(0,KEYS),(1,checkpoint.CP_KEYS)]:
            for k in selected:c.ram[chip][k]=c.saved[chip][k]=original[chip][k]
        c.ram[0][0x02cf3000]=Prop(b'unrelated-unsaved',0)
        SimRollback(self.root/'no-extra-save',factory=c).run(self.archive,100,'2.01')
        self.assertEqual(c.saves,[])
        self.assertEqual(c.ram[0][0x02cf3000].data,b'unrelated-unsaved')
        self.assertEqual(c.saved[0][0x02cf3000].data,b'unrelated-latest')
    def test_existing_initial_archive_is_never_overwritten(self):
        with self.assertRaises(ValueError):checkpoint.write(self.archive,values(resource_fixture()),BODY,provenance={})
        self.assertEqual(checkpoint.read(self.archive)[1],self.original)
    def test_wrong_body_version_or_power_stops_before_camera(self):
        job=SimRollback(self.root/'stop')
        with patch.object(job,'factory') as factory:
            for battery,version in [(20,'2.01'),(100,'3.00')]:
                with self.assertRaises(ValueError):job.run(self.archive,battery,version)
            factory.assert_not_called()
        c=self.camera_after_updates();c.identity['serial_sha256']='another-body'
        job=SimRollback(self.root/'wrongbody',factory=c)
        with self.assertRaisesRegex(ValueError,'different body'):job.run(self.archive,100,'2.01')
        self.assertEqual(c.native_calls,[])
    def test_global_name_inverse_stock_and_preexisting_named_checkpoint(self):
        for initial in [stock_names(),resource_fixture()]:
            current=initial
            for slot in (1,2,5,6,5,1):current=resources.rename(current,{slot:'Latest '+str(slot)})[0]
            self.assertEqual(resources.inverse(current,checkpoint.name_inverse(initial,current)),initial)
    def legacy_folder(self):
        folder=self.root/'original-backup2';folder.mkdir()
        for name in checkpoint.PROGRAM_PATHS:(folder/(name+'.bin')).write_bytes(self.original[name])
        (folder/'backup.private.bin').write_bytes(self.original['settings-ram.bin'])
        return folder
    def test_original_fl23_backup_alone_restores_after_multiple_luts(self):
        backup=self.legacy_folder();c=self.camera_after_updates()
        # No original workspace, LUT jobs or checkpoint ZIP exist.
        job=SimRollback(self.root/'legacy-restore',factory=c)
        with patch('looktool.devicesession.modules',return_value=(None,SimpleNamespace(backup_records=records))):
            state=job.run(backup,100,'2.01')
        self.assertEqual(state['phase'],'RESTORED_AWAITING_RELOAD')
        self.assertEqual(job.verify(True)['phase'],'COMPLETE')
        _,target=checkpoint.read(job.root/'target.private.zip')
        self.assertEqual(target,self.original)
        self.assertFalse((backup/'checkpoint.private.zip').exists())
        self.assertEqual(set(p.name for p in backup.iterdir()),{'appFw.so.bin','cpapp-b.bin.bin','backup.private.bin'})
        self.assertIn('legacy_fl23_target_completed_without_lut_job',[r['event'] for r in state['journal']])
    def test_original_fl23_backup_alone_also_restores_without_lut_installation(self):
        backup=self.legacy_folder();c=Camera(self.original)
        c.files['/usr/lib/appFw.so']=bytes([1])*len(self.original['appFw.so'])
        job=SimRollback(self.root/'legacy-only-fl23',factory=c)
        with patch('looktool.devicesession.modules',return_value=(None,SimpleNamespace(backup_records=records))):
            job.run(backup,100,'2.01')
        self.assertEqual(c.files['/usr/lib/appFw.so'],self.original['appFw.so'])
        self.assertFalse(any(kind=='names' for kind,mode in c.native_calls))
    def test_legacy_uses_its_own_serial_and_preserves_missing_flash_limitation(self):
        backup=self.legacy_folder()
        with patch('looktool.devicesession.modules',return_value=(None,SimpleNamespace(backup_records=records))):
            manifest,source=checkpoint.load_target(backup)
        self.assertEqual(manifest['identity'],BODY)
        self.assertIn('not saved',manifest['limitations'][0])
        self.assertEqual(source['settings-ram.bin'],self.original['settings-ram.bin'])
    def test_resource_native_records_reconstruct_without_historical_name_job(self):
        source=stock_names();current=source
        for slot in (1,2,3,4,5,6,1,5):current=resources.rename(current,{slot:'Look '+str(slot)})[0]
        self.assertEqual(resources.before_custom(current),source)
        self.assertEqual(resources.before_custom(source),source)

if __name__=='__main__':unittest.main()
