"""Bounded service acquisition for known busy or missing-card MSC states.

Only changes the temporary USB identity. Model proof is deferred to pinned
programs plus the read-only native probe, before any persistent write.
"""
import time

def allowed_initial_busy(transport,error):
    return ((isinstance(error,transport.ReadinessFailure) and str(error) in {
            'Camera did not become ready; Sony query was not started.',
            'Camera is not ready; sense=02/3a/00. Stopped.'})
        or (isinstance(error,transport.SonyBusyFailure) and str(error)=='Camera remained busy after readiness passed; query stopped.'))

def open_service(transport):
    dev=transport.get_device(0x0e8a)
    try:
        # INQUIRY is valid without a ready storage medium. Do not broaden this
        # path to USB timeouts, unknown sense codes or a different manufacturer.
        info=transport.MscDevice(transport.MscBbbDriver(transport._InitialBackend(dev,None))).getDeviceInfo()
        if info.manufacturer.strip()!='Sony':raise ValueError('Unexpected SCSI manufacturer; no service authentication')
    finally:transport.usb.util.dispose_resources(dev)
    normal=transport.get_device(0x0e8a)
    try:
        auth=transport.SonySenserAuthDevice(transport.GenericUsbDriver(transport.Bounded(normal,20)))
        auth.start();auth.authenticate()
    finally:
        # An ambiguous authentication is never retried or followed by another
        # protocol command. Releasing the host handle is always local cleanup.
        transport.usb.util.dispose_resources(normal)
    link=transport.Session();deadline=time.monotonic()+15
    while True:
        try:link.dev=transport.get_device(0x0336);break
        except RuntimeError:
            if time.monotonic()>=deadline:raise RuntimeError('Service USB identity did not appear; inspect without repeating authentication')
            time.sleep(.5)
    time.sleep(2)
    link.backend=transport.Bounded(link.dev)
    link.auth=transport.SonySenserAuthDevice(transport.GenericUsbDriver(link.backend))
    try:
        link.auth.start();link.auth.authenticate()
        link.channel=transport.SonySenserDevice(link.auth.driver)
        link.camera=transport.SonySenserCamera(link.channel)
        link.identity={'model':None,'identification_method':'pending-pinned-programs-and-native-model'}
    except BaseException:
        link.healthy=False;transport.usb.util.dispose_resources(link.dev);raise
    return link
