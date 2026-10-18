"""Offline protocol/failure tests. Never enumerate USB hardware."""
import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = ROOT / 'src/fl23'
sys.path[:0] = [str(PACKAGE_ROOT / 'vendor'), str(PACKAGE_ROOT)]
spec = importlib.util.spec_from_file_location('initial_diag', ROOT / 'dev/usb/initial-usb-v1/diagnose_initial_usb.py')
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)
import usb.core
from pmca.usb.sony import SonyExtCmdCamera


class FakeDevice:
    """Minimal MSC target; no serial or raw response may appear in the report."""
    def __init__(self, scenario='success'):
        self.scenario = scenario
        self.writes = []
        self.halts = []
        self.op = None
        self.direction = None
        self._ctx = SimpleNamespace(dispose=lambda _: None)
        self.endpoints = [SimpleNamespace(bmAttributes=2, bEndpointAddress=n) for n in (0x81, 2)]

    def is_kernel_driver_active(self, _):
        raise NotImplementedError()

    def get_active_configuration(self):
        return {(0, 0): self.endpoints}

    def clear_halt(self, ep):
        self.halts.append(ep)

    def write(self, ep, data, timeout):
        self.writes.append(bytes(data))
        if len(data) == 31 and data[:4] == b'USBC':
            self.op, self.direction = data[15], data[12]
            if self.op == 3 and self.scenario == 'sense_timeout':
                raise usb.core.USBTimeoutError('Operation timed out', error_code=-7, errno=10060)
        return len(data)

    def read(self, ep, length, timeout):
        if length == 13:
            status = int(self.op == 0x7a and self.direction == 0 and self.scenario != 'success')
            return struct.pack('<4sIIB', b'USBS', 0, 0, status)
        if self.op == 0x12:
            data = bytearray(36)
            data[4] = 31
            data[8:16] = b'Sony    '
            data[16:32] = b'DSC             '
            return data[:length]
        if self.op == 3:
            return bytes([0x70, 0, 5] + [0] * 9 + [0x20, 0] + [0] * 4)
        if self.op == 0x7a:
            model = b'ILCE-7CM2'
            data = struct.pack('<I', 0) + b'\0' * 4 + bytes([len(model)]) + model + b'abcde' + b'\xde\xad\xbe\xef'
            return (SonyExtCmdCamera.ExtCmdHeader.pack(dataSize=len(data), cmd=1, direction=1) + data).ljust(length, b'\0')
        raise AssertionError('Unexpected command')


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.report = diag.Report(Path(self.tmp.name) / 'report.json')
        self.backend_type = diag.make_backend_type()

    def test_success_queries_only_initial_information_without_logging_serial(self):
        device = FakeDevice()
        diag.query_initial(device, self.report, self.backend_type)
        self.assertEqual(self.report.data['events'][-1]['kind'], 'camera_info_ok')
        opcodes = [p[15] for p in device.writes if len(p) == 31 and p[:4] == b'USBC']
        self.assertEqual(opcodes, [0, 0x12, 0x12, 0, 0x7a, 0x7a])
        # Device serial, raw payloads and host body paths must not leak.
        text = self.report.path.read_text(encoding='utf-8')
        self.assertNotIn('deadbeef', text)
        self.assertNotIn('abcde', text)
        self.assertFalse(self.report.data['service_authentication'])

    def test_issue_request_sense_timeout_preserves_prior_csw_and_stops(self):
        device = FakeDevice('sense_timeout')
        with self.assertRaises(diag.DiagnosticUsbFailure):
            diag.query_initial(device, self.report, self.backend_type)
        self.assertEqual(device.writes[-1][15], 3)
        self.assertEqual(device.halts, [])
        statuses = [e['csw']['status'] for e in self.report.data['events'] if 'csw' in e]
        self.assertEqual(statuses[-1], 1)
        error = self.report.data['events'][-1]
        self.assertEqual(error['kind'], 'usb_error')
        self.assertEqual(error['backend_error_code'], -7)
        self.assertEqual(error['errno'], 10060)

    def test_sense_code_captured_without_raw_sense_buffer(self):
        device = FakeDevice('sense_error')
        with self.assertRaises(Exception):
            diag.query_initial(device, self.report, self.backend_type)
        sense = [e['sense'] for e in self.report.data['events'] if 'sense' in e]
        self.assertEqual(sense, [{'key': 5, 'asc': 0x20, 'ascq': 0}])

    def test_expired_budget_sends_no_transfer(self):
        device = FakeDevice()
        backend = self.backend_type(device, self.report, budget=-1)
        with self.assertRaises(diag.DiagnosticUsbFailure):
            backend.write(2, b'query')
        self.assertEqual(device.writes, [])

    def test_backend_refuses_to_recover_timeout_but_allows_pipe_handling(self):
        from pmca.usb.driver.generic import GenericUsbException
        backend = self.backend_type(FakeDevice(), self.report)
        error = usb.core.USBError('Pipe error', error_code=-9, errno=32)
        with self.assertRaises(GenericUsbException):
            backend.failure('write', 2, error)
        self.assertEqual(self.report.data['events'][-1]['backend_error_code'], -9)

    def test_main_failure_redacts_paths_and_leaves_report(self):
        with patch.object(diag, 'BASE', Path(self.tmp.name)), patch.object(diag, 'probe',
                side_effect=RuntimeError(str(Path(self.tmp.name) / 'private') + ' ' + str(Path.home()))):
            self.assertEqual(diag.main(), 1)
        reports = list((Path(self.tmp.name) / 'diagnostic-reports').glob('*.json'))
        self.assertEqual(len(reports), 1)
        text = reports[0].read_text(encoding='utf-8')
        self.assertIn('<TOOL_DIR>', text)
        self.assertIn('<USER_DIR>', text)
        self.assertNotIn(str(Path.home()).replace('\\', '\\\\'), text)


if __name__ == '__main__':
    unittest.main()
