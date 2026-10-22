"""A lone read-only probe report is cleared; anything else still stops."""
import types,unittest
from looktool import devicesession

class Camera:
    def __init__(self,files):
        self.files=dict(files);self.preload=b''
        self.link=types.SimpleNamespace(read=lambda path,missing=False:self.files.get(path.rsplit('/',1)[-1]))
    def temp_read(self,name,missing=False):return self.files.get(name)
    def temp_remove(self,name):self.files.pop(name)
    def read(self,path,missing=False):return self.preload or None

class StaleProbeTests(unittest.TestCase):
    def test_lone_probe_report_is_recorded_then_removed(self):
        camera=Camera({'a7c2.probe.result':b'image_mode=0\n'});events=[]
        devicesession.clear_stale_probe(camera,lambda event,**kw:events.append((event,kw)))
        self.assertEqual(camera.files,{})
        self.assertEqual(events[0][0],'stale_probe_result_removed')
        self.assertEqual(bytes.fromhex(events[0][1]['contents_hex']),b'image_mode=0\n')

    def test_probe_beside_any_other_worker_file_or_preload_is_kept(self):
        for other in ('libJit.so','lut-names-staged.so','a7c2.runtime.result','checkpoint.program.request',
                      'a7c2-preview-staged.so','shutter.staged.so','portrait.request'):
            with self.subTest(other=other):
                camera=Camera({'a7c2.probe.result':b'x',other:b'y'});events=[]
                devicesession.clear_stale_probe(camera,lambda event,**kw:events.append(event))
                self.assertIn('a7c2.probe.result',camera.files);self.assertEqual(events,[])
        camera=Camera({'a7c2.probe.result':b'x'});camera.preload=b'/tmp/x.so'
        devicesession.clear_stale_probe(camera,lambda *a,**k:None)
        self.assertIn('a7c2.probe.result',camera.files)

if __name__=='__main__':unittest.main()
