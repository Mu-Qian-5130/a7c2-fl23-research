"""A locally loaded Zig package must work in compiler subprocesses too."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from looktool import nativebuild


class ZigDiscoveryTests(unittest.TestCase):
    def test_package_executable_is_used_without_child_module_lookup(self):
        with tempfile.TemporaryDirectory() as directory:
            binary=Path(directory)/('zig.exe' if os.name=='nt' else 'zig');binary.write_bytes(b'fixture')
            spec=SimpleNamespace(submodule_search_locations=[directory])
            with patch.object(nativebuild.shutil,'which',return_value=None),patch.object(nativebuild.importlib.util,'find_spec',return_value=spec):
                self.assertEqual(nativebuild.zig_command(),[str(binary.resolve())])

    def test_explicit_executable_remains_supported(self):
        self.assertEqual(nativebuild.zig_command('compiler/zig'),[str(Path('compiler/zig').resolve())])
