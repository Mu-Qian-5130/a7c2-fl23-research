"""Known zero-commit failure accounting; no camera/native writes."""
from contextlib import contextmanager
import copy,json,struct,tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from desktopapp import reviewnames
from looktool import checkpointworker,nameworker
from test_checkpoint import stock_names,fake_compile


class ReviewNamesTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.failed=self.root/'failed';(self.failed/'evidence').mkdir(parents=True)
        self.names=stock_names();self.files={'appFw.so':bytes(40000),'cpapp-b.bin':bytes(40000)}
        target=dict(self.files,**{'appFw.so':b'\1'+bytes(39999)})
        with patch.object(checkpointworker,'compile_worker',side_effect=fake_compile):
            programs=checkpointworker.build_programs(self.files,target,self.failed/'worker')
        path=self.failed/'names/names.so';path.parent.mkdir();path.write_bytes(b'known failed worker')
        build=dict(path=str(path),count=68,files=[dict(file=n,before_bytes=len(self.names),
            inverse=dict(before_count=2860,changes=[])) for n in nameworker.filenames()])
        self.raw=nameworker.REPORT.pack(b'A7NMR001',1,1,3,68,-28,0,0,0,0,0,517,39,0,0,0,0,0,bytes(32))
        self.report=self.failed/'evidence/old-names-forward-1.bin';self.report.write_bytes(self.raw)
        self.state=dict(mode='install_all',phase='NEEDS_REVIEW',identity={'model':'ILCE-7CM2'},forward_name_build=build,
            inverse_name_build=None,program_builds=programs,journal=[dict(event='native_intent',result='a7c2.names.result',mode=1)])
        self.save()
        self.temps={'lut-names-staged.so':path.read_bytes(),'a7c2.names.request':struct.pack('<8sII',b'A7NAM001',1,0),'a7c2.names.result':self.raw}
        case=self
        class Camera:
            def read(self,path):
                if path=='/usr/lib/appFw.so':return case.files['appFw.so']
                if path=='/cp/cpapp-b.bin':return case.files['cpapp-b.bin']
                return case.names
            def temp_read(self,name,missing=False):return case.temps.get(name)
            def temp_remove(self,name):case.temps.pop(name)
        @contextmanager
        def factory(expected,**kwargs):yield Camera()
        self.factory=factory

    def save(self):(self.failed/'direct.private.json').write_text(json.dumps(self.state),encoding='utf-8')
    def run_review(self):return reviewnames.run(self.failed,self.root/'review',factory=self.factory)

    def test_reviews_actual_error_shape_and_only_removes_owned_temporary_artifacts(self):
        old={str(p):p.read_bytes() for p in self.failed.rglob('*') if p.is_file()}
        result=self.run_review()
        self.assertTrue(result['pre_program_failure_accounted']);self.assertFalse(result['firmware_written'])
        self.assertEqual(self.temps,{})
        self.assertEqual(old,{str(p):p.read_bytes() for p in self.failed.rglob('*') if p.is_file()})

    def test_partial_commit_failed_rollback_or_unknown_program_intent_is_rejected(self):
        for index,value in ((14,1),(6,-5),(8,-16)):
            v=list(nameworker.REPORT.unpack(self.raw));v[index]=value;self.report.write_bytes(nameworker.REPORT.pack(*v))
            with self.assertRaises(ValueError):reviewnames.source(self.failed)
        self.report.write_bytes(self.raw)
        self.state['journal'].insert(0,dict(event='native_intent',result='checkpoint.program.result',mode=1));self.save()
        with self.assertRaises(ValueError):reviewnames.source(self.failed)

    def test_changed_program_does_not_remove_any_temporary_bytes(self):
        self.files['appFw.so']=b'\2'+bytes(39999);before=dict(self.temps)
        with self.assertRaisesRegex(ValueError,'program windows differ'):self.run_review()
        self.assertEqual(self.temps,before)

    def test_foreign_temporary_data_is_not_removed(self):
        for name in ('lut-names-staged.so','libJit.so'):
            original=dict(self.temps);self.temps[name]=b'other operation';before=dict(self.temps)
            with self.assertRaises(ValueError):self.run_review()
            self.assertEqual(self.temps,before);self.temps=original
