"""Compressed backup integrity, space use and independence; no USB."""
import copy,json,os,random,shutil,tempfile,unittest,zlib
from pathlib import Path
from looktool import backupstore as b
from looktool.devicejob import Job
from unittest.mock import patch

class StoreTests(unittest.TestCase):
    def test_slot_reader_ignores_hash_values_but_keeps_compression_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            store=b.Store(folder,'a'*64,hash_checks=False)
            spec=store.put('before',b'original slot bytes')
            spec['sha256']='0'*64
            self.assertEqual(store.read(spec),b'original slot bytes')
            store._path(spec['chunks'][0]['sha256']).write_bytes(b'broken compressed data')
            with self.assertRaises(ValueError):store.read(spec)
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=b.Store(self.root/'work','a'*64)
    def test_roundtrip_empty_chunk_boundaries_and_resized_files(self):
        for raw in [b'',b'a',bytes(100),bytes(b.CHUNK),bytes(b.CHUNK+1),b'other bytes'*731]:
            spec=self.store.put('one',raw);self.assertEqual(self.store.read(spec),raw)
    def test_one_foundation_and_direct_deltas_no_previous_job_dependency(self):
        raw=random.Random(201).randbytes(b.CHUNK+100)
        first=self.store.put('cp',raw);initial=self.store.new_bytes
        later=bytearray(raw);later[91:96]=b'abcde'
        second=self.store.put('cp',bytes(later));extra=self.store.new_bytes-initial
        later[200:210]=b'1234567890';third=self.store.put('cp',bytes(later))
        self.assertLess(extra,4096)
        self.assertEqual(second['chunks'][0]['base'],first['chunks'][0]['sha256'])
        self.assertEqual(third['chunks'][0]['base'],first['chunks'][0]['sha256'])
        self.store._path(second['chunks'][0]['delta']).unlink()
        self.assertEqual(self.store.read(third),bytes(later))
    def test_identical_repeated_readback_adds_no_objects(self):
        raw=os.urandom(8192);one=self.store.put('a',raw);count=self.store.new_objects
        self.assertEqual(one,self.store.put('a',raw));self.assertEqual(count,self.store.new_objects)
        self.store.put('other-name',raw);self.assertEqual(count,self.store.new_objects)
    def test_independent_store_with_different_foundation_still_reconstructs(self):
        mirror=b.Store(self.root/'mirror','a'*64)
        self.store.put('name',b'initial left');mirror.put('name',b'initial right is longer')
        raw=b'new identical snapshot';a=self.store.put('name',raw);c=mirror.put('name',raw)
        self.assertNotEqual(a,c);self.assertEqual(self.store.read(a),mirror.read(c))
        shutil.rmtree(self.store.root)
        self.assertEqual(mirror.read(c),raw)
    def test_corrupt_missing_wrong_hash_and_wrong_dimensions_reject(self):
        spec=self.store.put('file',os.urandom(100));path=self.store._path(spec['chunks'][0]['sha256'])
        packed=path.read_bytes()
        for altered in [packed[:-1],packed+b'junk',zlib.compress(b'wrong')]:
            path.write_bytes(altered)
            with self.assertRaises(ValueError):self.store.read(spec)
        path.write_bytes(packed)
        for values in [{'bytes':-1},{'sha256':'0'*64},{'chunks':[]}]:
            with self.assertRaises(ValueError):self.store.read(dict(spec,**values))
        path.unlink()
        with self.assertRaises(FileNotFoundError):self.store.read(spec)
    def test_delta_target_corruption_rejects(self):
        self.store.put('file',b'a'*100);spec=self.store.put('file',b'b'*100)
        spec['chunks'][0]['sha256']='0'*64
        with self.assertRaises(ValueError):self.store.read(spec)
    def test_decompression_bomb_and_path_escape_reject(self):
        raw=b'a'*100;spec=self.store.put('file',raw)
        self.store._path(spec['chunks'][0]['sha256']).write_bytes(zlib.compress(b'a'*1000000))
        with self.assertRaises(ValueError):self.store.read(spec)
        for digest in ['../escape','0'*63,'f'*64+'/x']:
            with self.assertRaises(ValueError):self.store._path(digest)
    def test_body_binding_separates_same_files(self):
        first=b.body_key({'model':'ILCE-7CM2','serial_sha256':'body-a'})
        second=b.body_key({'model':'ILCE-7CM2','serial_sha256':'body-b'})
        self.assertNotEqual(first,second)
        with self.assertRaises(ValueError):b.body_key({'model':'ILCE-7RM5','serial_sha256':'body-a'})
    def test_legacy_plain_backup_still_loads(self):
        job=Job(self.root/'old');second=self.root/'old-copy';(job.root/'source').mkdir(parents=True);second.mkdir()
        for folder in [job.root/'source',second]:(folder/'old.bin').write_bytes(b'old full backup')
        state={'schema':'a7c2-lut-device-job/1','backup_copy':str(second),'backup_files':{'old.bin':b.sha(b'old full backup')}}
        b.write_json(job.state_path,state);job.load();self.assertEqual(job.source('old.bin'),b'old full backup')
        self.assertEqual((second/'old.bin').read_bytes(),b'old full backup')
    def test_low_battery_slot_restore_stops_before_camera_or_folders(self):
        original=type('Original',(),{'state':{'phase':'COMPLETE','slot':1},'load':lambda self,**kw:None,'source':lambda self,n:b'not-used'})()
        job=Job(self.root/'new')
        with patch.object(job,'factory',side_effect=AssertionError('No camera')):
            with self.assertRaisesRegex(ValueError,'50'):job.restore_slot(original,12,self.root/'copy')
        self.assertFalse(job.root.exists())
    def test_normal_conversion_does_not_require_a_restore_recipe(self):
        from looktool import devicejob
        source=self.root/'source.cube';source.write_text('LUT_3D_SIZE 2\n',encoding='ascii')
        job=Job(self.root/'normal');job.root.mkdir()
        job.state={'reference_contract':{'input_space':'sony-st-srgb','bridge':None},'journal':[]}
        model=json.loads((Path(devicejob.__file__).parents[1]/'assets/rendering-model-v1.json').read_text(encoding='utf-8'))
        with patch.object(devicejob.project,'reference',return_value=(None,{'type':'unit-test'})),patch.object(devicejob.native,'fit_reference',return_value=(bytes(1215),{'convergence':{'converged':True},'synthetic_holdout':{}})):
            self.assertEqual(job._fit(source,'A look',3,model,'test'),bytes(1215))
        self.assertTrue((job.root/'candidate/slot3.bin').is_file())
        self.assertFalse((job.root/'candidate/restore-recipe.private.json').exists())

if __name__=='__main__':unittest.main()
