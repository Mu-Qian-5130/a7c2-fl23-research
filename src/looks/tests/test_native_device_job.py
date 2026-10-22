"""Real program/settings fixtures, simulated transport; no camera evidence."""
import copy,json,os,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from looktool import devicejob,device_layout,firmware,lookfile,nameworker,nativebuild,photobasis,photoio,six
import test_device_job as fixtures


class NativeJob(fixtures.SimJob):
    _fit=devicejob.Job._fit


@unittest.skipUnless(os.environ.get('A7C2_RESEARCH_FIXTURES') and os.environ.get('A7C2_NATIVE_CHECKPOINT'),
                     'Needs private program and body-settings fixtures')
class NativeDeviceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        index=Path(os.environ['A7C2_RESEARCH_FIXTURES']);files=json.loads(index.read_text())
        cls.ap=(index.parent/files['six_ap']).read_bytes();cls.cp=(index.parent/files['v4_cp']).read_bytes()
        with zipfile.ZipFile(os.environ['A7C2_NATIVE_CHECKPOINT']) as archive:
            cls.settings=archive.read('settings-ram.bin')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.camera=fixtures.SimCamera(self.ap,self.cp)
        self.camera.cp=copy.deepcopy(fixtures.core.backup_records(self.settings)[1])
        self.bank=devicejob.Job(self.root/'unused')._native_bank(self.cp,self.camera.snapshot(True),self.camera)
        self.source=self.root/'look.a7look';self.table=bytes([2])*1215
        delta=photobasis.pack(self.bank,tone=[32,0,0])[1]
        lookfile.write(self.source,'Astia',self.table,method='fixture-test',attribution='Test',native_photo=delta)
        for target,name,helper in [(nativebuild,'build_program',fixtures.fake_program),(nameworker,'prepare',fixtures.fake_names)]:
            p=patch.object(target,name,side_effect=helper);p.start();self.addCleanup(p.stop)

    def create(self,number,slot,source=None,name='Astia',write=True):
        job=NativeJob(self.root/('job'+str(number)),factory=self.camera)
        job.create(source or self.source,name,slot,None,self.root/('backup'+str(number)),write=write,battery=90)
        return job

    def accepted(self,job):
        self.camera.reboot();self.assertEqual(job.verify(True)['phase'],'COMPLETE')

    def test_four_stages_prepare_install_reload_and_acceptance(self):
        before=copy.deepcopy(self.camera.properties)
        job=self.create(1,4)
        self.assertEqual(job.state['phase'],'AWAITING_RELOAD')
        self.assertTrue(job.state['byte_checks'])
        self.assertEqual(photoio.inspect(self.camera.files['/cp/cpapp-b.bin'])['mask'],8)
        self.assertEqual(self.camera.files['/usr/lib/appFw.so'],self.ap)
        self.assertEqual(device_layout.tables(self.camera.files['/cp/cpapp-b.bin'])[3],self.table)
        self.assertTrue(all(value==before[key] for key,value in self.camera.properties.items()
            if key not in {field['key'] for field in job.state['settings_plan']}))
        self.accepted(job)

    def test_restore_one_native_slot_keeps_later_other_native_slot(self):
        original=self.create(1,4);self.accepted(original)
        newer=self.create(2,5,name='Five');self.accepted(newer)
        before=self.camera.files['/cp/cpapp-b.bin'];five=photoio.slot_bytes(before,5)
        undo=NativeJob(self.root/'undo4',factory=self.camera)
        undo.restore_slot(original,90,self.root/'backup-undo4')
        cp=self.camera.files['/cp/cpapp-b.bin']
        self.assertIsNone(photoio.slot_bytes(cp,4));self.assertEqual(photoio.slot_bytes(cp,5),five)
        self.assertEqual(device_layout.tables(cp)[3],device_layout.tables(self.cp)[3])
        self.assertEqual(device_layout.tables(cp)[4],self.table)
        self.assertEqual(self.camera.files['/usr/lib/appFw.so'],self.ap)
        self.accepted(undo)

    def test_restore_rejects_later_native_change_even_with_same_table_and_name(self):
        first=self.create(1,4);self.accepted(first)
        path=self.root/'new.a7look';delta=photobasis.pack(self.bank,tone=[64,0,0])[1]
        lookfile.write(path,'Astia',self.table,method='test',attribution='Test',native_photo=delta)
        newer=self.create(2,4,path);self.accepted(newer)
        before=dict(self.camera.files)
        undo=NativeJob(self.root/'undo',factory=self.camera)
        with self.assertRaisesRegex(ValueError,'native stages were changed later'):
            undo.restore_slot(first,90,self.root/'backup-undo')
        self.assertEqual(self.camera.files,before)
        self.assertFalse(any(row['event']=='simulated_native_call' for row in undo.state['journal']))

    def test_unknown_program_result_does_not_repeat_or_write_settings(self):
        job=NativeJob(self.root/'failed',factory=self.camera);job.fail_after_program=True
        before=copy.deepcopy(self.camera.properties)
        with self.assertRaises(TimeoutError):
            job.create(self.source,'Astia',4,None,self.root/'failed-backup',write=True,battery=90)
        self.assertEqual(job.state['phase'],'NEEDS_REVIEW')
        calls=[row['kind'] for row in job.state['journal'] if row['event']=='simulated_native_call' and row['mode']==1]
        self.assertEqual(calls,['names','program']);self.assertEqual(self.camera.properties,before)
        with self.assertRaises(ValueError):job.install(90)

    def test_later_FL23_is_accepted_without_losing_native_stages(self):
        from looktool.devicesession import modules
        modules();import compat
        root=Path(os.environ['A7C2_RESEARCH_FIXTURES']).parents[2]
        stock={name:(root/'firmware/a7c2-2.01/components'/name).read_bytes() for name in devicejob.PROGRAM_PATHS}
        document=lookfile.read(self.source)
        forward,_,native=device_layout.replace(stock['appFw.so'],stock['cpapp-b.bin'],{4:self.table},hash_checks=False,
            native_photo={4:document['native_photo']},native_bank=self.bank)
        _,_,enabled,_,_=compat.plan(native['appFw.so'],native['cpapp-b.bin'],transitions=False)
        self.assertEqual(enabled['cpapp-b.bin'],native['cpapp-b.bin'])
        job=NativeJob(self.root/'byte-readback',factory=self.camera);job.root.mkdir()
        job.state=dict(byte_checks=True,source_hashes={name:firmware.sha(raw) for name,raw in stock.items()},
            target_hashes={name:firmware.sha(raw) for name,raw in native.items()},journal=[])
        job.source=lambda name:stock[name]
        (job.root/'transition').mkdir();(job.root/'transition/forward.private.json').write_text(json.dumps(forward))
        for name,path in devicejob.PROGRAM_PATHS.items():self.camera.files[path]=enabled[name]
        self.assertEqual(job._read_programs(self.camera,job.state['target_hashes']),enabled)
        self.assertTrue(job._later_fl23)


if __name__=='__main__':unittest.main()
