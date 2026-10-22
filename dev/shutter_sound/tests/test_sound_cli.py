import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import buffer_trial
import boot_trial
import native_codec
import sound_cli as cli
import trial


class IntegratedSoundTests(unittest.TestCase):
    def test_diagnostic25_fresh_conversion_can_save_without_on_or_attach(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);root=base/'sound';root.mkdir()
            converted=root/'jobs/converted';converted.mkdir(parents=True)
            payload=bytes(64);(converted/'custom-native.private.bin').write_bytes(payload)
            (root/'conversion.private.json').write_text(json.dumps(dict(conversion=str(converted))))
            identity=dict(model='ILCE-7CM2',serial_sha256='fixture-body')
            calls=[]
            def adopt(job,backup,zig=None,**kwargs):
                calls.append('adopt')
                job.mkdir(parents=True)
                value=dict(phase='written',identity=identity,complete_readback_and_settings_verified=True,electronic_only_gate=True,
                    adopted_existing_enabled=True,camera_firmware_written=False)
                trial.save(job,value);return value
            def install(job,backup,native,audio,actual,*args,**kwargs):
                calls.append('install');self.assertEqual(actual,payload);self.assertIsNone(audio)
                return dict(phase='installed_cold_test_pending')
            results=[]
            with patch.object(trial,'preflight',side_effect=adopt),patch.object(trial,'change') as change, \
                 patch.object(boot_trial,'install',side_effect=install):
                code=cli.main(['install','--workspace',str(root),'--power-confirmed'],report=results.append)
            self.assertEqual(code,0);self.assertEqual(calls,['adopt','install']);change.assert_not_called()
            self.assertEqual(results[0]['phase'],'installed_cold_test_pending')
            self.assertTrue((root/'sound.private.json').is_file())

    def test_fresh_save_without_conversion_requests_conversion_without_camera(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'sound';results=[]
            with patch.object(trial,'preflight',side_effect=AssertionError('No camera')):
                code=cli.main(['install','--workspace',str(root),'--power-confirmed'],report=results.append)
            self.assertEqual(code,0);self.assertEqual(results[0]['phase'],'sound_conversion_required')

    def test_fresh_save_enables_support_then_installs_before_single_final_reload(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);root,state=cli.workspace(base/'sound',True,base/'backup')
            converted=base/'converted';converted.mkdir();(converted/'custom-native.private.bin').write_bytes(bytes(64))
            state['conversion']=str(converted);calls=[]
            def prepare(job,*args,**kwargs):
                job.mkdir(parents=True);calls.append('prepare');return dict(phase='ready')
            def change(job,**kwargs):
                calls.append('enable')
                value=dict(phase='written',identity=dict(model='ILCE-7CM2'),complete_readback_and_settings_verified=True,electronic_only_gate=True)
                trial.save(job,value);return value
            with patch.object(trial,'preflight',side_effect=prepare),patch.object(trial,'change',side_effect=change), \
                 patch.object(boot_trial,'install',side_effect=lambda *a,**k:calls.append('install') or dict(phase='installed_cold_test_pending')):
                result=cli.install(root,state,None,power_confirmed=True)
            self.assertEqual(calls,['prepare','enable','install'])
            self.assertEqual(result['phase'],'installed_cold_test_pending')

    def test_main_reports_only_public_outcome_to_desktop(self):
        report = []
        with patch.object(cli, 'doctor', return_value=dict(phase='diagnostic', camera_io=False,
            identity='private identity', journal=['private native buffer'])):
            self.assertEqual(cli.main(['doctor'], report=report.append), 0)
        self.assertEqual(report, [dict(phase='diagnostic', camera_io=False)])

    def scenario(self, check):
        with tempfile.TemporaryDirectory() as temp:
            # macOS /var is an alias of /private/var; attach stores resolved
            # paths, so compare fixtures using the same canonical spelling.
            base = Path(temp).resolve()
            native, audio = base / 'native', base / 'audio'
            native.mkdir(); audio.mkdir()
            identity = {'model': 'ILCE-7CM2', 'serial_sha256': 'synthetic'}
            trial.save(native, {'phase': 'written', 'identity': identity,
                               'complete_readback_and_settings_verified': True, 'electronic_only_gate': True})
            trial.save(audio, {'phase': 'temporary_pcm_registered_cold_reload_required_after_test',
                              'identity': identity, 'wire_format': 0,
                              'result': {'temporary_pcm_registered': True}})
            (audio / 'payload.private.bin').write_bytes(bytes(64))
            root, state = cli.workspace(base / 'workspace', True, base / 'backup2')
            cli.attach(root, state, native, audio)
            def adopt(job,backup,zig=None,**kwargs):
                value=dict(phase='written',identity=identity,complete_readback_and_settings_verified=True,
                           adopted_existing_enabled=True,camera_firmware_written=False)
                Path(job).mkdir(parents=True);trial.save(job,value);return value
            with patch.object(trial,'preflight',side_effect=adopt):
                check(base, root, state, native, audio)

    def test_off_uses_only_narrow_CP_inverse_not_global_audio_settings(self):
        def check(base, root, state, native, audio):
            cli.confirm_audio(root, state, 'correct')
            cli.confirm_recovery(root, state)
            with patch.object(trial, 'change', return_value={'phase': 'restored'}) as change:
                cli.off(root, state)
                change.assert_called_once_with(native, restore=True, zig=None)
            self.assertIsNone(state['pending'])
            self.assertEqual(state['audio_job'], str(audio))
        self.scenario(check)

    def test_recorded_listening_judgment_is_not_a_mandatory_install_gate(self):
        def check(base, root, state, native, audio):
            cli.confirm_audio(root, state, 'quiet')
            with patch.object(boot_trial, 'install',return_value={'phase':'installed_cold_test_pending'}) as install:
                result=cli.install(root,state,100)
                self.assertEqual(result['phase'],'installed_cold_test_pending')
                install.assert_called_once()
        self.scenario(check)

    def test_install_uses_selected_bytes_without_reusing_audition_provenance(self):
        def check(base, root, state, native, audio):
            cli.confirm_audio(root, state, 'correct')
            cli.confirm_recovery(root, state)
            converted = base / 'converted'; converted.mkdir()
            (converted / 'custom-native.private.bin').write_bytes(bytes(64))
            (converted / 'selected.private.wav').write_bytes(b'source has since changed')
            state['conversion'] = str(converted)
            with patch.object(boot_trial, 'install', return_value={'phase': 'installed_cold_test_pending'}) as install:
                cli.install(root, state, 100)
                args = install.call_args.args
                self.assertEqual(args[4], bytes(64))
                self.assertNotEqual(args[2], native)
                self.assertEqual(cli.load_job(args[2])['identity'],cli.load_job(native)['identity'])
                self.assertIsNone(args[3])
                self.assertEqual(args[5], 100)
        self.scenario(check)

    def test_new_conversion_installs_current_bytes_without_reaudition(self):
        def check(base, root, state, native, audio):
            cli.confirm_audio(root, state, 'correct'); cli.confirm_recovery(root, state)
            converted = base / 'other'; converted.mkdir()
            payload=bytes([2])*64
            (converted / 'custom-native.private.bin').write_bytes(payload)
            state['conversion'] = str(converted)
            with patch.object(boot_trial, 'install',return_value={'phase':'installed_cold_test_pending'}) as install:
                self.assertEqual(cli.install(root,state,100)['phase'],'installed_cold_test_pending')
                self.assertIsNone(install.call_args.args[3])
                self.assertEqual(install.call_args.args[4],payload)
        self.scenario(check)

    def test_sound_off_and_save_do_not_require_a_cold_recovery_record(self):
        def check(base, root, state, native, audio):
            cli.confirm_audio(root, state, 'correct')
            with patch.object(trial,'change',return_value={'phase':'restored'}) as off,patch.object(boot_trial, 'install',return_value={'phase':'installed_cold_test_pending'}) as install:
                cli.off(root,state)
                off.assert_called_once()
                result=cli.install(root,state,100)
                self.assertEqual(result['phase'],'installed_cold_test_pending')
                install.assert_called_once()
        self.scenario(check)

    def test_reaudition_automatically_replaces_completed_marker_without_recorded_recovery(self):
        def check(base,root,state,native,audio):
            state['conversion']=str(audio);(audio/'custom-native.private.bin').write_bytes(bytes(64))
            with patch.object(buffer_trial,'run',return_value={'phase':'temporary_pcm_registered_cold_reload_required_after_test'}) as run:
                cli.audition(root,state)
            self.assertIsNone(run.call_args.kwargs['recovered_job'])
            self.assertEqual(run.call_args.kwargs['replace_jobs'],())
        self.scenario(check)

    def test_direct_save_does_not_require_or_fabricate_listening_or_recovery(self):
        def check(base,root,state,native,audio):
            with patch.object(trial,'factory',side_effect=AssertionError('No camera')):
                before=(audio/'job.private.json').read_bytes()
                with patch.object(boot_trial,'install',return_value={'phase':'installed_cold_test_pending'}) as install:
                    self.assertEqual(cli.install(root,state,100)['phase'],'installed_cold_test_pending')
                    install.assert_called_once()
                    self.assertEqual((audio/'job.private.json').read_bytes(),before)
                    self.assertIsNone(state['pending'])
        self.scenario(check)

    def test_unknown_off_result_is_archived_and_next_off_replans_from_current_body(self):
        def check(base, root, state, native, audio):
            cli.confirm_audio(root, state, 'correct'); cli.confirm_recovery(root, state)
            calls = []
            def change(job, **kwargs):
                calls.append(Path(job))
                value = trial.load(job) if hasattr(trial, 'load') else json.loads((Path(job) / 'job.private.json').read_text())
                trial.save(job, dict(value, phase='restoring'))
                raise TimeoutError('lost native reply')
            with patch.object(trial, 'change', side_effect=change):
                with self.assertRaises(TimeoutError): cli.off(root, state)
                saved = json.loads((root / 'sound.private.json').read_text())
                self.assertEqual(saved['pending']['outcome'], 'needs_review')
                # The next click is not blocked by the old record and does not
                # replay it: it adopts the current body into a new job.
                with self.assertRaises(TimeoutError): cli.off(root, state)
            self.assertEqual(calls[0], native)
            self.assertNotEqual(calls[1], native)
            self.assertEqual(json.loads((native / 'job.private.json').read_text())['phase'], 'restoring')
            self.assertTrue(any(h.get('phase') == 'superseded_by_current_selection' and h.get('job') == str(native)
                                for h in state['history']))
        self.scenario(check)

    def test_on_fresh_job_runs_backup_preflight_before_CP_write(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root, state = cli.workspace(base / 'workspace', True, base / 'backup2')
            calls = []
            with patch.object(trial, 'preflight', side_effect=lambda *a: calls.append('backup-preflight')), \
                 patch.object(trial, 'change', side_effect=lambda *a, **k: calls.append('write') or {'phase': 'written'}):
                cli.on(root, state, 100)
            self.assertEqual(calls, ['backup-preflight', 'write'])

    def test_on_adopts_an_already_enabled_native_branch_without_rewriting(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)
            root,state=cli.workspace(base/'workspace',True,base/'backup2')
            result={'phase':'written','adopted_existing_enabled':True,'camera_firmware_written':False}
            with patch.object(trial,'preflight',return_value=result), patch.object(trial,'change') as change:
                actual=cli.on(root,state,100)
            self.assertEqual(actual,result)
            change.assert_not_called()

    def test_convert_and_help_never_open_a_camera(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(trial, 'factory', side_effect=AssertionError('USB')):
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as exit_status: cli.main(['--help'])
            self.assertEqual(exit_status.exception.code, 0)
            source = Path(temp) / 'source.wav'
            native_codec.write_wav(source, [0, 300, -600, 1200] * 100, 24000)
            from media import convert
            report = convert(source, Path(temp) / 'candidate')
            self.assertFalse(report['camera_io'])


if __name__ == '__main__': unittest.main()
