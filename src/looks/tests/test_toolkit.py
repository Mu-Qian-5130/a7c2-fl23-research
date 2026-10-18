import contextlib
import io
import json
import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

from looktool import calibration,firmware,native,project
from looktool.color import rgb_to_hsv,hsv_to_rgb,srgb_encode,srgb_decode
from looktool.references import Cube,DcpLook,tiff_tags
from looktool.__main__ import main


def fixture_dcp(path, dims=(4,3,2), encoding=1, endian='<', magic=0x4352):
    nh,ns,nv = dims
    table = np.zeros((nv,nh,ns,3),dtype=endian+'f4')
    table[...,1:] = 1
    values = [(50981,4,struct.pack(endian+'3I',*dims)),(50982,11,table.tobytes()),
              (50940,11,struct.pack(endian+'4f',0,0,1,1)),(51108,4,struct.pack(endian+'I',encoding))]
    raw = bytearray((b'II' if endian == '<' else b'MM')+struct.pack(endian+'HI',magic,8))
    raw.extend(struct.pack(endian+'H',len(values))+bytes(12*len(values)+4))
    for i,(tag,typ,payload) in enumerate(values):
        at = 10+i*12
        if len(payload) <= 4:
            raw[at:at+12] = struct.pack(endian+'HHI',tag,typ,len(payload)//4)+payload+bytes(4-len(payload))
        else:
            raw[at:at+12] = struct.pack(endian+'HHII',tag,typ,len(payload)//4,len(raw))
            raw.extend(payload)
    path.write_bytes(raw)
    return table


def fixture_cube(path, minimum=0, maximum=1):
    lines = ['TITLE "identity # quoted"', 'LUT_3D_SIZE 2', f'DOMAIN_MIN {minimum} {minimum} {minimum}',f'DOMAIN_MAX {maximum} {maximum} {maximum}']
    for b in (minimum,maximum):
        for g in (minimum,maximum):
            for r in (minimum,maximum):
                lines.append(f'{r} {g} {b} # red fastest')
    path.write_text('\n'.join(lines))


class ToolkitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cube_axis_order_and_domain(self):
        p=self.root/'a.cube';fixture_cube(p,-1,2);c=Cube(p)
        x=np.random.default_rng(7).uniform(-1,2,(317,3))
        np.testing.assert_allclose(c.sample(x),x,atol=1e-14)

    def test_cube_rejects_shaper_nonfinite_truncation(self):
        p=self.root/'a.cube'
        for text in ['LUT_1D_SIZE 2\n0 0 0\n1 1 1','LUT_3D_SIZE 2\n0 0 0','LUT_3D_SIZE 2\n'+'nan 0 0\n'*8]:
            p.write_text(text)
            with self.assertRaises(ValueError):Cube(p)

    def test_dcp_both_magics_byte_orders_and_single_axes(self):
        p=self.root/'a.dcp'
        for magic in (42,0x4352):
            for endian in ('<','>'):
                for dims in ((4,3,2),(1,3,1)):
                    for encoding in (0,1):
                        fixture_dcp(p,dims,encoding,endian,magic)
                        d=DcpLook(p);hsv=np.random.default_rng(3).uniform(0,1,(113,3));hsv[:,0]*=360
                        np.testing.assert_allclose(d.lookup(hsv),np.tile([0,1,1],(113,1)),atol=1e-14)

    def test_dcp_hue_wrap_and_value_axis(self):
        p=self.root/'a.dcp';fixture_dcp(p);d=DcpLook(p)
        d.table[...,0]=np.arange(4)[None,:,None]*10
        d.table[...,2]=np.array([1.,2.])[:,None,None]
        x=np.array([[359.9,.3,.15],[-.1,.3,.15]])
        out=d.lookup(x)
        np.testing.assert_allclose(out[0],out[1])
        self.assertAlmostEqual(out[0,2],1+srgb_encode(np.array([.15]))[0])

    def test_dcp_truncation_and_bad_ifd(self):
        p=self.root/'a.dcp';fixture_dcp(p);raw=p.read_bytes()
        for bad in (raw[:8],raw[:25],raw[:-7],raw[:4]+struct.pack('<I',0xffff)+raw[8:]):
            with self.assertRaises(ValueError):tiff_tags(bad)

    def test_hsv_and_encoding_roundtrips(self):
        rgb=np.vstack([np.zeros((1,3)),np.ones((1,3)),np.random.default_rng(11).uniform(0,1,(300,3))])
        np.testing.assert_allclose(hsv_to_rgb(rgb_to_hsv(rgb)),rgb,atol=1e-14)
        np.testing.assert_allclose(srgb_decode(srgb_encode(rgb)),rgb,atol=1e-14)

    def test_dcp_render_identity_look_matches_color_conversion(self):
        from looktool.color import prophoto_to_srgb
        p=self.root/'a.dcp';fixture_dcp(p);d=DcpLook(p)
        rgb=np.random.default_rng(1).uniform(.01,.8,(211,3))
        np.testing.assert_allclose(d.render(rgb),np.clip(srgb_encode(rgb@prophoto_to_srgb().T),0,1),atol=2e-14)

    def test_native_encoding_plane_order_and_range(self):
        c=(np.arange(1215)%128-64).reshape(405,3)
        raw=native.encode(c)
        np.testing.assert_array_equal(native.decode(raw),c)
        self.assertEqual(raw[:405],c[:,0].astype('i1').tobytes())
        for bad in (bytes([127])*1215,bytes(1214)):
            with self.assertRaises(ValueError):native.decode(bad)

    def test_native_weights_and_constant_correction(self):
        rgb=np.random.default_rng(5).uniform(0,1,(213,3));ids,w=native.interpolation(rgb)
        np.testing.assert_allclose(w.sum(1),1)
        self.assertTrue(np.all((ids>=0)&(ids<405)))
        c=np.tile([1,-2,3],(405,1));response=np.eye(3)
        np.testing.assert_allclose(native.predict(rgb,c,response),np.clip(rgb+[1/256,-2/256,3/256],0,1))

    def test_fit_reduces_known_transform_error(self):
        rgb=np.random.default_rng(9).uniform(.1,.9,(800,3));wanted=np.clip(rgb+[.02,-.01,.03],0,1)
        h,rhs=native.equations(rgb,wanted,np.eye(3));c,convergence=native.constrained_fit(h,rhs,1)
        self.assertTrue(convergence['converged'])
        self.assertLess(native.metrics(native.predict(rgb,c,np.eye(3)),wanted)['rgb_mae'],.003)

    def test_calibration_split_and_response_guards(self):
        data={'schema':'a7c2-look-calibration/1','coordinate_model':'bt601-limited-provisional','response_matrix':np.eye(3).tolist(),'evidence':'synthetic unit test'}
        calibration.validate(data)
        data['response_matrix']=np.zeros((3,3)).tolist()
        with self.assertRaises(ValueError):calibration.validate(data)
        with self.assertRaises(ValueError):calibration.fit(np.zeros((64,3)),np.zeros((64,3)),np.zeros(64),np.eye(3),'test')

    def test_project_selected_st_constraint_and_preservation(self):
        d={'schema':'a7c2-look-project/1','model':'ILCE-7CM2','firmware':'2.01','slots':[
            {'slot':5,'name':'GR Positive Film','base':'ST','source':{'type':'dcp','path':'a.dcp','attribution':'test'}}]}
        p=self.root/'project.json';p.write_text(json.dumps(d));data,_=project.load(p);plan=project.slot_plan(data)
        self.assertEqual(plan['preserve_slots'],[1,2,3,4,6]);project.check_bindings(plan,{'5':'ST'})
        for bindings in ({},{'5':'FL'}):
            with self.assertRaises(ValueError):project.check_bindings(plan,bindings)
        d['slots'][0]['base']='FL';p.write_text(json.dumps(d))
        with self.assertRaises(ValueError):project.load(p)

    def test_project_duplicate_bool_slots_and_unbridged_log(self):
        entry={'slot':1,'name':'A','base':'ST','source':{'type':'cube','path':'a.cube','input_space':'flog2','output_space':'srgb','attribution':'test'}}
        p=self.root/'p.json';d={'schema':'a7c2-look-project/1','model':'ILCE-7CM2','firmware':'2.01','slots':[entry]}
        p.write_text(json.dumps(d))
        with self.assertRaises(ValueError):project.load(p)
        entry['source']['input_space']='sony-st-srgb'
        for slots in ([entry,entry],[dict(entry,slot=True)]):
            d['slots']=slots;p.write_text(json.dumps(d))
            with self.assertRaises(ValueError):project.load(p)

    def test_exact_transitions_reverse_and_tamper_rejection(self):
        before={'a':bytes(range(200))};a=bytearray(before['a']);a[30:34]=b'abcd';after={'a':bytes(a)}
        f=firmware.transition(before,after,{'a':[(30,4)]});r=firmware.transition(after,before,{'a':[(30,4)]})
        self.assertEqual(firmware.apply(firmware.apply(before,f),r),before)
        with self.assertRaises(ValueError):firmware.apply({'a':bytes(200)},f)
        with self.assertRaises(ValueError):firmware.transition(before,after,{'a':[(1,3)]})
        f['files']['a']['windows'].append(f['files']['a']['windows'][0])
        with self.assertRaises(ValueError):firmware.apply(before,f)

    def test_six_slot_native_adapter_refuses_unsupported_layout(self):
        with self.assertRaisesRegex(ValueError,'only slots'):
            firmware.replace_tables(b'',b'',{4:bytes(1215)})
        with self.assertRaisesRegex(ValueError,'exact documented'):
            firmware.replace_tables(b'',b'',{1:bytes(1215)})

    def test_cli_plan_runs_without_inputs_and_no_camera(self):
        example=Path(__file__).resolve().parents[1]/'examples/six-looks.json'
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['plan',str(example)]),0)
        data=json.loads(out.getvalue());self.assertEqual(data['selected_slots'],[1,2,3,4,5,6])
        self.assertFalse(data['camera_menu_base_picker_locked'])

    def test_cli_fit_identity_cube_end_to_end(self):
        cube=self.root/'identity.cube';fixture_cube(cube)
        model={'schema':'a7c2-look-calibration/1','coordinate_model':'bt601-limited-provisional',
               'response_matrix':np.eye(3).tolist(),'evidence':'synthetic identity test only'}
        (self.root/'calibration.json').write_text(json.dumps(model))
        data={'schema':'a7c2-look-project/1','model':'ILCE-7CM2','firmware':'2.01','calibration':'calibration.json',
              'slots':[{'slot':2,'name':'Identity','base':'ST','source':{'type':'cube','path':'identity.cube',
                       'input_space':'sony-st-srgb','output_space':'srgb','attribution':'synthetic fixture'}}]}
        path=self.root/'project.json';path.write_text(json.dumps(data));out=self.root/'candidate'
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['fit',str(path),str(out),'--samples','512']),0)
        report=json.loads((out/'candidate.json').read_text())
        self.assertEqual((out/'slot2.raw-s8.bin').read_bytes(),bytes(1215))
        self.assertLess(report['looks'][0]['fit']['synthetic_holdout']['rgb_mae'],1e-14)
        self.assertEqual(report['slot_plan']['preserve_slots'],[1,3,4,5,6])
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['fit',str(path),str(out),'--samples','512']),2)


if __name__=='__main__':unittest.main()
