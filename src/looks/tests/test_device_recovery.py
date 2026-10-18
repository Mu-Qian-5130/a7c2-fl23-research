"""Interrupted transactions: evidence recovery never invokes a native loader."""
import json,os,struct,unittest
from pathlib import Path
from unittest.mock import patch
from looktool import devicejob,firmware,nameworker,worker
import test_device_job as fixtures
from test_device_job import SimJob

@unittest.skipUnless(os.environ.get('A7C2_RESEARCH_FIXTURES'),'Needs private complete sources')
class RecoveryTests(fixtures.DeviceJobTests):
    def test_unknown_programs_stop_before_any_native_probe(self):
        raw=bytearray(self.camera.files['/cp/cpapp-b.bin']);raw[0x13553a]^=1
        self.camera.files['/cp/cpapp-b.bin']=bytes(raw)
        with self.assertRaises(ValueError):self.create(False)
        self.assertFalse(any(e['event']=='simulated_native_call' for e in self.job.state['journal']))
    def test_modified_recipe_plan_stops_before_any_installation(self):
        self.create(False);self.job.state['settings_plan'][0]['key']=0x02a40000
        self.job.save('PREFLIGHT_VERIFIED')
        with self.assertRaises(ValueError):self.job.install(90)
        self.assertEqual(self.camera.files['/cp/cpapp-b.bin'],self.cp)
        self.assertEqual(self.camera.saves,0)
        calls=[e for e in self.job.state['journal'] if e['event']=='simulated_native_call' and e['mode']==1]
        self.assertFalse(calls)
    def pending_program(self,mode):
        state=self.job.state;contract=state['program_build']['contract'];blob=(self.job.root/'worker/program/program.so').read_bytes()
        before=[bytes.fromhex(contract['after' if mode==2 else 'before'][n]) for n in worker.NAMES]
        after=[bytes.fromhex(contract['before' if mode==2 else 'after'][n]) for n in worker.NAMES]
        raw=worker.REPORT.pack(b'A7IRP001',1,mode,9,contract['window_writes'],*([0]*6+[123]),11,12,*[contract['sizes'][n] for n in worker.NAMES])+b''.join(before+after)
        files={'lut-program-staged.so':blob,'a7c2.install.request':struct.pack('<8sII',b'A7INS001',mode,0),'a7c2.install.result':raw}
        self.job.record('native_intent',stage='lut-program-staged.so',result='a7c2.install.result',mode=mode,worker_sha256=firmware.sha(blob))
        self.camera.temp_read=lambda name,missing=False:files.get(name)
        self.camera.temp_remove=lambda name:files.pop(name,None)
        return files
    def test_lost_program_completion_recovers_and_resumes_without_reinstall(self):
        self.job.fail_after_program=True
        with self.assertRaises(TimeoutError):self.create()
        files=self.pending_program(1)
        self.assertEqual(self.job.recover()['phase'],'PROGRAMS_VERIFIED');self.assertFalse(files)
        self.job.fail_after_program=False
        self.assertEqual(self.job.resume(90)['phase'],'AWAITING_RELOAD')
        calls=[e for e in self.job.state['journal'] if e['event']=='simulated_native_call' and e['kind']=='program' and e['mode']==1]
        self.assertEqual(len(calls),1)
    def test_missing_completion_never_advances_or_reexecutes(self):
        self.job.fail_after_program=True
        with self.assertRaises(TimeoutError):self.create()
        files=self.pending_program(1);files.pop('a7c2.install.result')
        self.assertEqual(self.job.recover()['phase'],'NEEDS_REVIEW')
        self.assertIn('lut-program-staged.so',files)
        with self.assertRaises(ValueError):self.job.resume(90)
    def test_partial_saved_settings_require_stable_exact_job_values(self):
        self.create();self.job.save('NEEDS_REVIEW',failed_during='SETTINGS_WRITE_INTENT')
        fields=self.job.state['settings_plan']
        for f in fields[2:]:
            p=self.camera.properties[f['key']];self.camera.properties[f['key']]=p._replace(data=bytes.fromhex(f['before_ram']))
            self.camera.saved[f['key']]=self.camera.properties[f['key']]
        self.assertEqual(self.job.recover()['phase'],'PARTIAL_SETTINGS_VERIFIED')
        self.assertEqual(self.job.resume(90)['phase'],'AWAITING_RELOAD')
    def test_program_restore_completion_resumes_only_names_and_reload(self):
        self.create();original=SimJob._invoke
        def interrupt(job,camera,kind,mode):
            result=original(job,camera,kind,mode)
            if kind=='program' and mode==2:raise TimeoutError('lost restore completion')
            return result
        with patch.object(SimJob,'_invoke',interrupt):
            with self.assertRaises(TimeoutError):self.job.restore(90)
        files=self.pending_program(2)
        self.assertEqual(self.job.recover()['phase'],'PROGRAMS_RESTORED');self.assertFalse(files)
        self.assertEqual(self.job.resume(90)['phase'],'RESTORED_AWAITING_RELOAD')
        calls=[e for e in self.job.state['journal'] if e['event']=='simulated_native_call' and e['kind']=='program' and e['mode']==2]
        self.assertEqual(len(calls),1)

if __name__=='__main__':unittest.main()
