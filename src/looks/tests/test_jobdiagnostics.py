"""Recorded failures: precise explanation, no USB, no scientific dependencies."""
import copy,gzip,json,os,struct,subprocess,sys,tempfile,unittest
from pathlib import Path
from looktool import jobdiagnostics as d,nameworker

ROOT=Path(__file__).resolve().parents[3]

class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.state={'schema':'a7c2-lut-device-job/1','phase':'NEEDS_REVIEW','failed_during':'NAME_RESTORE_INTENT','active_operation':'restore',
            'identity':{'serial':'do-not-publish-body-data'},'name_build':{'AP':'11'*32,'count':2,'files':[{},{}]},
            'error':'Native name transaction incomplete; inspect existing result without replay',
            'journal':[{'event':'native_intent','result':'a7c2.names.result','mode':2}]}
        self.path=self.root/'job.private.json';self.path.write_text(json.dumps(self.state),encoding='utf-8')
    def report(self,status=-84,phase=3):
        return d.NAME_REPORT.pack(b'A7NMR001',1,2,phase,2,status,*([0]*5),123,*([0]*6),bytes.fromhex('11'*32))
    def test_native_failure_message_exposes_real_status_without_weakening_rejection(self):
        raw=self.report()
        with self.assertRaisesRegex(ValueError,r'mode=2, phase=3, status=-84 \(EILSEQ\)'):
            nameworker.validate(raw,2,self.state['name_build'])
        info=d.name_report(raw,2,self.state['name_build'])
        self.assertTrue(info['ap_matches_job']);self.assertTrue(info['historical_evidence_only'])
    def test_bad_ap_and_mode_are_visible(self):
        info=d.name_report(self.report(0,9),1,{'AP':'22'*32})
        self.assertFalse(info['requested_mode_matches']);self.assertFalse(info['ap_matches_job'])
    def test_report_abi_and_size_remain_strict(self):
        for raw in [self.report()[:-1],self.report()+b'x',b'badmagic'+self.report()[8:]]:
            with self.assertRaises(ValueError):d.name_report(raw)
    def test_diagnosis_reads_only_existing_files_and_redacts_identity(self):
        folder=self.root/'evidence';folder.mkdir();report=folder/'0003-random-names-2.bin';report.write_bytes(self.report())
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result=d.explain(self.root)
        self.assertEqual(result['problem'],'name_restoration_needs_inspection')
        self.assertEqual(result['native_name_report']['phase'],3);self.assertFalse(result['camera_io']);self.assertFalse(result['state_modified'])
        self.assertNotIn('do-not-publish',json.dumps(result))
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
    def test_shared_temp_conflict_directs_to_first_owner_not_another_restore(self):
        self.state['error']='Existing temporary state needs recovery: lut-names-staged.so'
        self.path.write_text(json.dumps(self.state),encoding='utf-8')
        result=d.explain(self.root)
        self.assertEqual(result['problem'],'pending_shared_temporary_state');self.assertIn('FIRST failing job',result['next_step'])
    def test_program_mismatch_has_distinct_explanation_and_missing_report_is_not_invented(self):
        self.state['error']='Complete host readback differs: appFw.so';self.path.write_text(json.dumps(self.state),encoding='utf-8')
        result=d.explain(self.root)
        self.assertEqual(result['problem'],'current_program_differs_from_job');self.assertIsNone(result['native_name_report'])
    def test_gzip_report_is_bounded_and_supported(self):
        report=self.root/'report.bin.gz';report.write_bytes(gzip.compress(self.report()))
        self.assertEqual(d.explain(self.root,report)['native_name_report']['status'],-84)
        report.write_bytes(gzip.compress(b'x'*100000))
        with self.assertRaises(ValueError):d.explain(self.root,report)
    def test_root_command_runs_without_site_packages_or_usb_imports(self):
        code='import runpy,sys; m=runpy.run_path(sys.argv[1]); result=m["main"](["diagnose-job",sys.argv[2]]); assert result==0; assert "numpy" not in sys.modules and "usb" not in sys.modules'
        env=dict(os.environ);env.pop('PYTHONPATH',None);env['PYTHONIOENCODING']='utf-8'
        run=subprocess.run([sys.executable,'-S','-c',code,str(ROOT/'lut.py'),str(self.root)],env=env,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(run.returncode,0,run.stderr);self.assertFalse(json.loads(run.stdout)['camera_io'])

if __name__=='__main__':unittest.main()
