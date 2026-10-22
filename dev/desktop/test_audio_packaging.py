"""Real generated-audio conversion and frozen-build dependency regressions."""
import ast
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'dev/shutter_sound'))
spec = importlib.util.spec_from_file_location('desktop_offline_smoke',
                                            ROOT / 'dev/desktop/offline_smoke.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class AudioPackagingTests(unittest.TestCase):
    def test_generated_mono_stereo_and_mp3_have_native_payload_and_24khz_preview(self):
        from looktool import devicesession
        with patch.object(devicesession, 'Camera', side_effect=AssertionError('No camera in audio conversion')):
            report = smoke.check_audio_conversion()
        self.assertEqual([report[name] for name in ('mono_wav', 'stereo_wav', 'stereo_mp3')],
                         ['passed'] * 3)
        self.assertFalse(report['camera_io'])
        self.assertEqual(report['preview_rate_hz'], 24000)

    def test_frozen_self_test_fails_for_missing_wave_instead_of_reporting_success(self):
        with patch.dict(sys.modules, {'wave': None}):
            with self.assertRaises(ModuleNotFoundError):
                smoke.check_audio_conversion()

    def test_spec_explicitly_collects_lazy_wave_import(self):
        tree = ast.parse((ROOT / 'dev/desktop/desktop.spec').read_text(encoding='utf-8'))
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Tuple):
                names = [item.id for item in node.targets[0].elts]
                if 'hidden' in names:
                    hidden = ast.literal_eval(node.value.elts[names.index('hidden')])
                    self.assertIn('wave', hidden)
                    break
        else:
            self.fail('Explicit hidden-import collection missing from desktop.spec')

    def test_spec_collects_sound_install_emulator_and_requirements_pin_it(self):
        tree=ast.parse((ROOT/'dev/desktop/desktop.spec').read_text(encoding='utf-8'))
        packages=[]
        for node in tree.body:
            if isinstance(node,ast.For) and isinstance(node.iter,ast.Tuple):
                try:packages.extend(ast.literal_eval(node.iter))
                except ValueError:pass
        self.assertIn('unicorn',packages)
        self.assertIn('unicorn==2.1.3',(ROOT/'desktop-requirements.txt').read_text())
