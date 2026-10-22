"""Factory recovery faults and discovery; all camera access is simulated."""
import copy
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from looktool import direct, factoryrecover


class FactoryRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.failed = self.root / 'failed'
        self.failed.mkdir()
        self.prior = dict(mode='factory_reset', phase='NEEDS_REVIEW', factory_path='builtin',
            identity=dict(model='ILCE-7CM2', serial_sha256='fixture-body'), journal=[])
        self.intent = dict(event='native_stage_intent', stage='checkpoint.staged.so',
            result='checkpoint.names.result', request='checkpoint.names.request', mode=2,
            contents_hex=struct.pack('<8sII', b'A7NAM001', 2, 0).hex())
        self.prior['journal'].append(self.intent)
        self.write_prior()

    def write_prior(self):
        (self.failed / 'direct.private.json').write_text(json.dumps(self.prior), encoding='utf-8')

    def test_original_enospc_is_discovered_despite_later_read_only_failure(self):
        later = self.root / 'later-no-write'
        later.mkdir()
        state = dict(self.prior, journal=[], program_builds=[])
        (later / 'direct.private.json').write_text(json.dumps(state))
        os.utime(later / 'direct.private.json', (4_000_000_000, 4_000_000_000))
        selected = factoryrecover.pending(self.root)
        self.assertEqual(selected[0], self.failed.resolve())


    def test_completed_recovery_selects_verification_and_complete_recovery_is_not_replayed(self):
        continued = self.root / 'continued'
        continued.mkdir()
        for phase in ('AWAITING_RELOAD', 'LOADED', 'COMPLETE'):
            state = dict(self.prior, phase=phase, resume_from=str(self.failed))
            (continued / 'direct.private.json').write_text(json.dumps(state))
            os.utime(continued / 'direct.private.json', (4_000_000_000, 4_000_000_000))
            chosen = factoryrecover.pending(self.root, self.failed)
            if phase == 'COMPLETE':
                self.assertIsNone(chosen)
            else:
                self.assertEqual(chosen[0], continued.resolve())
                self.assertEqual(chosen[1]['phase'], phase)

    def test_loaded_readonly_verified_is_not_pending_even_without_photo_acceptance(self):
        continued=self.root/'loaded-recovery';continued.mkdir()
        state=dict(self.prior,phase='LOADED',resume_from=str(self.failed),
            readonly_after_reload_verified=True,physical_checks_accepted=False)
        path=continued/'direct.private.json';path.write_text(json.dumps(state))
        os.utime(path,(4_000_000_000,4_000_000_000))
        original=self.failed.joinpath('direct.private.json').read_bytes()
        self.assertIsNone(factoryrecover.pending(self.root,self.failed))
        self.assertIsNone(factoryrecover.pending(self.root,continued))
        self.assertEqual(self.failed.joinpath('direct.private.json').read_bytes(),original)
        self.assertFalse(json.loads(path.read_text())['physical_checks_accepted'])

    def test_multiple_bodies_plan_fresh_unless_selected_and_ancestry_loops_stop(self):
        other = self.root / 'other'
        other.mkdir()
        state = copy.deepcopy(self.prior)
        state['identity']['serial_sha256'] = 'another-body'
        (other / 'direct.private.json').write_text(json.dumps(state))
        # The connected body is unknown before USB opens: plan fresh, keep both.
        self.assertIsNone(factoryrecover.pending(self.root))
        self.assertEqual(factoryrecover.pending(self.root, self.failed)[0], self.failed.resolve())
        self.prior['resume_from'] = str(self.failed)
        self.write_prior()
        with self.assertRaisesRegex(ValueError, 'loop'):
            factoryrecover.chain(self.failed)

    def test_unreadable_or_unattributed_records_never_block_discovery(self):
        broken = self.root / 'broken'; broken.mkdir()
        (broken / 'direct.private.json').write_text('{truncated')
        anonymous = self.root / 'anonymous'; anonymous.mkdir()
        state = copy.deepcopy(self.prior); state['identity'] = {'model': 'ILCE-7CM2'}
        (anonymous / 'direct.private.json').write_text(json.dumps(state))
        for preferred in (None, broken, anonymous):
            with self.subTest(preferred=preferred):
                self.assertEqual(factoryrecover.pending(self.root, preferred)[0], self.failed.resolve())
        self.assertEqual((broken / 'direct.private.json').read_text(), '{truncated')


    def test_host_dispatch_replans_builtin_reset_without_old_worker_dependency(self):
        from desktopapp import worker
        from unittest.mock import Mock
        instance = Mock()
        instance.root = self.root / 'next'
        instance.run_direct.return_value = {'phase': 'AWAITING_RELOAD', 'mode': 'factory_reset'}
        args = dict(workspace=str(instance.root), firmware='2.01', power_confirmed=True)
        with patch('looktool.factoryrecover.pending', return_value=(self.failed, self.prior)), \
             patch('looktool.direct.DirectJob', return_value=instance), \
             patch('desktopapp.official.load', return_value={}):
            result = worker.run('direct_factory_reset', args, self.root)
        instance.run_direct.assert_called_once()
        self.assertEqual(instance.run_direct.call_args.args,('factory_reset',))
        self.assertEqual(instance.run_direct.call_args.kwargs['factory_path'],'builtin')
        self.assertEqual(instance.run_direct.call_args.kwargs['recovery_identity'],self.prior['identity'])
        self.assertEqual(result['phase'], 'AWAITING_RELOAD')

    def dispatch(self, prior, configure):
        """Run the restore button's worker path with one mock job per folder."""
        from desktopapp import worker
        from unittest.mock import Mock
        jobs = {}
        def job(root):
            if Path(root) not in jobs:
                jobs[Path(root)] = Mock(root=Path(root))
                jobs[Path(root)].run_direct.return_value = {'phase': 'AWAITING_RELOAD', 'mode': 'factory_reset'}
                configure(Path(root), jobs[Path(root)])
            return jobs[Path(root)]
        (self.failed / 'direct.private.json').write_text(json.dumps(prior))
        args = dict(workspace=str(self.root / 'next'), firmware='2.01', power_confirmed=True)
        with patch('looktool.factoryrecover.pending', return_value=(self.failed, prior)), \
             patch('looktool.direct.DirectJob', side_effect=job), \
             patch('desktopapp.official.load', return_value={}):
            return worker.run('direct_factory_reset', args, self.root), jobs

    def test_finished_restore_verifies_and_replans_only_when_content_changed(self):
        finished = dict(self.prior, phase='AWAITING_RELOAD')
        loaded = {'phase': 'LOADED', 'mode': 'factory_reset'}
        def verified(root, job):
            job.verify_direct.return_value = loaded
        result, jobs = self.dispatch(finished, verified)
        self.assertEqual(result['phase'], 'LOADED')
        self.assertEqual(result['workspace'], str(self.failed.resolve()))
        jobs[self.root / 'next'].run_direct.assert_not_called()
        def changed(root, job):
            job.verify_direct.side_effect = direct.ContentChanged('Full program readback differs: appFw.so')
        result, jobs = self.dispatch(finished, changed)
        fresh = jobs[self.root / 'next'].run_direct
        fresh.assert_called_once()
        self.assertIsNone(fresh.call_args.kwargs['recovery_identity'])
        self.assertEqual(fresh.call_args.kwargs['recovery_source'], str(self.failed.resolve()))
        # Not yet power-cycled (or any other stop) is reported, never re-planned.
        def not_reloaded(root, job):
            job.verify_direct.side_effect = ValueError('尚未确认新的冷启动。')
        with self.assertRaisesRegex(ValueError, '冷启动'):
            _, jobs = self.dispatch(finished, not_reloaded)

    def test_unfinished_restore_on_another_body_replans_for_the_connected_body(self):
        from looktool.usbidentity import BodyMismatch
        def mismatch(root, job):
            if root.name == 'next':
                job.run_direct.side_effect = BodyMismatch('Current USB body identity differs; no service authentication')
        result, jobs = self.dispatch(self.prior, mismatch)
        first, second = jobs[self.root / 'next'].run_direct, jobs[self.root / 'next-current-body'].run_direct
        self.assertEqual(first.call_args.kwargs['recovery_identity'], self.prior['identity'])
        self.assertIsNone(second.call_args.kwargs['recovery_identity'])
        self.assertEqual(result['workspace'], str(self.root / 'next-current-body'))

    def test_unreadable_selected_record_replans_fresh(self):
        result, jobs = self.dispatch({}, lambda root, job: None)
        (self.failed / 'direct.private.json').write_text('{truncated')
        from desktopapp import worker
        from unittest.mock import Mock
        instance = Mock(root=self.root / 'again')
        instance.run_direct.return_value = {'phase': 'AWAITING_RELOAD', 'mode': 'factory_reset'}
        with patch('looktool.factoryrecover.pending', return_value=None), \
             patch('looktool.direct.DirectJob', return_value=instance), \
             patch('desktopapp.official.load', return_value={}):
            worker.run('direct_resume_factory', dict(workspace=str(instance.root), firmware='2.01',
                       power_confirmed=True, failed_workspace=str(self.failed)), self.root)
        self.assertIsNone(instance.run_direct.call_args.kwargs['recovery_identity'])
