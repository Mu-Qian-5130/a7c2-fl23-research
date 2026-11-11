"""Reviewed presentation contract, color retention and desktop compiler wiring."""
import json
from pathlib import Path
import shutil

import pytest
from PIL import Image
from desktopapp import presets
from looktool import iconfile,lookfile,looklabels


def test_complete_reviewed_plan_keeps_every_entry_and_shared_codes():
    rows=looklabels.catalog()
    assert len(rows)==41 and len({row['name'] for row in rows})==41
    assert [r['icon_text'] for r in rows[:14]]==[
        'F400','F200','F200','K100','K200','K200','K200','K400',
        '5213','5207','5219','5219','5203','5203']
    assert [r['icon_text'] for r in rows[22:28]]==['PN','PN','PR','RA','VE','HB']
    assert [r['icon_text'] for r in rows[-4:]]==['RN','RP','RS','RV']
    assert presets.MENU_ICON_LABELS==('NC','CC','NN','AS','RP','RN')


@pytest.mark.parametrize('name,expected,code',[
    ('GR Negative Film','Ricoh Negative Film','RN'),
    ('Classic Neg.','Fujifilm Classic Negative','NC'),
    ('Kodak Ultramax 400','Kodak UltraMax 400','K400'),
    ('Sony_ILCE-7CM2_Pro_Neg_Hi.dcp','Fujifilm Pro Neg. Hi','PN')])
def test_legacy_names_and_source_filenames_resolve_to_full_names(name,expected,code):
    result=looklabels.lookup(name)
    assert result['name']==expected and result['icon_text']==code


@pytest.mark.parametrize('text',['F400','F200','K100','K400','5213','5207','5219','5203','2383','RN','RP'])
def test_four_character_glyphs_are_distinct_bounded_portable_masks(text):
    value=iconfile.from_text(text);pixels=iconfile.mask(value)
    assert value['label']==text and len(pixels)==494
    image=Image.frombytes('L',(26,19),pixels)
    assert image.getbbox() is not None
    if text=='F400':assert pixels!=iconfile.mask(iconfile.from_text('F200'))


@pytest.mark.parametrize('text',['','ABCDE','F 40','A/B','A\n'])
def test_invalid_glyph_inputs_fail_before_any_output(text):
    with pytest.raises(ValueError):iconfile.from_text(text)


def test_custom_full_title_and_explicit_color_only_choice_are_preserved():
    name,icon=looklabels.metadata('My custom look',source='Fuji Pro 400.dcp')
    assert name=='My custom look' and icon['label']=='F400'
    assert looklabels.metadata('GR Positive Film',include_icon=False)==('Ricoh Positive Film',None)
    name,icon=looklabels.metadata('Fuji Pro 400',icon_text='TEST')
    assert name=='Fuji Pro 400' and icon['label']=='TEST'


def test_old_builtin_assets_refresh_without_changing_any_color_or_raw_field(tmp_path):
    folder=tmp_path/'desktop-assets/presets'/presets.PACK
    shutil.copytree(presets.ROOT/'desktop-assets/presets'/presets.PACK,folder)
    before=[]
    legacy=['Classic Neg.','Classic Chrome','Nostalgic Neg.','Astia','GR Positive Film','GR Negative Film']
    for slot,name in enumerate(legacy,1):
        path=folder/('slot%d.a7look'%slot);doc=lookfile.read(path);doc['name']=name
        path.write_text(json.dumps(doc),encoding='utf-8');before.append(doc)
    result=presets.refresh_assets(tmp_path)
    assert len(result)==6
    for slot,(old,name,label) in enumerate(zip(before,presets.NAMES,presets.MENU_ICON_LABELS),1):
        plain=lookfile.read(folder/('slot%d.a7look'%slot))
        menu=lookfile.read(folder/'MenuIcons'/('slot%d.a7look'%slot))
        assert plain['name']==menu['name']==name and menu['menu_icon']['label']==label
        stable=lambda doc:{k:v for k,v in doc.items()if k not in ('name','menu_icon')}
        assert stable(old)==stable(plain)==stable(menu)
        assert 'menu_icon' not in plain


def test_compiler_adapter_forwards_user_artwork_choice(monkeypatch,tmp_path):
    from desktopapp.actions import look_compiler
    from looktool import compilelook
    calls=[];monkeypatch.setattr(compilelook,'main',lambda args:calls.append(args)or 0)
    args=dict(source='source.dcp',name='Fuji Pro 400',output=str(tmp_path/'out.a7look'),model='model.npz')
    look_compiler.run(dict(args,menu_icon_text='F400'))
    look_compiler.run(dict(args,include_menu_icon=False,menu_icon_text='F400'))
    assert calls[0][calls[0].index('--menu-icon-text')+1]=='F400'
    assert '--without-menu-icon'in calls[1] and '--menu-icon-text'not in calls[1]


def test_paired_library_menu_companions_are_source_identical(tmp_path):
    import profilepack
    shutil.copytree(presets.ROOT/'desktop-assets/profile-library-v1',tmp_path/'desktop-assets/profile-library-v1')
    rows=profilepack.refresh_labels(tmp_path)
    values=profilepack.files(tmp_path)
    assert len(rows)==15 and len([p for p in values if p.startswith('MenuIcons/')])==15


def test_editor_renamed_copy_retains_original_and_every_fitting_field(tmp_path):
    source=tmp_path/'old.a7look';old=lookfile.read(presets.catalog()[4]['path'])
    old['name']='GR Positive Film';source.write_text(json.dumps(old),encoding='utf-8')
    original=source.read_bytes()
    changed=iconfile.save_copy(source,tmp_path/'new.a7look',iconfile.from_text('RP'),name='Ricoh Positive Film')
    assert changed['name']=='Ricoh Positive Film' and changed['menu_icon']['label']=='RP'
    assert {k:v for k,v in changed.items()if k not in ('name','menu_icon')}=={k:v for k,v in old.items()if k!='name'}
    assert source.read_bytes()==original


@pytest.mark.parametrize('value',['../escape.a7look','C:/escape.a7look','other.a7look',42])
def test_profile_menu_paths_remain_inside_the_companion_folder(value):
    import profilepack
    with pytest.raises(ValueError):profilepack.menu_paths(dict(profiles=[dict(menu_a7look=value)]))


def test_desktop_compiler_autofill_preserves_manual_icon_and_passes_toggle(monkeypatch,tmp_path):
    from PySide6 import QtWidgets as W
    from desktopapp.window import Window
    monkeypatch.setenv('A7C2_DESKTOP_DATA',str(tmp_path/'app'))
    app=W.QApplication.instance()or W.QApplication([])
    window=Window();calls=[]
    monkeypatch.setattr(window,'launch',lambda action,args:calls.append((action,args)))
    def inspect(dialog):
        window.fields['compile_name'].setText('')
        window.fields['compile_source'].setText(str(tmp_path/'Fuji Pro 400.dcp'))
        assert window.text('compile_name')=='Fuji Pro 400'
        assert window.text('compile_icon')=='F400' and window.fields['compile_icon'].maxLength()==4
        window.fields['compile_name'].setText('Ricoh Negative Film')
        assert window.text('compile_icon')=='RN'
        window.fields['compile_icon'].setText('TEST')
        window.fields['compile_name'].setText('Ricoh Positive Film')
        assert window.text('compile_icon')=='TEST'
        box=next(x for x in dialog.findChildren(W.QCheckBox)if x.text().startswith('附带图标'))
        box.setChecked(False);assert not window.fields['compile_icon'].isEnabled()
        next(x for x in dialog.findChildren(W.QPushButton)if x.text()=='开始生成').click()
        return 0
    monkeypatch.setattr(W.QDialog,'exec',inspect)
    try:window.compiler_dialog()
    finally:window.close();app.processEvents()
    assert calls[0][0]=='compile_look' and calls[0][1]['include_menu_icon'] is False
