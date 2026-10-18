"""Body identity must survive sessions and reject a different device."""
import sys,types,unittest
from unittest.mock import Mock,patch
from looktool import usbidentity,firmware
from looktool.devicesession import Camera

class IdentityTests(unittest.TestCase):
    def transport(self,serial,index=3):
        dev=types.SimpleNamespace(iSerialNumber=index)
        util=types.SimpleNamespace(get_string=Mock(return_value=serial),dispose_resources=Mock())
        return types.SimpleNamespace(get_device=Mock(return_value=dev),usb=types.SimpleNamespace(util=util)),dev
    def test_descriptor_hash_stable_and_raw_serial_not_returned(self):
        t,dev=self.transport('BODY01234567')
        first=usbidentity.capture(t);second=usbidentity.capture(t)
        self.assertEqual(first,second);self.assertEqual(first,firmware.sha(b'BODY01234567'))
        usbidentity.require_match({'usb_serial_sha256':first,'product_info_sha256':'old-session'},second)
        self.assertEqual(t.usb.util.dispose_resources.call_count,2)
    def test_wrong_body_and_unbound_legacy_job_stop(self):
        for expected in [{'usb_serial_sha256':firmware.sha(b'another-body')},{'product_sha256':'legacy-opaque-response'}]:
            with self.assertRaises(ValueError):usbidentity.require_match(expected,firmware.sha(b'BODY01234567'))
    def test_missing_or_generic_serial_and_descriptor_error_stop_with_cleanup(self):
        for serial in [None,'','000000000000','1234567890','unknown','ILCE-7CM2',' BODY01234567']:
            t,dev=self.transport(serial)
            with self.assertRaises(ValueError):usbidentity.capture(t)
            t.usb.util.dispose_resources.assert_called_once_with(dev)
        t,dev=self.transport('unused');t.usb.util.get_string.side_effect=TimeoutError('descriptor failed')
        with self.assertRaises(TimeoutError):usbidentity.capture(t)
        t.usb.util.dispose_resources.assert_called_once_with(dev)
    def test_connection_does_not_query_opaque_product_for_body_binding(self):
        token=firmware.sha(b'BODY01234567');expected={'model':'ILCE-7CM2','usb_serial_sha256':token}
        t,dev=self.transport('BODY01234567')
        t.ReadinessFailure=type('ReadyFailure',(RuntimeError,),{});t.SonyBusyFailure=type('BusyFailure',(RuntimeError,),{})
        link=Mock();link.identity={'model':'ILCE-7CM2'};link.call.side_effect=[b'a'*88,b'b'*88]
        link.__enter__=Mock(return_value=link);link.__exit__=Mock()
        t.Session=Mock(return_value=link)
        usb=types.ModuleType('usb');usb.__path__=[];usb.core=types.ModuleType('usb.core');usb.core.find=Mock(return_value=dev)
        usb.backend=types.ModuleType('usb.backend');usb.backend.__path__=[]
        usb.backend.libusb1=types.ModuleType('usb.backend.libusb1');usb.backend.libusb1.get_backend=Mock()
        t.libusb_package=types.SimpleNamespace(find_library=Mock())
        with patch.dict(sys.modules,{'usb':usb,'usb.core':usb.core,'usb.backend':usb.backend,'usb.backend.libusb1':usb.backend.libusb1}),patch('looktool.devicesession.modules',return_value=(t,types.SimpleNamespace(MODEL='ILCE-7CM2'))):
            one=Camera(expected)._connect();two=Camera(expected)._connect()
            link.call.assert_not_called()
            self.assertEqual(one.identity['usb_serial_sha256'],two.identity['usb_serial_sha256'])
            t.Session.reset_mock()
            with self.assertRaises(ValueError):Camera(dict(expected,usb_serial_sha256='different-body'))._connect()
            t.Session.assert_not_called()

if __name__=='__main__':unittest.main()
