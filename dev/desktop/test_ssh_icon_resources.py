"""Artwork publication uses an exact baseline and advances the correct namespace."""
import json
from pathlib import Path

from desktopapp import iconresources, menuicons, sshupdates, lookbatch
from looktool import iconfile, lookfile
from test_menu_icons import bank
from test_ssh_updates import Connection


def source_banks():
    menuicons.vertical_modules()
    from verticaltool import nativeportrait
    a,b=bank(group=0,all_views=True),bank(group=1,all_views=True)
    return dict(zip(iconresources.NAMES,(a,b,nativeportrait.prepare(a,0),nativeportrait.prepare(b,1))))


def test_all_orientations_are_owned_idempotent_and_keep_original_resources():
    from verticaltool import nativeportrait
    before=source_banks();icon=iconfile.from_mask(bytes((i*17)%256 for i in range(494)))
    after=iconresources.replace(before,{2:icon})
    assert all(after[n]!=before[n] for n in iconresources.NAMES)
    assert all(nativeportrait.owned(after[n]) for n in iconresources.NAMES[2:])
    assert iconresources.replace(after,{2:icon})==after
    assert set(after)==set(before)


def test_compile_ssh_artwork_carries_four_images_without_relaxing_usb_guard(tmp_path,monkeypatch):
    from desktopapp import presets
    from looktool import bundle
    import pytest
    images=source_banks();current={'appFw.so':b'AP','cpapp-b.bin':b'CP',**{'images/'+k:v for k,v in images.items()}}
    source=tmp_path/'look.a7look'
    iconfile.save_copy(presets.catalog()[0]['path'],source,iconfile.from_mask(bytes([255])*494))
    with pytest.raises(ValueError,match='USB'):lookbatch.options([dict(slot=2,path=str(source))])
    monkeypatch.setattr(sshupdates,'baseline',lambda folder:(tmp_path,current,[{},{}],{}))
    monkeypatch.setattr(bundle,'plan',lambda *args:(dict(current),[{},{}],{}))
    result=sshupdates.compile_look(tmp_path,[dict(slot=2,path=str(source))],tmp_path/'prepared')
    assert {r['path'] for r in result['rows']}=={'/usr/share/app/'+n for n in iconresources.NAMES}
    assert not sshupdates.allowed('/usr/share/app/image_02_32_IPSX.uxc')


def test_reload_advances_images_namespace_and_preserves_unrelated_baseline(tmp_path):
    source=tmp_path/'baseline';(source/'images').mkdir(parents=True)
    name=iconresources.NAMES[0];(source/'images'/name).write_bytes(b'old')
    (source/'cpapp-b.bin').write_bytes(b'unchanged CP');(source/'baseline.private.json').write_text('{}')
    folder=tmp_path/'update';path='/usr/share/app/'+name
    sshupdates.save_package({path:(b'old',b'new')},folder,'looks',source_baseline=source)
    connection=Connection({path:b'old'});sshupdates.apply(folder,connection)
    connection.boot='00000000-0000-0000-0000-000000000002'
    result=sshupdates.verify_reload(folder,connection);next_baseline=Path(result['next_baseline'])
    assert (next_baseline/'images'/name).read_bytes()==b'new'
    assert not (next_baseline/'resources'/name).exists()
    assert (next_baseline/'cpapp-b.bin').read_bytes()==b'unchanged CP'
