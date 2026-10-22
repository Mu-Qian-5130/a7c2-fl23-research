"""Both install orders, native slot undo and current FL23 verification. No USB."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from looktool import device_layout,firmware,nameworker,nativebuild,resources,six
import test_device_job as f

FIXTURES=os.environ.get('A7C2_RESEARCH_FIXTURES')

@unittest.skipUnless(FIXTURES,'Needs private original firmware and program fixtures')
class InstallOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        index=Path(FIXTURES);cls.research=index.parents[2]
        folder=cls.research/'firmware/a7c2-2.01/components'
        cls.ap=(folder/'appFw.so').read_bytes();cls.cp=(folder/'cpapp-b.bin').read_bytes()
        runtime=f.ROOT/('src/camera_runtime' if (f.ROOT/'src/camera_runtime').is_dir() else 'src/fl23')
        sys.path.insert(0,str(runtime))
        import core,compat
        cls.core,cls.compat=core,compat
    def test_fl23_then_lut_and_lut_then_fl23_produce_same_programs(self):
        raw=bytes([1])*1215
        _,_,fl23,_,_=self.compat.plan(self.ap,self.cp,transitions=False)
        _,_,first=device_layout.replace(fl23['appFw.so'],fl23['cpapp-b.bin'],{5:raw})
        _,_,lut=device_layout.replace(self.ap,self.cp,{5:raw})
        _,_,second,_,_=self.compat.plan(lut['appFw.so'],lut['cpapp-b.bin'],transitions=False)
        self.assertEqual(first,second)
        self.assertTrue(self.compat.plan(first['appFw.so'],first['cpapp-b.bin'],transitions=False)[1])
        self.assertEqual(six.read_tables(first['cpapp-b.bin'])[4],raw)
        self.assertEqual(device_layout.identify(first['appFw.so'],first['cpapp-b.bin'])['mask'],16)
    def test_last_native_slot_undo_keeps_fl23_and_can_import_again(self):
        old=device_layout.before_first_table(self.ap,self.cp,5)
        _,_,lut=device_layout.replace(self.ap,self.cp,{5:bytes([1])*1215})
        _,_,both,_,_=self.compat.plan(lut['appFw.so'],lut['cpapp-b.bin'],transitions=False)
        forward,reverse,after=device_layout.deactivate(both['appFw.so'],both['cpapp-b.bin'],5,old)
        self.assertEqual(firmware.apply(after,reverse),both)
        self.assertEqual(device_layout.identify(after['appFw.so'],after['cpapp-b.bin'])['mask'],0)
        self.assertTrue(self.compat.plan(after['appFw.so'],after['cpapp-b.bin'],transitions=False)[1])
        _,_,again=device_layout.replace(after['appFw.so'],after['cpapp-b.bin'],{6:bytes([2])*1215})
        self.assertEqual(device_layout.identify(again['appFw.so'],again['cpapp-b.bin'])['mask'],32)
    def test_fl23_verify_accepts_a_later_lut_install_without_old_output_hash(self):
        import app
        from types import SimpleNamespace
        _,_,fl23,_,_=self.compat.plan(self.ap,self.cp,transitions=False)
        _,_,later=device_layout.replace(fl23['appFw.so'],fl23['cpapp-b.bin'],{5:bytes([1])*1215})
        a,b=bytes(8192),bytes(28672);merged=self.core.merge_colors(a,b)
        saved=[{k:f.Prop(bytes([10+i]),0) for i,k in enumerate(self.core.AP_KEYS)},
            {k:f.Prop(v,0) for k,v in zip(self.core.CP_KEYS,merged)}]
        class S:
            camera=SimpleNamespace(getBackupPresetData=lambda memory:b'synthetic-snapshot')
            def __init__(self,expected):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def call(self,method,*args):return method(*args)
            def read(self,path):return later['appFw.so'] if path.endswith('appFw.so') else later['cpapp-b.bin']
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'original').mkdir()
            for name,raw in [('unit-02a40001.bin',a),('unit-02a4000d.bin',b)]:
                (root/'original'/name).write_bytes(raw)
            self.core.save_json(root/'state.json',{'identity':{'model':'ILCE-7CM2'},'version':'2.01','journal':[]})
            job=app.Job(root)
            def load():job.state=self.core.read_json(root/'state.json');return job
            at=0x3528804;expected=later['appFw.so'][at:at+112].hex()
            with patch.object(job,'load',side_effect=load),patch('transport.Session',S),patch.object(self.core,'backup_records',return_value=saved),patch.object(job,'module',return_value={'spans':[{'offset':at,'length':112,'memory':expected,'disk':expected}]}):
                job.verify()
            self.assertEqual(job.state['journal'][-1]['step'],'post_restart_files_and_targets_verified')
    def test_lut_verify_accepts_later_fl23_and_retargets_pending_name_cleanup(self):
        from looktool import devicesettings
        from test_checkpoint import stock_names
        camera=f.SimCamera(self.ap,self.cp)
        for k in self.core.AP_KEYS:camera.properties[k]=f.Prop(b'\0',0)
        a,b=bytes(8192),bytes(28672)
        for k,v in zip(self.core.CP_KEYS,(a,b)):camera.cp[k]=f.Prop(v,0)
        camera.saved=copy.deepcopy(camera.properties)
        sources={'appFw.so':self.ap,'cpapp-b.bin':self.cp,'settings-ram.bin':camera.snapshot(True),'settings-saved.bin':camera.snapshot(False)}
        for n in nameworker.filenames():sources['resources/'+n]=stock_names()
        fields=devicesettings.plan(self.ap,camera.records(sources['settings-ram.bin']),camera.records(sources['settings-saved.bin']),[5])
        forward,_,lut=device_layout.replace(self.ap,self.cp,{5:bytes([1])*1215})
        _,_,both,_,_=self.compat.plan(lut['appFw.so'],lut['cpapp-b.bin'],transitions=False)
        for n,p in f.devicejob.PROGRAM_PATHS.items():camera.files[p]=both[n]
        specs=[];labels=list(range(0x0200ab2c,0x0200ab32))
        for n in nameworker.filenames():
            before=sources['resources/'+n];after,inverse=resources.rename(before,{5:'Kept LUT'},labels)
            camera.files['/usr/share/app/'+n]=after
            specs.append({'file':n,'before_bytes':len(before),'after_bytes':len(after),'before_sha256':firmware.sha(before),'after_sha256':firmware.sha(after),'inverse':inverse})
        for field in fields:camera.properties[field['key']]=f.Prop(bytes.fromhex(field['after']),0)
        for i,k in enumerate(self.core.AP_KEYS):camera.properties[k]=f.Prop(bytes([10+i]),0)
        for k,v in zip(self.core.CP_KEYS,self.core.merge_colors(a,b)):camera.cp[k]=f.Prop(v,0)
        camera.saved=copy.deepcopy(camera.properties);old_boot=camera.boot;camera.reboot()
        with tempfile.TemporaryDirectory() as folder:
            job=f.SimJob(Path(folder)/'verify',factory=camera);job.root.mkdir()
            f.devicejob.write_json(job.root/'transition/forward.private.json',forward)
            job.state={'schema':'a7c2-lut-device-job/1','phase':'AWAITING_RELOAD','identity':camera.identity,
                'slot':5,'name':'Kept LUT','job_id':'0123456789abcdef','journal':[],
                'source_hashes':{n:firmware.sha(sources[n]) for n in f.devicejob.PROGRAM_PATHS},
                'target_hashes':{n:firmware.sha(lut[n]) for n in f.devicejob.PROGRAM_PATHS},
                'settings_plan':fields,'layout':{'label_ids':labels},
                'name_build':{'files':specs,'count':68,'AP':firmware.sha(self.ap),'target_AP':firmware.sha(lut['appFw.so'])},
                'reload_before_boot_id_sha256':firmware.sha(old_boot.encode())}
            with patch.object(job,'load',return_value=job),patch.object(job,'source',side_effect=lambda n:sources[n]),patch.object(nameworker,'prepare',side_effect=f.fake_names):
                self.assertEqual(job.verify(True)['phase'],'COMPLETE')
            self.assertEqual(job.state['name_build']['target_AP'],firmware.sha(both['appFw.so']))
            self.assertIn('name_cleanup_retargeted_after_native_fl23',[r['event'] for r in job.state['journal']])
    def test_real_native_resources_reconstruct_without_lut_jobs(self):
        folder=self.research/'research/fuji-feasibility/menu-resource-research/all-layout-sources'
        for name in nameworker.filenames():
            before=(folder/name).read_bytes();after=before
            for slot in (1,2,3,4,5,6,5,1):after=resources.rename(after,{slot:'New '+str(slot)})[0]
            self.assertEqual(resources.before_custom(after),before,name)
    def test_first_slot_undo_after_fl23_and_another_slot_preserves_both(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);camera=f.SimCamera(self.ap,self.cp)
            for k,n in zip(self.core.CP_KEYS,(8192,28672)):camera.cp[k]=f.Prop(bytes(n),0)
            reference=root/'look.cube';reference.write_text('LUT_3D_SIZE 2\n'+'\n'.join(f'{r} {g} {b}' for b in (0,1) for g in (0,1) for r in (0,1)))
            model=root/'model.json';model.write_text(json.dumps({'schema':'a7c2-look-calibration/1','coordinate_model':'bt601-limited-provisional','response_matrix':[[1,0,0],[0,1,0],[0,0,1]],'evidence':'SYNTHETIC TEST ONLY'}))
            original_properties=copy.deepcopy(camera.properties)
            with patch.object(nativebuild,'build_program',side_effect=f.fake_program),patch.object(nameworker,'prepare',side_effect=f.fake_names):
                first=f.SimJob(root/'first',factory=camera)
                first.create(reference,'First five',5,model,root/'backup-first',write=True,battery=90,input_space='sony-st-srgb')
                camera.reboot();first.verify(True)
                _,_,both,_,_=self.compat.plan(camera.files['/usr/lib/appFw.so'],camera.files['/cp/cpapp-b.bin'],transitions=False)
                for n,p in f.devicejob.PROGRAM_PATHS.items():camera.files[p]=both[n]
                merged=self.core.merge_colors(*(camera.cp[k].data for k in self.core.CP_KEYS))
                for k,value in zip(self.core.CP_KEYS,merged):camera.cp[k]=f.Prop(value,0)
                camera.reboot()
                self.assertEqual(first.verify(True)['phase'],'COMPLETE')
                second=f.SimJob(root/'second',factory=camera);second.table=bytes([2])*1215
                second.create(reference,'Six kept',6,model,root/'backup-second',write=True,battery=90,input_space='sony-st-srgb')
                camera.reboot();second.verify(True)
                before=copy.deepcopy(camera.properties);before_tables=six.read_tables(camera.files['/cp/cpapp-b.bin'])
                undo=f.SimJob(root/'undo',factory=camera)
                undo.restore_slot(first,90,root/'backup-undo')
                ap,cp=camera.files['/usr/lib/appFw.so'],camera.files['/cp/cpapp-b.bin']
                self.assertEqual(device_layout.identify(ap,cp)['mask'],32)
                self.assertTrue(self.compat.plan(ap,cp,transitions=False)[1])
                selected={field['key'] for field in first.state['settings_plan']}
                self.assertEqual({k:v for k,v in camera.properties.items() if k in selected},{k:v for k,v in original_properties.items() if k in selected})
                self.assertEqual({k:v for k,v in camera.properties.items() if k not in selected},{k:v for k,v in before.items() if k not in selected})
                self.assertEqual(six.read_tables(cp)[5],before_tables[5])
                camera.reboot();self.assertEqual(undo.verify(True)['phase'],'COMPLETE')

if __name__=='__main__':unittest.main()
