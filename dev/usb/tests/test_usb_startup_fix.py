"""Initial-query replay and offline host update guards; never enumerate USB."""
import ast
import base64
from contextlib import ExitStack, redirect_stdout
import hashlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_initial_usb_readiness import Clock, ReadyDevice, ROOT
import usb.core

from test_initial_usb_diagnostic import PACKAGE_ROOT
sys.path.insert(0, str(PACKAGE_ROOT))
FOLDER = ROOT / 'dev/usb/usb-startup-fix-v1'
ORIGINAL = (ROOT / 'dev/usb/tests/fixtures/transport-original.py').read_bytes()
PATCHED = (FOLDER / 'transport.py').read_bytes()


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


runtime = module(FOLDER / 'transport.py', 'startup_fixed_transport')
updater = module(FOLDER / 'apply_fix.py', 'startup_updater')
updater.PATCHED_SHA = hashlib.sha256(PATCHED).hexdigest()
updater.PATCHED_B64 = base64.b64encode(PATCHED).decode('ascii')


class ReportedDevice(ReadyDevice):
    """Replay v2: becoming-ready, then one read stall + Sony busy, then success."""
    def __init__(self):
        super().__init__(not_ready=1)
        self.stalled = False

    def read(self, ep, length, timeout):
        if self.op == 0x7a and self.direction == 0x80 and length == 8192 and not self.stalled:
            self.stalled = True
            self.status = 1
            self.sense = (9, 0x81, 0x81)
            raise usb.core.USBError('Pipe error', error_code=-9, errno=32)
        return super().read(ep, length, timeout)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        context = ExitStack()
        self.addCleanup(context.close)
        self.clock = Clock()
        context.enter_context(patch.object(runtime.time, 'monotonic', self.clock.monotonic))
        context.enter_context(patch.object(runtime.time, 'sleep', self.clock.sleep))
        context.enter_context(patch.object(runtime, 'SonySenserAuthDevice', side_effect=AssertionError('No auth in identity')))

    def identify(self, device):
        with patch.object(runtime, 'get_device', return_value=device), redirect_stdout(io.StringIO()):
            return runtime.identity()

    def test_reported_success_sequence_reads_identity_and_preserves_binding(self):
        device = ReportedDevice()
        result = self.identify(device)
        self.assertEqual(result, {'model': 'ILCE-7CM2', 'serial_sha256': hashlib.sha256(b'deadbeef').hexdigest()})
        self.assertGreaterEqual(self.clock.value, 102)
        self.assertEqual(device.halts, [0x81])

    def test_pending_camera_never_receives_sony_query(self):
        device = ReadyDevice(not_ready=100)
        with self.assertRaises(runtime.ReadinessFailure):
            self.identify(device)
        self.assertNotIn(0x7a, device.opcodes())

    def test_busy_response_is_bounded(self):
        with self.assertRaises(runtime.SonyBusyFailure):
            self.identify(ReadyDevice(sony_busy=100))
        self.assertEqual(self.clock.value, 110)

    def test_timeout_does_not_trigger_stall_recovery_or_another_command(self):
        device = ReadyDevice(timeout_payload=True)
        with self.assertRaises(usb.core.USBTimeoutError):
            self.identify(device)
        self.assertEqual(device.opcodes(), [0, 0x12, 0x12, 0, 0x7a])
        self.assertEqual(device.halts, [])

    def test_service_and_write_transport_ast_is_unchanged(self):
        def nodes(blob):
            return {n.name: ast.dump(n, include_attributes=False) for n in ast.parse(blob).body
                    if isinstance(n, (ast.ClassDef, ast.FunctionDef))}
        old, new = nodes(ORIGINAL), nodes(PATCHED)
        for name in ('Bounded', 'get_device', 'Session'):
            self.assertEqual(old[name], new[name], name)


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='usb fix check ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'app.py').write_text('# test fixture', encoding='utf-8')
        vendor = self.root / 'vendor/pmca/usb'
        vendor.mkdir(parents=True)
        (vendor / 'sony.py').write_text('# fixture', encoding='utf-8')
        self.target = self.root / 'transport.py'
        self.target.write_bytes(ORIGINAL)
        self.backup = self.root / 'transport.py.before-usb-startup-fix-v1.bak'

    def apply(self):
        with redirect_stdout(io.StringIO()):
            updater.apply_fix(self.root)

    def test_update_preserves_original_and_repeated_run_is_noop(self):
        self.apply()
        self.assertEqual(self.backup.read_bytes(), ORIGINAL)
        self.assertEqual(self.target.read_bytes(), PATCHED)
        self.apply()
        self.assertEqual(self.backup.read_bytes(), ORIGINAL)

    def test_unknown_transport_is_rejected(self):
        self.target.write_bytes(b'# modified')
        with self.assertRaises(RuntimeError):
            self.apply()
        self.assertEqual(self.target.read_bytes(), b'# modified')
        self.assertFalse(self.backup.exists())

    def test_conflicting_backup_is_preserved_and_update_rejected(self):
        self.backup.write_bytes(b'# another backup')
        with self.assertRaises(RuntimeError):
            self.apply()
        self.assertEqual(self.target.read_bytes(), ORIGINAL)
        self.assertEqual(self.backup.read_bytes(), b'# another backup')

    def test_replace_failure_keeps_original_and_backup(self):
        with patch.object(updater.os, 'replace', side_effect=OSError('simulated failure')):
            with self.assertRaises(OSError):
                self.apply()
        self.assertEqual(self.target.read_bytes(), ORIGINAL)
        self.assertEqual(self.backup.read_bytes(), ORIGINAL)
        self.assertEqual(list(self.root.glob('.usb-startup-*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
