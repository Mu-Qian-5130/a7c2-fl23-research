"""Portable artwork, unchanged fitting, source-bound record edits and UI routing."""
import base64
import copy
import io
import json
import os
from pathlib import Path
import struct
from unittest.mock import patch

import pytest
from PIL import Image
from desktopapp import cameraapi,menuicons,presets
from looktool import bundle,iconfile,lookfile


def sample():return lookfile.read(presets.catalog()[0]['path'])


def test_embedded_icon_copy_preserves_every_color_and_source_field(tmp_path):
    source=Path(presets.catalog()[0]['path']);before=source.read_bytes();doc=sample()
    output=tmp_path/'icon.a7look';icon=iconfile.from_text('Po')
    changed=iconfile.save_copy(source,output,icon)
    assert {k:v for k,v in changed.items() if k!='menu_icon'}==doc
    assert source.read_bytes()==before and lookfile.read(output)==changed
    assert len(iconfile.mask(icon))==494
    with pytest.raises(FileExistsError):iconfile.save_copy(source,output,icon)
    removed=iconfile.save_copy(output,tmp_path/'removed.a7look',None)
    assert removed==doc
    assert 'png_base64' not in lookfile.inventory(changed)['menu_icon']


@pytest.mark.parametrize('kind',['bad-base64','wrong-size','trailing-keys','empty','too-large'])
def test_invalid_icon_rejected(kind):
    icon=iconfile.from_text('NC')
    if kind=='bad-base64':icon['png_base64']='!'
    if kind=='wrong-size':
        out=io.BytesIO();Image.new('L',(27,19),255).save(out,format='PNG');icon['png_base64']=base64.b64encode(out.getvalue()).decode()
    if kind=='trailing-keys':icon['offset']=123
    if kind=='empty':
        out=io.BytesIO();Image.new('L',(26,19)).save(out,format='PNG');icon['png_base64']=base64.b64encode(out.getvalue()).decode()
    if kind=='too-large':icon['png_base64']='A'*30000
    with pytest.raises(ValueError):lookfile.validate(dict(sample(),menu_icon=icon))


def test_transparent_and_opaque_png_imports_use_the_actual_artwork(tmp_path):
    image=Image.new('RGBA',(26,19),(0,0,0,255));image.putpixel((12,9),(255,255,255,255))
    path=tmp_path/'opaque.png';image.save(path)
    assert sum(iconfile.mask(iconfile.from_png(path)))==255
    image=Image.new('RGBA',(26,19),(255,255,255,0));image.putpixel((12,9),(255,255,255,255));image.save(path)
    assert sum(iconfile.mask(iconfile.from_png(path)))==255


def test_usb_guard_remains_and_fixed_api_encodes_artwork_without_connecting(tmp_path):
    path=tmp_path/'icon.a7look';iconfile.save_copy(presets.catalog()[0]['path'],path,iconfile.from_text('CC'))
    options=dict(looks=[dict(slot=6,path=str(path))])
    with pytest.raises(ValueError,match='USB'):bundle.documents(options)
    from desktopapp.iconprotocol import unpack
    title,packet=cameraapi.prepare_look(path)
    assert title==sample()['name'] and len(unpack(packet)[1])==846
    selection,rows=bundle.documents(options,allow_menu_icons=True)
    assert rows[0]['slot']==6 and rows[0]['document']['menu_icon']
    assert bundle.documents(dict(looks=[presets.catalog()[0]]))[1][0]['document']==sample()


def bank(*,group=0,all_views=False):
    imagebank,codec=menuicons.vertical_modules();count=0x1880 if all_views else 0x940;descriptor=count|(((count+1)&~1)<<12)
    base=16+((descriptor>>11)&0x7ffc)
    source=bytearray(struct.pack('<8sHHI',imagebank.MAGIC,8,group,descriptor)+b'\xff\xff'*count)
    source.extend(bytes(base-len(source)))
    indices=[1]+[v for slot in range(6) for v in (0x6c5+slot,0x8ef+slot*13)]
    small=set()
    if all_views and group==0:
        small={0x181a+slot*13 for slot in range(6)};indices+=sorted(small)
    elif all_views and group==1:
        small={0x13a3+slot for slot in range(6)};indices=[1]+sorted(small)
    for index in indices:
        at=len(source);struct.pack_into('<H',source,16+2*index,(at-base)//4)
        width,height=(58,30) if index in small else (70,35)
        source.extend(struct.pack('<IIHHII',0x1a000000+(group<<13)+index,0xc0000000,width,height,0,0))
    for n,index in enumerate(indices):
        at=base+20*n;compact=index in small;raw=bytearray(3840 if compact else 5600);raw[0:2]=struct.pack('<H',0x111f+n*16)
        origin=(8*64+22)*2 if compact else (10*80+27)*2
        raw[origin:origin+2]=b'\xff\xff'
        payload=codec.compress(bytes(raw));source.extend(bytes((-len(source))%4))
        struct.pack_into('<II',source,at+12,len(payload),len(source)-at-4);source.extend(payload)
    source.extend(bytes((-len(source))%4));imagebank.inspect(source,group)
    return bytes(source)


def test_all_six_existing_slots_keep_other_records_old_payloads_and_inverse():
    imagebank,_=menuicons.vertical_modules();source=bank()
    icons={i:iconfile.from_text(text) for i,text in enumerate(presets.MENU_ICON_LABELS,1)}
    target,plan=menuicons.replace(source,icons)
    assert len(plan['windows'])==12 and plan['registered_ids_preserved']
    old,new=imagebank.inspect(source,0),imagebank.inspect(target,0)
    assert old['count']==new['count'] and old['unused']==new['unused']
    inverse=bytearray(target)
    for row in plan['windows']:
        at=row['offset'];inverse[at:at+8]=bytes.fromhex(row['before_hex'])
    assert inverse[:len(source)]==source
    again,second=menuicons.replace(target,icons)
    assert again==target and not second['windows']
    damaged=bytearray(source);row=old['records'][0x6c5];struct.pack_into('<H',damaged,row['at']+8,71)
    with pytest.raises(ValueError):menuicons.replace(bytes(damaged),{1:icons[1]})
    for payload in (b'',b'\xf0',b'\xf0\1\0\0',b'\xf0\1\x10\1'):
        with pytest.raises(ValueError):menuicons.decode(payload)

@pytest.mark.parametrize('group',[0,1])
def test_four_native_appearance_families_preserve_frames_and_repeat_exactly(group):
    imagebank,_=menuicons.vertical_modules();source=bank(group=group,all_views=True)
    icons={i:iconfile.from_text(label) for i,label in enumerate(presets.MENU_ICON_LABELS,1)}
    target,plan=menuicons.replace(source,icons,group=group,all_views=True)
    assert len(plan['windows'])==(18 if group==0 else 6)
    old,new=imagebank.inspect(source,group),imagebank.inspect(target,group)
    for change in plan['windows']:
        index=change['index'];a,b=old['records'][index],new['records'][index]
        compact=a['width']==58;n=3840 if compact else 5600
        before=menuicons.decode(source[a['start']:a['start']+a['size']],n)
        after=menuicons.decode(target[b['start']:b['start']+b['size']],n)
        stride,ox,oy,width,height=(64,22,8,22,16) if compact else (80,27,10,26,19)
        for y in range(a['height']):
            for x in range(stride):
                if ox<=x<ox+width and oy<=y<oy+height:continue
                at=(y*stride+x)*2;assert before[at:at+2]==after[at:at+2]
    again,noop=menuicons.replace(target,icons,group=group,all_views=True)
    assert again==target and not noop['windows']
    for n in (0,3839,3841,True):
        with pytest.raises(ValueError):menuicons.decode(b'\xf0',n)


def test_main_window_firmware_selection_embeds_icons_and_avoids_preset_conflicts(tmp_path):
    from PySide6 import QtWidgets as W
    from desktopapp.window import Window
    app=W.QApplication.instance() or W.QApplication([])
    path=tmp_path/'icon.a7look';iconfile.save_copy(presets.catalog()[0]['path'],path,iconfile.from_text('Po'))
    with patch.dict(os.environ,A7C2_DESKTOP_DATA=str(tmp_path/'app')):
        window=Window();window.timer.stop()
        try:
            window.local_custom_looks.setChecked(True)
            row=window.firmware_look_editor.add_row(6);row.set_file(path)
            assert not window.local_presets.isChecked()
            assert row.icon_button.isEnabled() and '已嵌入' in row.icon_status.text()
            args=window.firmware_args();assert args['looks'][0]['slot']==6 and args['preset_pack'] is None
            window.local_presets.setChecked(True)
            assert window.firmware_look_editor.rows==[row]
            assert window.firmware_args()['preset_pack']==presets.PACK and not window.firmware_args()['looks']
            window.local_custom_looks.setChecked(True)
            assert window.firmware_args()['looks'][0]['slot']==6
        finally:window.close()


def test_recommended_examples_use_RP_RN_and_uppercase_AS_without_refitting(tmp_path):
    source=[lookfile.read(r['path']) for r in presets.catalog()]
    rows=presets.menu_examples(tmp_path/'examples')
    assert presets.MENU_ICON_LABELS==('NC','CC','NN','AS','RP','RN')
    for old,row,label in zip(source,rows,presets.MENU_ICON_LABELS):
        document=lookfile.read(row['path'])
        assert document['menu_icon']['label']==label
        assert {k:v for k,v in document.items() if k!='menu_icon'}==old


def test_full_native_icon_edit_and_offline_selection_keep_the_dense_fit(tmp_path):
    from looktool import editrecipe
    from test_editrecipe import recipe
    document=sample();document.pop('native_photo',None)
    document.update(schema=lookfile.FULL_SCHEMA,edit_native=recipe())
    document['source_reference']={'method':'fixture','details':{'preserve':[1,2,3]}}
    source=tmp_path/'full.a7look';source.write_text(json.dumps(document),encoding='utf-8')
    before=source.read_bytes();packed=editrecipe.pack(document['edit_native'])
    path=tmp_path/'full-icon.a7look'
    changed=iconfile.save_copy(source,path,iconfile.from_text('AS'))
    assert {k:v for k,v in changed.items()if k!='menu_icon'}==document
    assert editrecipe.pack(changed['edit_native'])==packed and source.read_bytes()==before
    _,rows=bundle.documents(dict(looks=[dict(slot=4,path=str(path))]),allow_menu_icons=True)
    assert rows[0]['document']==changed
    from desktopapp.iconprotocol import unpack
    _,packet=cameraapi.prepare_look(path)
    color,_=unpack(packet)
    assert color[:8]==b'A7F2LOOK' and color[1223:]==packed
    plain=tmp_path/'full-plain.a7look';iconfile.save_copy(path,plain,None)
    assert lookfile.read(plain)==document
    assert cameraapi.prepare_look(plain)[1]==b'A7F2LOOK'+lookfile.validate(document)+packed
