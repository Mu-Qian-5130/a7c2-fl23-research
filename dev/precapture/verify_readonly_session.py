"""Offline fake-transport controls; importing this file never opens USB."""
import struct
from types import SimpleNamespace
import unittest
from support.readonly_session import session_class

PATH = '/tmp/jiritsu/../../cp/cpapp-b.bin'
OTHER = '/tmp/jiritsu/../../usr/lib/appFw.so'


class ReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        events = self.events
        class Camera:
            def getBackupPresetData(self, memory):
                events.append(('snapshot', memory)); return b'settings'
            def writeBackup(self, *args):
                raise AssertionError('Parameter write reached device')
        class Channel:
            def sendSenserPacket(self, function, packet):
                events.append(('packet', function, packet)); return 0, struct.pack('<I', 0)+b'file'
        class Base:
            def __init__(self, expected=None):
                self.healthy = True; self.camera = Camera(); self.channel = Channel()
                self.dev = object(); self.expected = expected
                self.auth = SimpleNamespace(stop=lambda: events.append(('stop',)))
            def __enter__(self):
                events.append(('entry',)); return self
            def __exit__(self, *args):
                raise AssertionError('Base exit/rescue reached')
            def call(self, method, *args):
                if not self.healthy: raise RuntimeError('Unknown session outcome')
                try: return method(*args)
                except BaseException: self.healthy = False; raise
            def jiritsu(self, cmd, data=b'', missing=False):
                return self.call(self.channel.sendSenserPacket, 0x40,
                                 struct.pack('<HH', 0x1001, cmd)+data)
            def select(self, path):
                return self.jiritsu(15, b'\0'+path.encode('ascii')+b'\0')
            def read(self, path):
                self.select(path); return self.jiritsu(17, b'\0\xff\0')
        self.transport = SimpleNamespace(Session=Base,
            SonySenserDevice=SimpleNamespace(RESPONSE_FRAMING='length-delimited-zlp/1'),
            usb=SimpleNamespace(util=SimpleNamespace(dispose_resources=lambda d: events.append(('dispose',)))),
            time=SimpleNamespace(monotonic=lambda: 123), _service_exit=0)
        self.cls = session_class(self.transport)
        self.s = self.cls([PATH])

    def test_named_file_and_both_snapshot_modes(self):
        with self.s as s:
            s.read(PATH)
            for memory in (True, False):
                self.assertEqual(s.call(s.camera.getBackupPresetData, memory), b'settings')
        self.assertEqual(len([e for e in self.events if e[0]=='packet']), 2)
        self.assertEqual(self.events[-2:], [('stop',), ('dispose',)])
        self.assertEqual(self.transport._service_exit, 123)

    def test_invalid_paths_stop_before_entry(self):
        for paths in ([], ['/etc/passwd'], [PATH+'\0'], [PATH+'é'], [PATH+'a'*512]):
            with self.subTest(paths=paths), self.assertRaises(ValueError): self.cls(paths)
        self.assertEqual(self.events, [])

    def test_old_reply_parser_not_admitted(self):
        self.transport.SonySenserDevice.RESPONSE_FRAMING='old'
        with self.assertRaises(ValueError): session_class(self.transport)

    def test_missing_reply_parser_marker_not_admitted(self):
        del self.transport.SonySenserDevice.RESPONSE_FRAMING
        with self.assertRaises(ValueError): session_class(self.transport)

    def test_reviewed_v3_file_parser_is_admitted_without_device_entry(self):
        self.transport.SonySenserDevice.RESPONSE_FRAMING='length-delimited-zlp/3'
        session_class(self.transport)([PATH])
        self.assertEqual(self.events, [])

    def test_other_file_is_rejected_before_packet(self):
        with self.assertRaises(ValueError): self.s.read(OTHER)
        self.assertEqual(self.events, [])

    def test_write_remove_and_other_jiritsu_commands_blocked(self):
        for command in (0, 16, 18, 19):
            with self.subTest(command=command), self.assertRaises(ValueError): self.s.jiritsu(command, b'data')
        self.assertEqual(self.events, [])

    def test_direct_packet_cannot_bypass_path_or_command_guard(self):
        for packet in (struct.pack('<HH',0x1001,16)+b'payload',
                       struct.pack('<HH',0x1001,18)+b'\0\xff',
                       struct.pack('<HH',0x1001,15)+b'\0'+OTHER.encode()+b'\0',
                       struct.pack('<HH',0x1001,17)+b'\0\xff\0', b''):
            with self.subTest(packet=packet), self.assertRaises(ValueError):
                self.s.call(self.s.channel.sendSenserPacket,0x40,packet)
        self.assertEqual(self.events, [])

    def test_write_settings_and_wrong_snapshot_argument_blocked(self):
        with self.assertRaises(ValueError): self.s.call(self.s.camera.writeBackup,0,b'x')
        for value in (0, 1, None, b''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.s.call(self.s.camera.getBackupPresetData,value)
        self.assertEqual(self.events, [])

    def test_same_method_name_on_other_owner_is_not_admitted(self):
        class Impostor:
            def getBackupPresetData(self, memory): raise AssertionError('Impostor called')
        with self.assertRaises(ValueError): self.s.call(Impostor().getBackupPresetData,True)
        self.assertEqual(self.events, [])

    def test_unknown_exchange_exits_without_stop_rescue_or_reauthentication(self):
        with self.s as s:
            s.healthy=False
        self.assertEqual(self.events, [('entry',), ('dispose',)])
        self.assertEqual(self.transport._service_exit,0)

    def test_failed_stop_is_not_repeated(self):
        def fail(): self.events.append(('failed-stop',)); raise TimeoutError('unknown stop')
        self.s.auth.stop=fail
        with self.assertRaises(TimeoutError):
            with self.s: pass
        self.assertFalse(self.s.healthy)
        self.assertEqual(self.events,[('entry',),('failed-stop',),('dispose',)])

    def test_failed_selection_never_admits_subsequent_read(self):
        self.s.read(PATH)
        original=self.s.call
        def fail(method,*args):
            self.s.healthy=False;raise TimeoutError('unknown selection')
        self.s.call=fail
        with self.assertRaises(TimeoutError): self.s.select(PATH)
        self.s.call=original
        self.assertIsNone(self.s._selected)
        before=list(self.events)
        with self.assertRaises(ValueError):self.s.jiritsu(17,b'\0\xff\0')
        self.assertEqual(self.events,before)


if __name__ == '__main__': unittest.main()
