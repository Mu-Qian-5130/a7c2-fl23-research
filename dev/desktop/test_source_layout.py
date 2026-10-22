"""Stable public imports and separated runtime/build modules, offline only."""
from pathlib import Path
import sys
from unittest.mock import patch
from desktopapp import drivers,macadmin
from desktopapp.platforms import usb_drivers,macos_authorization

ROOT=Path(__file__).resolve().parents[2]

def test_host_compatibility_imports_share_the_exact_module_object():
    assert drivers is usb_drivers
    assert macadmin is macos_authorization
    with patch.object(drivers,'scan',return_value={'mocked':True}):
        assert usb_drivers.scan()=={'mocked':True}

def test_sound_runtime_and_native_sources_are_in_src():
    sys.path.insert(0,str(ROOT/'src/shutter_sound'))
    import candidate,media,sound_cli,files_worker
    for module in (candidate,media,sound_cli,files_worker):
        assert Path(module.__file__).resolve().parent==ROOT/'src/shutter_sound'
    assert candidate.ROOT==ROOT
    for name in ('sound_probe.c','sound_files.c','buffer_probe.c'):
        assert (ROOT/'src/shutter_sound/native'/name).is_file()
    assert not (ROOT/'dev/shutter_sound/sound_cli.py').exists()
