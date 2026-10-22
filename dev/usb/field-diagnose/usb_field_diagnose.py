"""Read-only field USB diagnostic: one service authentication and a USB timeline.

It sends the same authentication as "Prepare drivers and test connection",
records every USB transfer of that exchange (including the start request that
pmca silently ignores on failure), then watches which Sony USB identities appear
for up to 90 seconds. It never stages workers, writes firmware, settings or
camera files, and never sends the service stop request.

Run from the packaged app: Run-USB-Diagnose.cmd temporarily puts this file in
place of the app's offline self-test and calls A7C2Tools.exe --offline-self-test.
It also runs from a source checkout: python dev/usb/field-diagnose/usb_field_diagnose.py
Serial numbers are reported only as SHA-256 digests.
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time
import traceback

# Packaged: _internal/dev/desktop/offline_smoke.py; source: dev/usb/field-diagnose/.
HERE = Path(__file__).resolve()
ROOT = HERE.parents[2] if (HERE.parents[2] / 'src/camera_runtime').is_dir() else HERE.parents[3]
SONY = 0x054c
TIMELINE_SECONDS = 90
POLL = 0.25
LOG = Path(os.environ.get('A7C2_DIAG_LOG') or (Path.cwd() / 'usb-diagnose.log'))
START = time.monotonic()


def log(event, **values):
    row = dict(t=round(time.monotonic() - START, 3), event=event, **values)
    with LOG.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
    return row


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16] if text else None


def describe(exc):
    if exc is None:
        return None
    return dict(type=type(exc).__name__, message=str(exc), cause=describe(exc.__context__) if exc.__context__ is not exc else None)


def setup():
    sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'src/looks')]
    from looktool.devicesession import modules
    return modules()


def environment():
    info = dict(platform=platform.platform(), release=platform.release(), version=platform.version(),
                machine=platform.machine(), python=sys.version, frozen=bool(getattr(sys, 'frozen', False)))
    if hasattr(sys, 'getwindowsversion'):
        w = sys.getwindowsversion()
        info['windows_build'] = '%d.%d.%d' % (w.major, w.minor, w.build)
    try:
        from desktopapp import VERSION
        info['app_version'] = VERSION
    except Exception as exc:
        info['app_version_error'] = describe(exc)
    return info


def devices(usb, backend, strings=False):
    rows = []
    for dev in usb.core.find(find_all=True, idVendor=SONY, backend=backend):
        row = dict(pid='%04x' % dev.idProduct, bus=dev.bus, address=dev.address,
                   speed=getattr(dev, 'speed', None), bcd_device='%04x' % dev.bcdDevice)
        try:
            row['port_numbers'] = list(dev.port_numbers or [])
        except Exception:
            pass
        try:
            configs = list(dev)
            row['interfaces'] = [dict(number=i.bInterfaceNumber, cls=i.bInterfaceClass, subclass=i.bInterfaceSubClass,
                                      protocol=i.bInterfaceProtocol,
                                      endpoints=['%02x/%d' % (e.bEndpointAddress, e.bmAttributes) for e in i])
                                 for c in configs for i in c]
        except Exception as exc:
            row['config_error'] = describe(exc)
        if strings:
            for key, index in (('product', dev.iProduct), ('manufacturer', dev.iManufacturer)):
                try:
                    row[key] = usb.util.get_string(dev, index) if index else None
                except Exception as exc:
                    row[key + '_error'] = describe(exc)
            try:
                row['serial_sha256'] = digest(usb.util.get_string(dev, dev.iSerialNumber)) if dev.iSerialNumber else None
            except Exception as exc:
                row['serial_error'] = describe(exc)
        usb.util.dispose_resources(dev)
        rows.append(row)
    return rows


def authenticate(transport, usb, report):
    """The same exchange as transport.Session, with every transfer recorded."""
    transfers = report['auth_transfers']

    class Logged(transport.Bounded):
        def _record(self, op, call, **detail):
            begin = time.perf_counter()
            try:
                result = call()
            except BaseException as exc:
                transfers.append(log('usb_' + op, ok=False, ms=round((time.perf_counter() - begin) * 1000, 1),
                                     error=describe(exc), **detail))
                raise
            if isinstance(result, (bytes, bytearray)):
                detail['returned_bytes'] = len(result)
            transfers.append(log('usb_' + op, ok=True, ms=round((time.perf_counter() - begin) * 1000, 1), **detail))
            return result

        def read(self, ep, length, timeout=None):
            return self._record('read', lambda: transport.Bounded.read(self, ep, length, timeout),
                                ep='%02x' % ep, requested=length)

        def write(self, ep, data):
            return self._record('write', lambda: transport.Bounded.write(self, ep, data), ep='%02x' % ep, sent=len(data))

        def vendorRequestOut(self, request, value, index, data=b''):
            return self._record('vendor_request_out', lambda: transport.Bounded.vendorRequestOut(self, request, value, index, data),
                                request=request, value='%04x' % value, index='%04x' % index)

        def classInterfaceRequestOut(self, request, value, index, data=b''):
            return self._record('class_request_out',
                                lambda: transport.Bounded.classInterfaceRequestOut(self, request, value, index, data),
                                request=request, value='%04x' % value, index='%04x' % index)

    dev = transport.get_device(0x0e8a)
    try:
        product = usb.util.get_string(dev, dev.iProduct) if dev.iProduct else None
        report['auth_device'] = log('auth_device', product=product, speed=getattr(dev, 'speed', None))
        backend = Logged(dev, 20)
        driver = transport.GenericUsbDriver(backend)
        report['auth_endpoints'] = log('auth_endpoints', bulk_in=['%02x' % e for e in driver.epIn],
                                       bulk_out=['%02x' % e for e in driver.epOut])
        auth = transport.SonySenserAuthDevice(driver)
        log('auth_start_request')
        auth.start()  # pmca ignores a failed start; the Logged backend still records it
        log('auth_exchange')
        auth.authenticate()
        report['auth_result'] = log('auth_completed')
    finally:
        usb.util.dispose_resources(dev)


def timeline(usb, backend, report):
    """Record each change of the Sony USB identities for up to TIMELINE_SECONDS."""
    begin = time.monotonic()
    last = None
    service_seen = None
    while time.monotonic() - begin < TIMELINE_SECONDS:
        try:
            state = devices(usb, backend)
            key = json.dumps([(r['pid'], r.get('address'), bool(r.get('config_error'))) for r in state])
        except Exception as exc:
            state, key = dict(error=describe(exc)), 'error:' + repr(exc)
        if key != last:
            report['timeline'].append(log('usb_state', seconds=round(time.monotonic() - begin, 2), devices=state))
            last = key
        if isinstance(state, list) and any(r['pid'] == '0336' for r in state):
            service_seen = service_seen or time.monotonic()
            if time.monotonic() - service_seen > 5:
                break
        time.sleep(POLL)
    report['service_identity_seen'] = service_seen is not None


def run():
    report = dict(schema='a7c2-usb-field-diagnose/1', camera_firmware_written=False, camera_settings_written=False,
                  native_worker_executed=False, service_stop_sent=False, auth_transfers=[], timeline=[])
    log('start', log_file=str(LOG))
    try:
        transport, core = setup()
        report['environment'] = log('environment', **environment())
        import usb.core
        import usb.util
        import usb.backend.libusb1
        backend = usb.backend.libusb1.get_backend(find_library=transport.libusb_package.find_library)
        report['libusb'] = log('libusb', library=str(getattr(getattr(backend, 'lib', None), '_name', None)), backend=bool(backend))
        if sys.platform == 'win32':
            try:
                from desktopapp.platforms.usb_drivers import scan
                found = scan()
                report['drivers'] = log('drivers', devices=found.get('devices'), errors=found.get('errors'))
            except Exception as exc:
                report['drivers_error'] = log('drivers_error', error=describe(exc))
        report['before'] = log('devices_before', devices=devices(usb, backend, strings=True))
        if not any(r['pid'] == '0e8a' for r in report['before']['devices']):
            report['stopped'] = log('stopped', reason='No 054C:0E8A camera found; select Mass Storage and reconnect')
            return report
        try:
            authenticate(transport, usb, report)
        except Exception as exc:
            report['auth_error'] = log('auth_error', error=describe(exc), traceback=traceback.format_exc())
        timeline(usb, backend, report)
        report['after'] = log('devices_after', devices=devices(usb, backend, strings=True))
    except Exception as exc:
        report['error'] = log('error', error=describe(exc), traceback=traceback.format_exc())
    report['finished'] = log('finished', next_step='Fully power-cycle the camera (remove the battery for one minute) before using it again.')
    return report


if __name__ == '__main__':
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd() / 'usb-diagnose-result.json'
    target.write_text(json.dumps(run(), ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print('Report:', target, '| log:', LOG)
