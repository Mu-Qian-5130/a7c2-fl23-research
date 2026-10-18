"""The custom entry builds only offline commands and preserves file arguments."""
import ast,importlib.util,os
from pathlib import Path
import unittest
BASE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('custom_look_gui',BASE/'gui.py')
gui=importlib.util.module_from_spec(spec);spec.loader.exec_module(gui)

class CustomEntryTests(unittest.TestCase):
    def test_actions_are_offline_and_unknown_action_is_rejected(self):
        self.assertEqual({item[0] for item in gui.ACTIONS.values()},{'inspect','plan','check-bindings','fit','prepare-transition'})
        with self.assertRaises(ValueError):gui.build_arguments('install',{})
        tree=ast.parse((BASE/'gui.py').read_text(encoding='utf-8'))
        imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        imports += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
        self.assertFalse(any(n.startswith(('usb','transport','pmca')) for n in imports))
    def test_transition_preserves_unicode_paths_and_exact_layout(self):
        values={k:'D:/色表 test/'+k for k in ['candidate','ap','cp','bindings','output']}
        args=gui.build_arguments('生成色表更新清单',values)
        self.assertEqual(args,['prepare-transition']+[values[k] for k in ['candidate','ap','cp','bindings','output']]+['--layout','full7-v4'])
        with self.assertRaises(ValueError):gui.build_arguments('生成色表更新清单',values,'stock-anything')
    def test_missing_input_stops_before_command_creation(self):
        with self.assertRaises(ValueError):gui.build_arguments('拟合机内色表',{'project':'profile.json','output':' '})
        self.assertEqual(gui.build_arguments('检查 DCP / CUBE',{'source':'D:/looks/参考.cube'}),['inspect','D:/looks/参考.cube'])
    @unittest.skipUnless(os.name=='nt','Windows Tk window construction')
    def test_window_constructs_and_can_select_transition_without_running_it(self):
        root=gui.tk.Tk();root.withdraw();observed={};errors=[]
        def inspect():
            try:
                def widgets(parent):
                    result=[]
                    for child in parent.winfo_children():result.append(child);result.extend(widgets(child))
                    return result
                combos=[w for w in widgets(root) if isinstance(w,gui.ttk.Combobox)]
                picker=next(w for w in combos if len(w['values'])==5)
                picker.set('生成色表更新清单');picker.event_generate('<<ComboboxSelected>>');root.update_idletasks()
                labels=[w.cget('text') for w in widgets(root) if isinstance(w,gui.ttk.Label)]
                observed.update(title=root.title(),fields=labels,button=any(isinstance(w,gui.ttk.Button) and w.cget('text')=='执行离线操作' for w in widgets(root)))
            except Exception as exc:errors.append(str(exc))
            finally:root.destroy()
        root.after(80,inspect);gui.main(root)
        self.assertEqual(errors,[])
        self.assertIn('自定义',observed['title']);self.assertTrue(observed['button'])
        self.assertIn('原始 appFw.so',observed['fields']);self.assertIn('原始 cpapp-b.bin',observed['fields'])

if __name__=='__main__':unittest.main()
