"""Lazy optional USB access for explicit LUT device commands only."""
import importlib,struct,sys
from pathlib import Path
from . import firmware
from .nativebuild import ROOT

TEMP_NAMES={'libJit.so','lut-program-staged.so','lut-names-staged.so','lut-runtime-staged.so',
    'a7c2.install.request','a7c2.install.result','a7c2.names.request','a7c2.names.result',
    'a7c2.wbi.request','a7c2.wbi.result','a7c2.runtime.result','a7c2.probe.result'}

def modules():
    folder=ROOT/'src/fl23';sys.path[:0]=[str(folder),str(folder/'vendor')]
    transport=importlib.import_module('transport');core=importlib.import_module('core')
    if Path(transport.__file__).resolve()!=folder/'transport.py' or Path(core.__file__).resolve()!=folder/'core.py':
        raise ValueError('Unexpected camera transport module already loaded')
    return transport,core

class Camera:
    def __init__(self,expected=None):self.expected=expected;self.healthy=True
    def __enter__(self):
        from .devicelock import DeviceLock
        self.lock=DeviceLock();self.lock.__enter__()
        try:return self._connect()
        except BaseException:
            self.lock.__exit__(*sys.exc_info());raise
    def _connect(self):
        transport,self.core=modules()
        normal=None if self.expected is None else {k:self.expected[k] for k in ['model','serial_sha256']}
        self.service_only=False
        import usb.core,usb.backend.libusb1
        backend=usb.backend.libusb1.get_backend(find_library=transport.libusb_package.find_library)
        detected=usb.core.find(idVendor=0x054c,idProduct=0x0e8a,backend=backend)
        if detected is not None:
            transport.usb.util.dispose_resources(detected)
            self.link=transport.Session(normal);self.link.__enter__()
        else:
            if not self.expected or 'product_sha256' not in self.expected:raise ValueError('First capture needs normal Mass Storage identity; reconnect USB')
            self.service_only=True;self.link=transport.Session(normal);self.link.dev=transport.get_device(0x0336)
            self.link.backend=transport.Bounded(self.link.dev)
            self.link.auth=transport.SonySenserAuthDevice(transport.GenericUsbDriver(self.link.backend))
            try:
                self.link.auth.start();self.link.auth.authenticate()
                self.link.channel=transport.SonySenserDevice(self.link.auth.driver)
                self.link.camera=transport.SonySenserCamera(self.link.channel);self.link.identity=normal
            except BaseException:
                transport.usb.util.dispose_resources(self.link.dev);raise
        try:
            product=self.link.call(self.link.camera.readHasp)
            if len(product)!=88:raise ValueError('Product-info format differs')
            token=firmware.sha(product)
            if self.expected and token!=self.expected.get('product_sha256'):raise ValueError('Current body product identity differs')
            self.identity=dict(self.link.identity,product_sha256=token)
        except BaseException:
            self.link.__exit__(*sys.exc_info());raise
        return self
    def __exit__(self,*args):
        try:
            self.healthy=self.link.healthy;return self.link.__exit__(*args)
        finally:self.lock.__exit__(*args)
    def read(self,path,missing=False):return self.link.read('/tmp/jiritsu/../../'+path.lstrip('/'),missing)
    def temp_read(self,name,missing=False):
        if name not in TEMP_NAMES:raise ValueError('Unowned temporary name')
        return self.link.read('/tmp/jiritsu/'+name,missing)
    def temp_write(self,name,data):
        if self.service_only:raise ValueError('Service-only recovery is read-only; reconnect normal USB identity before new execution')
        if name not in TEMP_NAMES or not data or len(data)>65536:raise ValueError('Invalid job temporary data')
        self.link.select('/tmp/jiritsu/'+name);self.link.jiritsu(16,b'\0\xff\0'+data)
    def temp_remove(self,name):
        if name not in TEMP_NAMES:raise ValueError('Unowned temporary name')
        self.link.select('/tmp/jiritsu/'+name);self.link.jiritsu(18,b'\0\xff')
    def snapshot(self,memory):return self.link.call(self.link.camera.getBackupPresetData,memory)
    def records(self,raw):return self.core.backup_records(raw)
    def property_read(self,key):return self.link.call(self.link.camera.readBackup,key)
    def property_write(self,key,value,allowlist):
        if self.service_only:raise ValueError('Service-only recovery cannot write settings')
        if key not in allowlist or key>>16!=0x02cf or not value or len(value)>4:raise ValueError('Setting outside selected AP descriptor plan')
        return self.link.call(self.link.camera.writeBackup,key,value)
    def save_settings(self):
        if self.service_only:raise ValueError('Service-only recovery cannot save settings')
        return self.link.call(self.link.camera.saveBackup,0x02cf)
    def mark_unknown(self):self.link.healthy=False;self.healthy=False

def invoke(camera,blob,*,stage,request,result,contents,mode,decode,record,save_raw,extras=()):
    """One invocation, never retries or cleans an unknown operation."""
    names=[n for n in [stage,request,'libJit.so',result,*extras] if n is not None]
    for name in names:
        if camera.temp_read(name,True) is not None:raise ValueError('Existing temporary state needs recovery: '+name)
    if camera.read('/etc/ld.so.preload',True):raise ValueError('Existing preload configuration requires inspection')
    expected={stage:blob,'libJit.so':blob}
    record('native_stage_intent',stage=stage,result=result,mode=mode,worker_sha256=firmware.sha(blob),request=request,contents_hex=contents.hex() if contents else None)
    camera.temp_write(stage,blob)
    if camera.temp_read(stage)!=blob:raise ValueError('Worker staging readback differs')
    if request is not None:
        expected[request]=contents;camera.temp_write(request,contents)
        if camera.temp_read(request)!=contents:raise ValueError('Request staging readback differs')
    record('native_intent',stage=stage,result=result,mode=mode,worker_sha256=firmware.sha(blob))
    try:
        camera.temp_write('libJit.so',blob)
        raw=camera.temp_read(result);save_raw(raw)
        parsed=decode(raw)
    except BaseException:
        camera.mark_unknown();raise
    expected[result]=raw
    for extra in extras:
        value=camera.temp_read(extra)
        if extra=='a7c2.probe.result':camera.core.parse_native('probe',value)
        expected[extra]=value
        record('native_extra_result',name=extra,sha256=firmware.sha(value))
    record('native_result_verified',stage=stage,mode=mode,result=parsed)
    for name in reversed(names):
        actual=camera.temp_read(name,True)
        if actual is not None:
            if actual!=expected[name]:raise ValueError('Preserve unexpected temporary contents: '+name)
            camera.temp_remove(name)
        if camera.temp_read(name,True) is not None:raise ValueError('Temporary cleanup incomplete: '+name)
    record('native_cleanup_verified',stage=stage,mode=mode)
    return parsed
