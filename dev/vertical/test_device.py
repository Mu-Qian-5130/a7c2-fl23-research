"""Offline host transaction tests. No USB modules or private firmware fixtures."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/vertical'))
from verticaltool import device


class Fixture:
    def __init__(self, aliases=0, running=1):
        self.mask, self.running = aliases, running
        self.healthy = True
        self.calls = []
        self.mismatch = False
        self.unknown_add = False
        self.unknown_read = False
        self.saved = '01'
        self.connection_failure = False
        self.originals = [bytes([65 + i]) * (20 + i) for i in range(3)]
        self.identity = dict(model='ILCE-7CM2', usb_serial_sha256='synthetic-test-body')

    def camera(self, expected=None):
        fixture = self

        class Camera:
            identity = fixture.identity
            identity_pending = False
            link = fixture

            def __enter__(self):
                if fixture.connection_failure:
                    raise OSError('Connection unavailable before any native operation')
                if expected is not None and expected != self.identity:
                    raise ValueError('Different body')
                return self

            def __exit__(self, *args):
                pass

            def pin_programs(self, ap, cp):
                assert self.byte_checks and ap == b'AP' and cp == b'CP'

            def read(self, path, missing=False):
                if path in ('/usr/lib/appFw.so', '/cp/cpapp-b.bin'):
                    return b'AP' if path.endswith('.so') else b'CP'
                if path in device.SOURCES:
                    return fixture.originals[device.SOURCES.index(path)]
                assert path in device.ALIASES
                i = device.ALIASES.index(path)
                if not fixture.mask & (1 << i):
                    assert missing
                    return None
                if fixture.unknown_read:
                    fixture.healthy = False
                    raise OSError('USB read outcome unknown')
                return b'wrong' if fixture.mismatch else fixture.originals[i]

            def snapshot(self, memory):
                return memory

            def records(self, raw):
                return [{device.SETTING: SimpleNamespace(data=bytes.fromhex(fixture.saved), attr=64)}]

        return Camera()

    def workers(self, camera, journal):
        fixture = self

        class Workers:
            def probe(self):
                fixture.calls.append(('probe', fixture.running))
                return dict(status=0, model_index=16, value=fixture.running, info_hex='00' * 24)

            def ram(self, target):
                fixture.calls.append(('ram', target))
                before = fixture.running
                fixture.running = target
                return dict(status=0, before=before, after=target, wrote=int(before != target))

            def aliases(self, mode):
                fixture.calls.append(('aliases', mode))
                prior = fixture.mask
                if mode == 1:
                    assert prior == 0
                    if fixture.unknown_add:
                        fixture.mask = 1
                        fixture.healthy = False
                        raise OSError('Native alias result unknown')
                    fixture.mask = 7
                elif mode == 2:
                    fixture.mask = 0
                result = dict(mode=mode, phase=1 if mode == 0 else 5, status=0,
                    rollback=0, readonly=0, source_ok=7, prior=prior,
                    created=7 if mode == 1 else 0, removed=prior if mode == 2 else 0,
                    source_sizes=list(map(len, fixture.originals)), source_counts=[3, 4, 5])
                journal.report['last_alias_result'] = result
                return result

        return Workers()


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_command(self, fixture, command):
        return device.execute(command, self.folder, camera_factory=fixture.camera,
                              workers_factory=fixture.workers)

    def state(self):
        return json.loads((self.folder / 'state.private.json').read_text(encoding='utf-8'))

    def test_first_enable_full_readback_and_small_journal(self):
        fixture = Fixture()
        result = self.run_command(fixture, 'enable')
        self.assertEqual((result['running'], result['saved'], result['alias_count']), ('ON', 'OFF', 3))
        self.assertEqual(fixture.calls.count(('aliases', 1)), 1)
        self.assertEqual(self.state()['phase'], 'complete')
        self.assertFalse(any(p.name in ('appFw.so', 'cpapp-b.bin') for p in self.folder.rglob('*')))

    def test_reenable_existing_resources_after_reload(self):
        fixture = Fixture(aliases=7)
        self.run_command(fixture, 'enable')
        self.assertNotIn(('aliases', 1), fixture.calls)
        self.assertEqual(fixture.running, 0)

    def test_disable_keeps_resources(self):
        fixture = Fixture(aliases=7, running=0)
        self.run_command(fixture, 'disable')
        self.assertEqual((fixture.running, fixture.mask), (1, 7))
        self.assertNotIn(('aliases', 2), fixture.calls)

    def test_remove_disables_before_unlinking(self):
        fixture = Fixture(aliases=7, running=0)
        result = self.run_command(fixture, 'remove')
        self.assertEqual((fixture.running, fixture.mask, result['alias_count']), (1, 0, 0))
        self.assertLess(fixture.calls.index(('ram', 1)), fixture.calls.index(('aliases', 2)))

    def test_status_has_no_ram_or_alias_mutations(self):
        fixture = Fixture(aliases=7, running=0)
        self.run_command(fixture, 'status')
        self.assertFalse(any(op == 'ram' or op == 'aliases' and mode for op, mode in fixture.calls))

    def test_partial_aliases_require_explicit_remove(self):
        fixture = Fixture(aliases=3)
        with self.assertRaisesRegex(ValueError, 'Partial aliases'):
            self.run_command(fixture, 'enable')
        self.assertEqual(fixture.mask, 3)
        self.run_command(fixture, 'remove')
        self.assertEqual(fixture.mask, 0)

    def test_known_readback_failure_removes_new_aliases(self):
        fixture = Fixture()
        fixture.mismatch = True
        with self.assertRaisesRegex(ValueError, 'readback differs'):
            self.run_command(fixture, 'enable')
        self.assertEqual((fixture.mask, fixture.running), (0, 1))

    def test_unknown_native_result_is_not_retried_or_cleaned(self):
        fixture = Fixture()
        fixture.unknown_add = True
        with self.assertRaisesRegex(OSError, 'result unknown'):
            self.run_command(fixture, 'enable')
        self.assertEqual(fixture.calls.count(('aliases', 1)), 1)
        self.assertNotIn(('aliases', 2), fixture.calls)
        self.assertEqual(self.state()['phase'], 'needs_review')
        with self.assertRaisesRegex(ValueError, 'needs review'):
            self.run_command(fixture, 'enable')

    def test_unknown_readback_preserves_evidence_and_resources(self):
        fixture = Fixture()
        fixture.unknown_read = True
        with self.assertRaises(OSError):
            self.run_command(fixture, 'enable')
        self.assertEqual(fixture.mask, 7)
        self.assertNotIn(('aliases', 2), fixture.calls)

    def test_saved_on_is_preserved_without_any_write(self):
        fixture = Fixture()
        fixture.saved = '00'
        with self.assertRaisesRegex(ValueError, 'setting OFF'):
            self.run_command(fixture, 'enable')
        self.assertEqual((fixture.saved, fixture.mask, fixture.running), ('00', 0, 1))

    def test_connection_failure_can_retry_same_folder(self):
        fixture = Fixture()
        fixture.connection_failure = True
        with self.assertRaises(OSError):
            self.run_command(fixture, 'enable')
        self.assertEqual(self.state()['phase'], 'failed_before_change')
        fixture.connection_failure = False
        self.run_command(fixture, 'enable')

    def test_status_does_not_clear_unresolved_operation(self):
        fixture = Fixture(aliases=7)
        device.save_json(self.folder / 'state.private.json', dict(phase='needs_review', identity=fixture.identity))
        self.run_command(fixture, 'status')
        self.assertEqual(self.state()['phase'], 'needs_review')


class DecodingTests(unittest.TestCase):
    def test_incomplete_results(self):
        for parse in (device.parse_probe, lambda raw: device.parse_ram(raw, 0),
                      lambda raw: device.parse_aliases(raw, 0)):
            with self.subTest(parse=parse), self.assertRaises(ValueError):
                parse(b'partial')

    def test_malformed_successful_ram_write(self):
        raw = struct.pack('<8sIIqQIIII24s', b'A7VTR001', 1, 16, 0, device.VALUE_RVA, 1, 1, 0, 1, bytes(24))
        with self.assertRaises(ValueError):
            device.parse_ram(raw, 0)

    def test_help_and_wrong_version_never_import_device_transport(self):
        spec = importlib.util.spec_from_file_location('vertical_entry', ROOT / 'vertical.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for args, expected in [(['--help'], 0), (['enable', '--firmware-version', '3.00'], 2)]:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as stopped:
                    module.main(args)
            self.assertEqual(stopped.exception.code, expected)


if __name__ == '__main__':
    unittest.main()
