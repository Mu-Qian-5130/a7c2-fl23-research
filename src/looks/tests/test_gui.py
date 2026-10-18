"""The custom entry builds only offline commands and preserves file arguments."""
import ast,contextlib,importlib.util,io,json,os,tempfile
from pathlib import Path
import unittest
BASE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('custom_look_gui',BASE/'gui.py')
gui=importlib.util.module_from_spec(spec);spec.loader.exec_module(gui)

class CustomEntryTests(unittest.TestCase):
    def test_actions_are_offline_and_unknown_action_is_rejected(self):
        self.assertEqual([item[0] for item in gui.ACTIONS.values()],['inspect','plan','check-bindings','calibrate','fit','prepare-transition'])
        with self.assertRaises(ValueError):gui.build_arguments('install',{})
        tree=ast.parse((BASE/'gui.py').read_text(encoding='utf-8'))
        imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        imports += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
        self.assertFalse(any(n.startswith(('usb','transport','pmca')) for n in imports))
    def test_transition_preserves_unicode_paths_and_exact_layout(self):
        values={k:'D:/色表 test/'+k for k in ['candidate','ap','cp','bindings','output']}
        args=gui.build_arguments('6. 生成更新与还原清单',values)
        self.assertEqual(args,['prepare-transition']+[values[k] for k in ['candidate','ap','cp','bindings','output']]+['--layout','full7-v4'])
        with self.assertRaises(ValueError):gui.build_arguments('6. 生成更新与还原清单',values,'stock-anything')
    def test_missing_input_stops_before_command_creation(self):
        with self.assertRaises(ValueError):gui.build_arguments('5. 拟合机内色表',{'project':'profile.json','output':' '})
        self.assertEqual(gui.build_arguments('1. 检查 DCP / CUBE',{'source':'D:/looks/参考.cube'}),['inspect','D:/looks/参考.cube'])
    def test_calibration_reaches_cli_and_protects_existing_output(self):
        import numpy as np
        from looktool.__main__ import main
        from looktool.calibration import validate
        from looktool.color import srgb_decode,prophoto_to_srgb
        with tempfile.TemporaryDirectory(prefix='校准 inputs ') as directory:
            root=Path(directory);rgb=np.random.default_rng(201).uniform(.1,.8,(80,3))
            linear=srgb_decode(rgb)@np.linalg.inv(prophoto_to_srgb()).T
            patches=root/'色块.npz';response=root/'响应.json';output=root/'校准.json'
            np.savez(patches,st_rgb=rgb,linear_prophoto=linear,split=np.tile([0,1],40))
            response.write_text(json.dumps({'response_matrix':np.eye(3).tolist(),'evidence':'SYNTHETIC GUI routing test only'}),encoding='utf-8')
            args=gui.build_arguments('4. 根据量测生成校准',{'patches':str(patches),'response':str(response),'output':str(output)})
            with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args),0)
                data=json.loads(output.read_text(encoding='utf-8'));validate(data,True)
                original=output.read_bytes();self.assertEqual(main(args),2)
            self.assertEqual(output.read_bytes(),original)
        self.assertEqual(gui.output_name('4. 根据量测生成校准'),'calibration-v1.json')
        self.assertEqual(gui.output_name('5. 拟合机内色表'),'candidate-v1')
        self.assertEqual(gui.output_name('6. 生成更新与还原清单'),'transition-v1')
    @unittest.skipUnless(os.name=='nt','Windows Tk window construction')
    def test_window_exposes_all_six_operations_with_separate_output_paths(self):
        root=gui.tk.Tk();root.withdraw();observed={};errors=[]
        def inspect():
            try:
                def widgets(parent):
                    result=[]
                    for child in parent.winfo_children():result.append(child);result.extend(widgets(child))
                    return result
                combos=[w for w in widgets(root) if isinstance(w,gui.ttk.Combobox)]
                picker=next(w for w in combos if len(w['values'])==6)
                for action in gui.ACTIONS:
                    picker.set(action);picker.event_generate('<<ComboboxSelected>>');root.update_idletasks()
                    labels=[w.cget('text') for w in widgets(root) if isinstance(w,gui.ttk.Label)]
                    self.assertIn(gui.HELP[gui.ACTIONS[action][0]],labels)
                    for key in gui.ACTIONS[action][1]:self.assertIn(gui.field_label(action,key),labels)
                    if 'output' in gui.ACTIONS[action][1]:
                        entries=[w for w in widgets(root) if type(w) is gui.ttk.Entry]
                        entries[-1].insert(0,gui.output_name(action))
                picker.set('4. 根据量测生成校准');picker.event_generate('<<ComboboxSelected>>');root.update_idletasks()
                entries=[w for w in widgets(root) if type(w) is gui.ttk.Entry]
                self.assertEqual(entries[-1].get(),'calibration-v1.json')
                picker.set('6. 生成更新与还原清单');picker.event_generate('<<ComboboxSelected>>');root.update_idletasks()
                labels=[w.cget('text') for w in widgets(root) if isinstance(w,gui.ttk.Label)]
                observed.update(title=root.title(),fields=labels,button=any(isinstance(w,gui.ttk.Button) and w.cget('text')=='执行离线操作' for w in widgets(root)))
            except Exception as exc:errors.append(str(exc))
            finally:root.destroy()
        root.after(80,inspect);gui.main(root)
        self.assertEqual(errors,[])
        self.assertIn('自定义',observed['title']);self.assertTrue(observed['button'])
        self.assertIn('原始 appFw.so',observed['fields']);self.assertIn('原始 cpapp-b.bin',observed['fields'])

if __name__=='__main__':unittest.main()
