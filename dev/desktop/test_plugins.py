"""Plugin helper refresh never overwrites an executable used by Lightroom."""
import json
from pathlib import Path

import pytest

from desktopapp import plugins,exiftool


@pytest.mark.parametrize('updated',[False,True],ids=['same_payload','updated_companion'])
def test_existing_locked_helper_is_reused_or_replaced_at_a_new_path(tmp_path,monkeypatch,updated):
    app=tmp_path/'app';monkeypatch.setenv('A7C2_DESKTOP_DATA',str(app))
    monkeypatch.setenv('APPDATA',str(tmp_path/'roaming'))
    monkeypatch.setattr(plugins.sys,'platform','win32');monkeypatch.setattr(plugins.sys,'frozen',True,raising=False)
    monkeypatch.setattr(plugins,'ROOT',tmp_path/'bundle')
    source=tmp_path/'bundle/exiftool/exiftool.exe';source.parent.mkdir(parents=True)
    source.write_bytes(b'same-launcher')
    (source.parent/'exiftool_files').mkdir()
    (source.parent/'exiftool_files/exiftool.pl').write_bytes(b'new' if updated else b'old')
    legacy=app/'helpers/exiftool/exiftool.exe';legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b'same-launcher');(legacy.parent/'exiftool_files').mkdir()
    (legacy.parent/'exiftool_files/exiftool.pl').write_bytes(b'old')
    monkeypatch.setattr(exiftool,'ensure',lambda preferred=None:str(source))
    copy=plugins.shutil.copy2
    def locked(src,dst,*args,**kwargs):
        if Path(dst)==legacy:raise PermissionError(13,'helper is running',str(dst))
        return copy(src,dst,*args,**kwargs)
    monkeypatch.setattr(plugins.shutil,'copy2',locked)
    result=plugins.install({})
    settings=json.loads(Path(result['settings']).read_text())
    tool=Path(settings['exiftool'])
    assert tool.is_file() and (tool==legacy)==(not updated)
    assert (tool.parent/'exiftool_files/exiftool.pl').read_bytes()==(b'new' if updated else b'old')
    assert (legacy.parent/'exiftool_files/exiftool.pl').read_bytes()==b'old'
    again=plugins.install({})
    assert json.loads(Path(again['settings']).read_text())['exiftool']==str(tool)


def test_unfrozen_gui_passes_managed_helper_without_another_mutable_copy(tmp_path,monkeypatch):
    from looktool import rawauto
    monkeypatch.setenv('A7C2_DESKTOP_DATA',str(tmp_path/'app'))
    monkeypatch.setattr(plugins.sys,'platform','win32');monkeypatch.setattr(plugins.sys,'frozen',False,raising=False)
    tool=tmp_path/'helper.exe';tool.write_bytes(b'exiftool')
    monkeypatch.setattr(exiftool,'ensure',lambda preferred=None:str(tool))
    def install(path,**kwargs):
        assert kwargs['copy_exiftool'] is False
        assert Path(path).is_file()
        return dict(exiftool=path)
    monkeypatch.setattr(rawauto,'install',install)
    assert Path(plugins.install({})['exiftool']).name=='exiftool.exe'

