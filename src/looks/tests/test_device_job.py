"""Simulated end-to-end jobs with real known program fixtures; never USB."""
import copy,hashlib,importlib.util,json,os,struct,tempfile,unittest
from collections import namedtuple
from pathlib import Path
from unittest.mock import patch
from looktool import devicejob,firmware,nameworker,nativebuild,resources
from test_device_components import resource_fixture

ROOT=Path(__file__).resolve().parents[3]
Prop=namedtuple('Prop','data attr')
spec=importlib.util.spec_from_file_location('lut_test_core',ROOT/'src/fl23/core.py')
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)

class SimCamera:
    def __init__(self,ap,cp):
        self.files={'/usr/lib/appFw.so':ap,'/cp/cpapp-b.bin':cp};self.identity={'model':'ILCE-7CM2','serial_sha256':'simulated-body'};self.core=core
        self.boot='boot-1\n';self.mode='2\n';self.properties={};self.saves=0
        for slot in range(18):
            at=0x57c6710+slot*32;row=struct.unpack_from('<8I',ap,at)
            self.properties[row[1]]=Prop(bytes([0 if slot==0 else 1]),0)
        for i in range(8):
            for slot in range(18):
                attr=0x1520+i*18+slot;row=struct.unpack_from('<8I',ap,0x57c6710+(attr-0x14ea)*32)
                self.properties[row[1]]=Prop((i+(5 if slot else 0)).to_bytes(4,'little'),0)
        self.cp={k:Prop(b'protected-'+str(k).encode(),0) for k in [0x02a40000,0x02a40001,0x02a40002,0x02a4000d]}
        self.saved=copy.deepcopy(self.properties)
        for n in nameworker.filenames():self.files['/usr/share/app/'+n]=resource_fixture()
    def __call__(self,expected=None):
        if expected and expected!=self.identity:raise ValueError('Wrong simulated body')
        return self
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,path,missing=False):return self.files.get(path)
    def snapshot(self,memory):
        a=self.properties if memory else self.saved
        return json.dumps([{str(k):[v.data.hex(),v.attr] for k,v in p.items()} for p in [a,self.cp]]).encode()
    def records(self,raw):return [{int(k):Prop(bytes.fromhex(v[0]),v[1]) for k,v in p.items()} for p in json.loads(raw)]
    def property_read(self,key):return self.properties[key].data
    def property_write(self,key,value,allowed):
        if key not in allowed:raise ValueError('Unexpected property')
        self.properties[key]=Prop(value,self.properties[key].attr)
    def save_settings(self):self.saved=copy.deepcopy(self.properties);self.saves+=1
    def reboot(self):self.boot=self.boot+'new';self.mode='2\n'

class SimJob(devicejob.Job):
    fail_after_program=False
    def _fit(self,*args):
        out=self.root/'candidate';out.mkdir();(out/'slot6.bin').write_bytes(bytes([1])*1215)
        return bytes([1])*1215
    def _invoke(self,camera,kind,mode):
        self.record('simulated_native_call',kind=kind,mode=mode)
        if kind=='runtime':
            ap=camera.files['/usr/lib/appFw.so'];offset=0x3528804;value=ap[offset:offset+112].hex()
            return {'boot_id':camera.boot,'image_mode':camera.mode,'image_dev':'*wbi4\n','spans':[{'offset':offset,'length':112,'memory':value,'disk':value}]}
        if kind=='wbi':camera.mode='0\n';return {'verified':True}
        if kind=='program':
            values={name:camera.files[path] for name,path in devicejob.PROGRAM_PATHS.items()}
            if mode in [1,2]:
                manifest=json.loads((self.root/f'transition/{"forward" if mode==1 else "reverse"}.private.json').read_text())
                after=firmware.apply(values,manifest)
                for n,b in after.items():camera.files[devicejob.PROGRAM_PATHS[n]]=b
                if mode==1 and self.fail_after_program:raise TimeoutError('simulated lost completion')
        elif kind=='names' and mode in [1,2]:
            for n in nameworker.filenames():camera.files['/usr/share/app/'+n]=(self.root/('resource-target' if mode==1 else 'source/resources')/n).read_bytes()
        return {'native_verified':True}

def fake_program(before,f,r,out,zig):
    out=Path(out);out.mkdir(parents=True);header,c=nativebuild.program_header(before,f,r);(out/'program.so').write_bytes(b'simulated-program-worker')
    return {'unchanged':False,'sha256':firmware.sha(b'simulated-program-worker'),'contract':c}

def fake_names(sources,names,ap,identifier,out,zig,**kwargs):
    out=Path(out);out.mkdir(parents=True);(out/'names.so').write_bytes(b'simulated-name-worker');target={};specs=[]
    for n,raw in sources.items():
        after,plan=resources.rename(raw,names,kwargs.get('label_ids',resources.LABEL_IDS));target[n]=after;specs.append({'file':n,'before_bytes':len(raw),'after_bytes':len(after),'before_sha256':firmware.sha(raw),'after_sha256':firmware.sha(after),'inverse':plan})
    return target,{'sha256':firmware.sha(b'simulated-name-worker'),'files':specs,'AP':firmware.sha(ap),'count':68}

@unittest.skipUnless(os.environ.get('A7C2_RESEARCH_FIXTURES'),'Requires private complete source fixtures')
class DeviceJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        index=Path(os.environ['A7C2_RESEARCH_FIXTURES']);p=json.loads(index.read_text())
        cls.ap=(index.parent/p['six_ap']).read_bytes();cls.cp=(index.parent/p['v4_cp']).read_bytes()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='lut-device-simulation ');self.addCleanup(self.tmp.cleanup);self.folder=Path(self.tmp.name)
        self.reference=self.folder/'reference.cube';self.reference.write_text('LUT_3D_SIZE 2\n'+'\n'.join(f'{r} {g} {b}' for b in [0,1] for g in [0,1] for r in [0,1]),encoding='ascii')
        self.model=self.folder/'calibration.json';self.model.write_text(json.dumps({'schema':'a7c2-look-calibration/1','coordinate_model':'bt601-limited-provisional','response_matrix':[[1,0,0],[0,1,0],[0,0,1]],'evidence':'SYNTHETIC TEST ONLY'}))
        self.camera=SimCamera(self.ap,self.cp)
        self.p1=patch.object(nativebuild,'build_program',side_effect=fake_program);self.p1.start();self.addCleanup(self.p1.stop)
        self.p2=patch.object(nameworker,'prepare',side_effect=fake_names);self.p2.start();self.addCleanup(self.p2.stop)
        self.job=SimJob(self.folder/'job',factory=self.camera)
    def create(self,write=True,battery=90):return self.job.create(self.reference,'怀旧负片',6,self.model,self.folder/'backup',write=write,battery=battery,input_space='sony-st-srgb')
    def test_full_import_readback_reload_acceptance_and_exact_restore(self):
        original_props=copy.deepcopy(self.camera.properties);before_resource=self.camera.files['/usr/share/app/'+nameworker.filenames()[0]]
        state=self.create();self.assertEqual(state['phase'],'AWAITING_RELOAD');self.assertEqual(self.camera.saves,1)
        self.assertEqual(self.camera.files['/usr/lib/appFw.so'],self.ap)
        renamed=self.camera.files['/usr/share/app/'+nameworker.filenames()[0]]
        self.assertEqual(resources.decode(renamed)['entries'][resources.LABEL_IDS[5]]['text'],'怀旧负片')
        with self.assertRaises(ValueError):self.job.verify(True)
        self.camera.reboot();self.assertEqual(self.job.verify(True)['phase'],'COMPLETE')
        self.assertEqual(self.job.restore(90)['phase'],'RESTORED_AWAITING_RELOAD')
        self.assertEqual(self.camera.files['/cp/cpapp-b.bin'],self.cp);self.assertEqual(self.camera.properties,original_props)
        self.assertEqual(self.camera.files['/usr/share/app/'+nameworker.filenames()[0]],before_resource)
        self.camera.reboot();self.assertEqual(self.job.verify(True)['phase'],'RESTORED')
    def test_prepare_only_never_installs_and_modified_artifact_stops_install(self):
        self.assertEqual(self.create(False)['phase'],'PREFLIGHT_VERIFIED')
        self.assertEqual(self.camera.files['/cp/cpapp-b.bin'],self.cp);self.assertEqual(self.camera.saves,0)
        p=self.job.root/'candidate/slot6.bin';p.write_bytes(bytes([2])*1215)
        with self.assertRaises(ValueError):self.job.install(90)
        self.assertEqual(self.camera.files['/cp/cpapp-b.bin'],self.cp)
    def test_unknown_program_outcome_never_replays_or_advances_to_settings(self):
        self.job.fail_after_program=True
        with self.assertRaises(TimeoutError):self.create()
        state=json.loads(self.job.state_path.read_text(encoding='utf-8'));self.assertEqual(state['phase'],'NEEDS_REVIEW')
        calls=[e for e in state['journal'] if e['event']=='simulated_native_call' and e['mode']==1]
        self.assertEqual([(e['kind'],e['mode']) for e in calls],[('names',1),('program',1)])
        self.assertEqual(self.camera.saves,0);self.assertEqual(self.camera.properties,self.camera.saved)
        with self.assertRaises(ValueError):self.job.install(90)
    def test_low_battery_and_missing_reference_stop_before_any_device_access(self):
        with patch.object(self.job,'factory') as factory:
            with self.assertRaises(ValueError):self.create(True,12)
            factory.assert_not_called()
        self.assertFalse((self.folder/'job').exists())

if __name__=='__main__':unittest.main()
