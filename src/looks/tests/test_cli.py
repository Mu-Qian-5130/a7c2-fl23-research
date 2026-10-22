"""LUT-only portable CLI: current Python, preserved arguments, no USB/GUI/setup."""
from contextlib import redirect_stdout,redirect_stderr
import ast,importlib.util,io,json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('a7c2_lut_cli',ROOT/'lut.py')
cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)

class LutCliTests(unittest.TestCase):
    def test_lut_has_slot_restore_but_no_whole_camera_restore_entry(self):
        self.assertIn('restore-slot',cli.DEVICE_COMMANDS)
        with patch.object(cli,'missing_packages') as probe,redirect_stderr(io.StringIO()):
            for command in ('restore','rollback','rollback-verify','inspect-checkpoint'):
                self.assertEqual(cli.main([command,'unused']),2)
        probe.assert_not_called()
    def test_help_and_version_need_no_dependencies_or_device(self):
        with patch.object(cli,'missing_packages') as probe,redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main([]),0);self.assertEqual(cli.main(['--version']),0)
        probe.assert_not_called();self.assertIn('calibrate',out.getvalue())
    def test_doctor_reports_missing_deps_without_running_backend(self):
        for missing,expected in [([],0),(['numpy'],2)]:
            with patch.object(cli,'missing_packages',return_value=missing),redirect_stdout(io.StringIO()) as out:
                self.assertEqual(cli.main(['doctor']),expected)
            self.assertFalse(json.loads(out.getvalue())['camera_io'])
    def test_unknown_command_cannot_enter_backend(self):
        with patch.object(cli,'missing_packages') as probe,redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['not-a-command','--workspace','anything']),2)
        probe.assert_not_called()
    def test_missing_dependency_does_not_install_it(self):
        with patch.object(cli,'missing_packages',return_value=['numpy']),redirect_stderr(io.StringIO()) as error:
            self.assertEqual(cli.main(['plan','project.json']),2)
        self.assertIn('-m pip install',error.getvalue())
    def test_mac_routes_preserve_unicode_arguments_and_error_once(self):
        import looktool.__main__ as backend
        args=['inspect','/Volumes/相机 files/look.dcp']
        with patch.object(cli.sys,'platform','darwin'),patch.object(cli,'missing_packages',return_value=[]),patch.object(backend,'main',return_value=9) as run:
            self.assertEqual(cli.main(args),9)
        run.assert_called_once_with(args)
    def test_no_camera_gui_shell_or_installer_imports(self):
        tree=ast.parse((ROOT/'lut.py').read_text(encoding='utf-8'))
        imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        imports += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
        self.assertFalse(any(n.startswith(('usb','transport','pmca','tkinter','subprocess')) for n in imports))
    def test_real_plan_and_unicode_spaced_root_help(self):
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(['plan',str(ROOT/'src/looks/examples/six-looks.json')]),0)
        self.assertEqual(json.loads(out.getvalue())['selected_slots'],[1,2,3,4,5,6])
        with tempfile.TemporaryDirectory(prefix='色表 CLI space ') as folder:
            entry=Path(folder)/'lut.py';shutil.copyfile(ROOT/'lut.py',entry)
            result=subprocess.run([sys.executable,entry,'--help'],cwd=folder,capture_output=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stderr);self.assertIn('doctor',result.stdout)
            self.assertFalse((Path(folder)/'.venv').exists())

class SlotRestoreCliTests(unittest.TestCase):
    def test_slot_restore_routes_to_new_job_once(self):
        from unittest.mock import Mock
        from looktool import devicecli
        original=Mock();fresh=Mock();fresh.root=Path('new-job')
        fresh.restore_slot.return_value={'phase':'AWAITING_RELOAD','slot':6,'name':'Previous six'}
        def factory(folder,**kwargs):return original if Path(folder)==Path('original-job') else fresh
        with patch.object(devicecli,'settings',return_value={}),patch.object(devicecli,'Job',side_effect=factory),redirect_stdout(io.StringIO()):
            result=devicecli.main(['restore-slot','original-job','--work-dir','new-job','--backup-dir','new-backup','--battery-percent','90'])
        self.assertEqual(result,0);fresh.restore_slot.assert_called_once_with(original,90,Path('new-backup'))

class RecoveryEntryTests(unittest.TestCase):
    def test_help_needs_no_device_packages(self):
        result=subprocess.run([sys.executable,'-S',ROOT/'recovery.py','--help'],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('restore',result.stdout);self.assertIn('inspect',result.stdout)
    def test_independent_recovery_routes_backup_without_lut_job(self):
        spec=importlib.util.spec_from_file_location('test_recovery_entry',ROOT/'recovery.py')
        entry=importlib.util.module_from_spec(spec);spec.loader.exec_module(entry)
        from looktool import checkpointcli
        with patch.object(checkpointcli,'main',return_value=0) as run:
            self.assertEqual(entry.main(['restore','旧备份 folder','--work-dir','new work','--firmware-version','2.01','--battery-percent','90']),0)
        run.assert_called_once_with(['rollback','旧备份 folder','--firmware-version','2.01','--battery-percent','90','--work-dir','new work'])

if __name__=='__main__':unittest.main()
