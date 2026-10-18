"""Query initial MSC information only; no authentication or firmware operations.

Extract beside the preview package's Start.cmd and use Diagnose-Initial-USB.cmd.
Report USB transfer metadata, never raw camera response bodies or serial numbers.
"""
import json
from pathlib import Path
import platform
import re
import struct
import sys
import time
import traceback
from datetime import datetime, timezone
from uuid import uuid4

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / 'vendor'))


class DiagnosticUsbFailure(RuntimeError):
    pass


class Report:
    def __init__(self, path):
        self.path = Path(path)
        self.started = time.monotonic()
        self.data = {
            'diagnostic': 'initial-usb-v1',
            'utc': datetime.now(timezone.utc).isoformat(),
            'python': platform.python_version(),
            'python_bits': struct.calcsize('P') * 8,
            'windows': list(platform.win32_ver()),
            'service_authentication': False,
            'firmware_or_settings_writes': False,
            'raw_camera_payloads_logged': False,
            'events': [],
        }
        self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding='utf-8')

    def event(self, kind, **fields):
        self.data['events'].append({'seconds': round(time.monotonic() - self.started, 3),
                                    'kind': kind, **fields})
        self.save()


def redact(text):
    for path, label in [(str(BASE), '<TOOL_DIR>'), (str(Path.home()), '<USER_DIR>')]:
        text = re.sub(re.escape(path), lambda _: label, text, flags=re.IGNORECASE)
    return text


def make_backend_type():
    import usb.core
    from pmca.usb.driver.generic import GenericUsbException
    from pmca.usb.driver.generic.libusb import UsbBackend

    class TracedBackend(UsbBackend):
        def __init__(self, device, report, budget=20):
            super().__init__(device)
            self.report = report
            self.deadline = time.monotonic() + budget

        def timeout(self, requested=None):
            remaining = int((self.deadline - time.monotonic()) * 1000)
            if remaining <= 0:
                raise DiagnosticUsbFailure('Initial MSC diagnostic exceeded its time budget; stopped.')
            return max(1, min(remaining, requested if requested is not None else 5000))

        def reset(self):
            # Upstream reset() only detaches a kernel driver where supported;
            # it does not issue a physical USB device reset.
            self.report.event('backend_initialize')
            return super().reset()

        def clearHalt(self, ep):
            self.report.event('clear_endpoint_halt', endpoint=ep)
            return super().clearHalt(ep)

        def failure(self, operation, ep, exc):
            self.report.event('usb_error', operation=operation, endpoint=ep,
                              error=type(exc).__name__, message=str(exc),
                              errno=getattr(exc, 'errno', None),
                              backend_error_code=getattr(exc, 'backend_error_code', None))
            # Upstream treats every USB error as a recoverable stall. Here only
            # PIPE may follow that path; timeout/disconnect aborts all MSC I/O.
            if getattr(exc, 'backend_error_code', None) == -9:
                raise GenericUsbException('USB endpoint stalled') from exc
            raise DiagnosticUsbFailure('USB transfer failed; no further commands sent.') from exc

        def write(self, ep, data):
            meta = {'endpoint': ep, 'length': len(data)}
            if len(data) == 31 and data[:4] == b'USBC':
                meta['cbw'] = {'opcode': hex(data[15]), 'transfer_bytes': struct.unpack_from('<I', data, 8)[0],
                               'direction': 'in' if data[12] & 0x80 else 'out', 'lun': data[13]}
            self.report.event('bulk_write_begin', **meta)
            try:
                count = self.dev.write(ep, data, timeout=self.timeout())
            except usb.core.USBError as exc:
                self.failure('write', ep, exc)
            self.report.event('bulk_write_end', transferred=count)

        def read(self, ep, length, timeout=None):
            self.report.event('bulk_read_begin', endpoint=ep, requested=length)
            try:
                data = bytes(self.dev.read(ep, length, timeout=self.timeout(timeout)))
            except usb.core.USBError as exc:
                self.failure('read', ep, exc)
            meta = {'received': len(data)}
            if length == 13 and len(data) == 13 and data[:4] == b'USBS':
                meta['csw'] = {'residue': struct.unpack_from('<I', data, 8)[0], 'status': data[12]}
            # SCSI sense codes do not contain image data or a serial number.
            if length == 18 and len(data) >= 14 and data[0] & 0x7f in (0x70, 0x71):
                meta['sense'] = {'key': data[2] & 0xf, 'asc': data[12], 'ascq': data[13]}
            self.report.event('bulk_read_end', **meta)
            return data

    return TracedBackend


def query_initial(device, report, backend_type):
    from pmca.usb import MscDevice
    from pmca.usb.driver.generic import MscBbbDriver
    from pmca.usb.sony import SonyExtCmdCamera, SonyMscExtCmdDevice

    driver = MscBbbDriver(backend_type(device, report))
    report.event('stage', name='scsi_inquiry')
    info = MscDevice(driver).getDeviceInfo()
    report.event('inquiry_ok', manufacturer=info.manufacturer.strip(), product=info.model.strip())
    if info.manufacturer.strip() != 'Sony':
        raise RuntimeError('Unexpected SCSI manufacturer; stopped before Sony extension.')
    report.event('stage', name='sony_get_camera_info')
    info = SonyExtCmdCamera(SonyMscExtCmdDevice(driver)).getCameraInfo()
    # Do not persist info.serial, modelCode, plist, or raw transfer payloads.
    report.event('camera_info_ok', model=info.modelName)
    if info.modelName != 'ILCE-7CM2':
        raise RuntimeError('Unexpected model; this diagnostic is for ILCE-7CM2 only.')


def probe(report):
    import usb.core
    import usb.util
    import usb.backend.libusb1
    import libusb_package

    backend = usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)
    if backend is None:
        raise RuntimeError('libusb is unavailable.')
    device = None
    try:
        # Only normal-mode target devices; never open 0336 or another Sony PID.
        found = list(usb.core.find(find_all=True, idVendor=0x054c, idProduct=0x0e8a, backend=backend))
        report.event('target_count', count=len(found), vid='054c', pid='0e8a')
        if len(found) != 1:
            raise RuntimeError('Connect exactly one 054C:0E8A camera in Mass Storage mode.')
        device = found[0]
        configs = list(device)
        report.event('descriptors', bcd_usb=device.bcdUSB, bcd_device=device.bcdDevice,
                     configurations=[{'value': c.bConfigurationValue,
                                      'interfaces': [{'number': i.bInterfaceNumber, 'alternate': i.bAlternateSetting,
                                                      'class': i.bInterfaceClass, 'subclass': i.bInterfaceSubClass,
                                                      'protocol': i.bInterfaceProtocol,
                                                      'endpoints': [{'address': e.bEndpointAddress,
                                                                     'attributes': e.bmAttributes,
                                                                     'max_packet_size': e.wMaxPacketSize} for e in i]}
                                                     for i in c]} for c in configs])
        interface = device.get_active_configuration()[(0, 0)]
        if (interface.bInterfaceClass, interface.bInterfaceProtocol) != (8, 0x50):
            raise RuntimeError('Interface 0 is not MSC Bulk-Only; no commands sent.')
        query_initial(device, report, make_backend_type())
    finally:
        # Explicitly release every matching handle, including ambiguous matches.
        for item in locals().get('found', []):
            usb.util.dispose_resources(item)


def main():
    path = BASE / 'diagnostic-reports' / ('initial-usb-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
                                        + '-' + uuid4().hex[:6] + '.json')
    report = Report(path)
    print('Initial USB information diagnostic. No service authentication or firmware/settings writes.', flush=True)
    try:
        probe(report)
    except Exception:
        report.data['outcome'] = 'failed'
        report.data['traceback'] = redact(traceback.format_exc())
        report.save()
        print('Stopped. Keep the report; do not proceed to installation.', flush=True)
        print(str(path), flush=True)
        return 1
    report.data['outcome'] = 'camera_info_passed'
    report.save()
    print('Initial camera information query passed. 0336 was intentionally not requested.', flush=True)
    print(str(path), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
