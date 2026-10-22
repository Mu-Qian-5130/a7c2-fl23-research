"""Explicit factory-name continuation; no camera I/O."""
import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from test_checkpoint import Camera, values, fake_compile, KEYS
from test_direct import SimDirect
from looktool import checkpoint, checkpointworker, direct, directresume, nameworker, resources


def report(count, status=-28, restored=0, rollback=0):
    return nameworker.REPORT.pack(b'A7NMR001', 1, 2, 3, count, status, rollback, 0, 0, 0,
                                  0, 519, 3, 0, 0, restored, 0, 0, bytes(32))


class ResumeJob(SimDirect):
    def native(self, camera, kind, mode, build=None):
        if kind == 'names':
            camera.native_calls.append((kind, mode))
            if mode == 2:
                for n in build['files']:
                    path = '/usr/share/app/' + n
                    camera.files[path] = resources.before_custom(camera.files[path])
            return {'mode': mode}
        return super().native(camera, kind, mode, build)


class DirectResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.failed = self.root / 'failed'
        (self.failed / 'worker').mkdir(parents=True)
        (self.failed / 'evidence').mkdir()
        original = values()
        modified = dict(original)
        modified['appFw.so'] = b'\x03' + original['appFw.so'][1:]
        for n in nameworker.filenames():
            modified['resources/' + n] = resources.rename(original['resources/' + n], {1: 'CC'})[0]
        self.camera = Camera(modified)
        self.camera.files['/usr/lib/appFw.so'] = original['appFw.so']
        self.compiler = patch.object(checkpointworker, 'compile_worker', side_effect=fake_compile)
        self.compiler.start()
        self.addCleanup(self.compiler.stop)
        programs = checkpointworker.build_programs(modified, original, self.failed / 'worker')
        names = checkpointworker.build_names(modified, original, self.failed / 'worker', 'failed')
        self.raw = report(68)
        (self.failed / 'evidence/known-names-2.bin').write_bytes(self.raw)
        self.prior = dict(mode='factory_reset', phase='NEEDS_REVIEW', identity=self.camera.identity,
            factory_path='builtin', inverse_name_build=names, program_builds=programs, forward_name_build=None,
            journal=[{'event': 'native_result_verified', 'result': {'spans': [
                {'offset': 0, 'length': 16, 'memory': modified['appFw.so'][:16].hex()}]}}]
                + [{'event': 'native_result_verified', 'stage': 'checkpoint.staged.so', 'mode': 1,
                    'result': {'windows': p['windows']}} for p in programs]
                + [{'event': 'native_intent', 'result': 'checkpoint.names.result', 'mode': 2}])
        self.write_prior()
        self.temps = {'checkpoint.staged.so': b'simulated-worker', 'checkpoint.names.result': self.raw,
                      'checkpoint.names.request': struct.pack('<8sII', b'A7NAM001', 2, 0)}
        self.camera.temp_read = lambda n, missing=False: self.temps.get(n)
        self.camera.temp_remove = lambda n: self.temps.pop(n)

    def write_prior(self):
        (self.failed / 'direct.private.json').write_text(json.dumps(self.prior), encoding='utf-8')

    def target(self, current, *args, **kwargs):
        target = dict(current)
        for n in nameworker.filenames():
            target['resources/' + n] = resources.before_custom(current['resources/' + n])
        return target, [{KEYS[0]: b'\x05'}, {}], None

    def job(self):
        return ResumeJob(self.root / 'continuation', factory=self.camera)

    def test_continues_only_names_settings_and_wbi_and_preserves_failed_job(self):
        before = {str(p): p.read_bytes() for p in self.failed.rglob('*') if p.is_file()}
        with patch.object(direct, 'plan', side_effect=self.target):
            job = self.job()
            result = job.resume_factory_names(self.failed, power_confirmed=True, factory_values={})
        self.assertEqual(result['phase'], 'AWAITING_RELOAD')
        self.assertEqual(result['program_builds'], [])
        self.assertFalse(any(k == 'program' for k, mode in self.camera.native_calls))
        self.assertIn(('names', 2), self.camera.native_calls)
        self.assertEqual(self.camera.ram[0][KEYS[0]].data, b'\x05')
        self.assertEqual(self.temps, {})
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.failed.rglob('*') if p.is_file()})
        self.assertEqual(list(self.root.rglob('*.zip')), [])

    def test_program_mismatch_does_not_remove_temp_or_invoke_native(self):
        self.camera.files['/usr/lib/appFw.so'] = b'\xff' + self.camera.files['/usr/lib/appFw.so'][1:]
        before = dict(self.temps)
        with patch.object(direct, 'plan', side_effect=self.target), self.assertRaisesRegex(ValueError, 'program bytes'):
            self.job().resume_factory_names(self.failed, power_confirmed=True, factory_values={})
        self.assertEqual(self.camera.native_calls, [])
        self.assertEqual(before, self.temps)

    def test_planner_needing_program_write_is_not_replayed(self):
        def wrong(current, *a, **kw):
            result, wanted, _ = self.target(current)
            result['cpapp-b.bin'] = b'\x01' + result['cpapp-b.bin'][1:]
            return result, wanted, None
        with patch.object(direct, 'plan', side_effect=wrong), self.assertRaisesRegex(ValueError, 'will not write programs'):
            self.job().resume_factory_names(self.failed, power_confirmed=True, factory_values={})
        self.assertEqual(self.camera.native_calls, [])
        self.assertEqual(self.camera.saves, [])

    def test_unexpected_temp_preserved_and_cleanup_is_all_or_nothing(self):
        for name in ('checkpoint.names.result', 'libJit.so', 'checkpoint.program.result'):
            with self.subTest(name=name):
                temps = dict(self.temps, **{name: b'unexpected'})
                self.camera.temp_read = lambda n, missing=False: temps.get(n)
                self.camera.temp_remove = lambda n: temps.pop(n)
                before = dict(temps)
                with self.assertRaises(ValueError):
                    directresume.cleanup(self.camera, self.failed, self.prior, self.raw, lambda *a, **kw: None)
                self.assertEqual(before, temps)

    def test_unknown_or_unclean_result_refuses_before_connecting(self):
        for raw in (report(68, status=-5), report(68, rollback=-5), b'incomplete'):
            (self.failed / 'evidence/known-names-2.bin').write_bytes(raw)
            with patch.object(self.camera, '__call__') as opened, self.assertRaises(ValueError):
                self.job().resume_factory_names(self.failed, power_confirmed=True, factory_values={})
            opened.assert_not_called()

    def test_missing_result_or_later_operation_is_not_guessed(self):
        self.prior['journal'].append({'event': 'something_else'})
        self.write_prior()
        with self.assertRaisesRegex(ValueError, 'Unaccounted'):
            directresume.source(self.failed)

    def test_failed_preflight_does_not_restore_settings_or_programs(self):
        job = self.job()
        native = job.native
        def fail(camera, kind, mode, build=None):
            if kind == 'names' and mode == 4:
                raise ValueError('simulated capacity failure')
            return native(camera, kind, mode, build)
        with patch.object(direct, 'plan', side_effect=self.target), patch.object(job, 'native', side_effect=fail), self.assertRaisesRegex(ValueError, 'capacity'):
            job.resume_factory_names(self.failed, power_confirmed=True, factory_values={})
        self.assertEqual(self.camera.saves, [])
        self.assertFalse(any(k == 'program' for k, mode in self.camera.native_calls))
        self.assertEqual(job.state['phase'], 'NEEDS_REVIEW')
