"""Body binding from the normal USB serial; never expose its raw value."""
from . import firmware

def capture(transport):
    dev=transport.get_device(0x0e8a)
    try:
        serial=transport.usb.util.get_string(dev,dev.iSerialNumber) if dev.iSerialNumber else None
        if (not serial or serial!=serial.strip() or len(serial)<8
                or len(set(serial))<2 or serial.lower() in {'12345678','123456789','1234567890','0123456789','unknown','ilce-7cm2'}):
            raise ValueError('A usable normal USB body serial is required; no service authentication')
        return firmware.sha(serial.encode('utf-8'))
    finally:transport.usb.util.dispose_resources(dev)

class BodyMismatch(ValueError):
    """Another body is connected; raised before any service authentication."""

def require_match(expected,actual):
    if expected is None:return
    wanted=expected.get('usb_serial_sha256')
    if not wanted:
        # Jobs from earlier previews bound the body only through the service
        # serial; the service session verifies that binding before any command.
        if expected.get('serial_sha256'):return
        raise ValueError('Legacy job has no stable USB body binding; retain it and prepare a fresh job')
    if wanted!=actual:raise BodyMismatch('Current USB body identity differs; no service authentication')
