"""Helper preparation stays offline from the camera and carries full payloads."""
import io,tarfile,zipfile
from pathlib import Path
from unittest.mock import patch
import pytest
from desktopapp import exiftool


def zip_data(entries):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:
        for name,value in entries.items():archive.writestr(name,value)
    return stream.getvalue()


def test_windows_archive_retains_companion_files_and_renames_launcher(tmp_path):
    data=zip_data({'exiftool-13.59_64/exiftool(-k).exe':b'launcher',
                   'exiftool-13.59_64/exiftool_files/perl.dll':b'perl',
                   'exiftool-13.59_64/exiftool_files/LICENSE':b'license'})
    tool=exiftool.unpack(data,tmp_path,'win32')
    assert tool.name=='exiftool.exe'
    assert (tmp_path/'exiftool_files/perl.dll').read_bytes()==b'perl'
    assert (tmp_path/'exiftool_files/LICENSE').read_bytes()==b'license'


def test_archive_path_cannot_escape_helper_directory(tmp_path):
    with pytest.raises(ValueError,match='archive path'):
        exiftool.unpack(zip_data({'../escape.exe':b'x'}),tmp_path,'win32')


def test_mac_perl_distribution_keeps_modules_license_and_execution_mode(tmp_path):
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w:gz') as archive:
        for name,value in [('exiftool',b'#!/usr/bin/perl'),('lib/Image/ExifTool.pm',b'module'),('LICENSE',b'license')]:
            item=tarfile.TarInfo('Image-ExifTool-13.59/'+name);item.size=len(value)
            archive.addfile(item,io.BytesIO(value))
    tool=exiftool.unpack(stream.getvalue(),tmp_path,'darwin')
    assert tool.name=='exiftool'
    assert (tmp_path/'lib/Image/ExifTool.pm').read_bytes()==b'module'
    assert (tmp_path/'LICENSE').read_bytes()==b'license'


def test_stale_saved_path_uses_bundled_helper_without_network(tmp_path,monkeypatch):
    monkeypatch.setattr(exiftool,'ROOT',tmp_path)
    tool=exiftool.executable(tmp_path/'desktop-assets/exiftool');tool.parent.mkdir(parents=True);tool.write_bytes(b'exiftool')
    with patch.object(exiftool,'install') as download,patch.object(exiftool.shutil,'which',return_value=None):
        assert exiftool.ensure('old-machine/missing.exe')==str(tool.resolve())
    download.assert_not_called()


def test_missing_helper_prepares_it_automatically(tmp_path,monkeypatch):
    monkeypatch.setattr(exiftool,'ROOT',tmp_path)
    monkeypatch.setenv('A7C2_DESKTOP_DATA',str(tmp_path/'app'))
    tool=tmp_path/'managed/exiftool.exe'
    with patch.object(exiftool,'install',return_value=tool) as download,patch.object(exiftool.shutil,'which',return_value=None):
        assert exiftool.ensure('missing.exe')==str(tool.resolve())
    download.assert_called_once()
