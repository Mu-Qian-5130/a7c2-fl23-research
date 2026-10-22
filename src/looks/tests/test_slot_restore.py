"""Host workflow simulation using private real programs; never camera proof."""
import copy,json,os,unittest
from unittest.mock import patch
import test_device_job as f
from looktool import devicejob,firmware,nameworker,resources,six

@unittest.skipUnless(os.environ.get('A7C2_RESEARCH_FIXTURES'),'Needs private program fixtures')
class SlotRestoreTests(f.DeviceJobTests):
    def accepted(self,job):
        self.camera.reboot();self.assertEqual(job.verify(True)['phase'],'COMPLETE')
    def another(self,number,slot,raw,name):
        job=f.SimJob(self.folder/('job'+str(number)),factory=self.camera);job.table=raw
        job.create(self.reference,name,slot,self.model,self.folder/('backup'+str(number)),write=True,battery=90,input_space='sony-st-srgb')
        self.accepted(job);return job
    def test_restore_slot6_after_later_slot5_preserves_other_tables_names_recipes(self):
        old=six.read_tables(self.cp);self.create();self.accepted(self.job)
        second=self.another(2,5,bytes([2])*1215,'Updated five')
        # File fingerprints are deliberately wrong: selected-slot restore must
        # use recorded bytes and fresh readback, never these old hash gates.
        state=json.loads(self.job.state_path.read_text(encoding='utf-8'))
        state['backup_files']={k:'0'*64 for k in state['backup_files']}
        state['artifacts']={k:'0'*64 for k in state['artifacts']}
        state['conversion_table_sha256']='0'*64
        for inventory in ('backup_objects','backup_mirror_objects'):
            for spec in state[inventory].values():spec['sha256']='0'*64
        self.job.state_path.write_text(json.dumps(state),encoding='utf-8')
        self.assertLess(second.state['backup_storage_summary']['new_primary_compressed_bytes'],65536)
        before=copy.deepcopy(self.camera.properties);latest=six.read_tables(self.camera.files['/cp/cpapp-b.bin'])
        undo=f.SimJob(self.folder/'undo6',factory=self.camera)
        self.assertEqual(undo.restore_slot(self.job,90,self.folder/'backup-undo6')['phase'],'AWAITING_RELOAD')
        self.assertTrue(undo.state['byte_checks'])
        actual=six.read_tables(self.camera.files['/cp/cpapp-b.bin'])
        self.assertEqual(actual[5],old[5]);self.assertEqual(actual[:5],latest[:5])
        selected={field['key'] for field in self.job.state['settings_plan']}
        self.assertEqual({k:v for k,v in self.camera.properties.items() if k not in selected},{k:v for k,v in before.items() if k not in selected})
        for n in nameworker.filenames():
            titles=resources.decode(self.camera.files['/usr/share/app/'+n])['entries']
            self.assertEqual(titles[resources.LABEL_IDS[4]]['text'],'Updated five')
            self.assertEqual(titles[resources.LABEL_IDS[5]]['text'],'Original 6')
        self.assertFalse((undo.root/'source/appFw.so').exists());self.assertFalse((undo.root/'resource-target').exists())
        self.assertFalse(list(undo.root.glob('evidence/*readback*')))
        self.assertLess((undo.root/'slot-6-before.private.json').stat().st_size,32768)
        self.accepted(undo)
    def test_later_same_slot_change_stops_before_native_execution(self):
        self.create();self.accepted(self.job)
        self.another(2,6,bytes([3])*1215,'Newest six')
        before=self.camera.files.copy();undo=f.SimJob(self.folder/'undo',factory=self.camera)
        with self.assertRaisesRegex(ValueError,'changed later'):undo.restore_slot(self.job,90,self.folder/'backup-undo')
        self.assertEqual(self.camera.files,before)
        self.assertFalse(any(e['event']=='simulated_native_call' for e in undo.state['journal']))
    def test_damaged_compressed_backup_stops_install_before_camera_connection(self):
        self.create(False)
        entry=self.job.state['backup_objects']['cpapp-b.bin']['chunks'][0]
        path=self.job._stores()[0]._path(entry.get('delta',entry['sha256']));path.write_bytes(b'damaged')
        with patch.object(self.job,'factory',side_effect=AssertionError('No camera')):
            with self.assertRaises((ValueError,__import__('zlib').error)):self.job.install(90)

if __name__=='__main__':unittest.main()
