"""Readiness/busy protocol simulations; no USB enumeration or camera access."""
import importlib.util
from contextlib import ExitStack
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from test_initial_usb_diagnostic import FakeDevice, ROOT
import usb.core

spec = importlib.util.spec_from_file_location('ready_diag', ROOT / 'dev/usb/initial-usb-v2/diagnose_initial_usb.py')
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)


class Clock:
    def __init__(self):
        self.value = 100

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class ReadyDevice(FakeDevice):
    def __init__(self, not_ready=0, sony_busy=0, readiness_error=None, timeout_payload=False):
        super().__init__()
        self.not_ready = not_ready
        self.sony_busy = sony_busy
        self.readiness_error = readiness_error
        self.timeout_payload = timeout_payload
        self.status = 0
        self.sense = (0, 0, 0)

    def write(self, ep, data, timeout):
        count = super().write(ep, data, timeout)
        if len(data) == 31 and data[:4] == b'USBC':
            self.status = 0
            if self.op == 0:
                if self.readiness_error:
                    self.sense = self.readiness_error
                    self.status = 1
                elif self.not_ready:
                    self.not_ready -= 1
                    self.sense = (2, 4, 1)
                    self.status = 1
            elif self.op == 0x7a and self.direction == 0 and self.sony_busy:
                self.sony_busy -= 1
                self.sense = (9, 0x81, 0x81)
                self.status = 1
        elif self.timeout_payload and self.op == 0x7a:
            raise usb.core.USBTimeoutError('Operation timed out', error_code=-7, errno=10060)
        return count

    def read(self, ep, length, timeout):
        if length == 13:
            return struct.pack('<4sIIB', b'USBS', 0, 8192 if self.op == 0x7a and self.status else 0, self.status)
        if self.op == 3:
            key, asc, ascq = self.sense
            return bytes([0x70, 0, key] + [0] * 9 + [asc, ascq] + [0] * 4)
        return super().read(ep, length, timeout)

    def opcodes(self):
        return [p[15] for p in self.writes if len(p) == 31 and p[:4] == b'USBC']


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = Clock()
        context = ExitStack()
        self.addCleanup(context.close)
        context.enter_context(patch.object(diag.time, 'monotonic', self.clock.monotonic))
        context.enter_context(patch.object(diag.time, 'sleep', self.clock.sleep))
        self.report = diag.Report(Path(self.tmp.name) / 'report.json')
        self.backend_type = diag.make_backend_type()

    def query(self, device):
        return diag.query_initial(device, self.report, self.backend_type)

    def test_ready_camera_queries_same_read_only_commands(self):
        device = ReadyDevice()
        self.query(device)
        self.assertEqual(device.opcodes(), [0, 0x12, 0x12, 0, 0x7a, 0x7a])
        self.assertEqual(self.report.data['events'][-1]['kind'], 'camera_info_ok')
        self.assertNotIn('deadbeef', self.report.path.read_text(encoding='utf-8'))

    def test_becoming_ready_is_waited_before_inquiry_or_sony_extension(self):
        device = ReadyDevice(not_ready=3)
        self.query(device)
        self.assertEqual(device.opcodes()[:7], [0, 3, 0, 3, 0, 3, 0])
        events = [e for e in self.report.data['events'] if e['kind'] == 'readiness']
        self.assertEqual([e['sense'] for e in events[:4]], [[2, 4, 1]] * 3 + [[0, 0, 0]])
        self.assertGreaterEqual(self.clock.value, 103)

    def test_always_not_ready_stops_without_sony_query(self):
        device = ReadyDevice(not_ready=100)
        with self.assertRaises(diag.ReadinessFailure):
            self.query(device)
        self.assertNotIn(0x7a, device.opcodes())
        self.assertNotIn(0x12, device.opcodes())
        self.assertEqual(self.clock.value, 130)

    def test_missing_media_does_not_retry(self):
        device = ReadyDevice(readiness_error=(2, 0x3a, 0))
        with self.assertRaises(diag.ReadinessFailure):
            self.query(device)
        self.assertEqual(device.opcodes(), [0, 3])

    def test_sony_busy_after_ready_has_separate_bounded_failure(self):
        device = ReadyDevice(sony_busy=100)
        with self.assertRaises(diag.SonyBusyFailure):
            self.query(device)
        statuses = [e for e in self.report.data['events'] if e['kind'] == 'sony_query_status']
        self.assertEqual(len(statuses), 10)
        self.assertTrue(all(e['sense'] == [9, 0x81, 0x81] for e in statuses))
        self.assertFalse(any(e['kind'] == 'usb_error' for e in self.report.data['events']))

    def test_sony_busy_then_ready_completes_without_authentication(self):
        device = ReadyDevice(sony_busy=2)
        self.query(device)
        self.assertEqual(self.clock.value, 102)
        self.assertEqual(device.opcodes(), [0, 0x12, 0x12, 0, 0x7a, 3, 0x7a, 3, 0x7a, 0x7a])
        self.assertFalse(self.report.data['service_authentication'])

    def test_payload_timeout_aborts_before_further_command(self):
        device = ReadyDevice(timeout_payload=True)
        with self.assertRaises(diag.DiagnosticUsbFailure):
            self.query(device)
        self.assertEqual(device.opcodes(), [0, 0x12, 0x12, 0, 0x7a])
        self.assertEqual(self.report.data['events'][-1]['kind'], 'usb_error')


if __name__ == '__main__':
    unittest.main()
