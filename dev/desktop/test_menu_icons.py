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


def test_device_adapters_reject_before_connecting_but_offline_documents_accept(tmp_path):
    path=tmp_path/'icon.a7look';iconfile.save_copy(presets.catalog()[0]['path'],path,iconfile.from_text('CC'))
    options=dict(looks=[dict(slot=6,path=str(path))])
    with pytest.raises(ValueError,match='USB'):bundle.documents(options)
    with pytest.raises(ValueError,match='USB'):cameraapi.prepare_look(path)
    selection,rows=bundle.documents(options,allow_menu_icons=True)
    assert rows[0]['slot']==6 and rows[0]['document']['menu_icon']
    assert bundle.documents(dict(looks=[presets.catalog()[0]]))[1][0]['document']==sample()


def bank():
    imagebank,codec=menuicons.vertical_modules();count=0x940;descriptor=count|(((count+1)&~1)<<12)
    base=16+((descriptor>>11)&0x7ffc)
    source=bytearray(struct.pack('<8sHHI',imagebank.MAGIC,8,0,descriptor)+b'\xff\xff'*count)
    source.extend(bytes(base-len(source)))
    indices=[1]+[v for slot in range(6) for v in (0x6c5+slot,0x8ef+slot*13)]
    for index in indices:
        at=len(source);struct.pack_into('<H',source,16+2*index,(at-base)//4)
        source.extend(struct.pack('<IIHHII',0x1a000000+index,0xc0000000,70,35,0,0))
    for n,index in enumerate(indices):
        at=base+20*n;raw=bytearray(5600);raw[0:2]=struct.pack('<H',0x111f+n*16)
        raw[((10*80+27)*2):((10*80+27)*2)+2]=b'\xff\xff'
        payload=codec.compress(bytes(raw));source.extend(bytes((-len(source))%4))
        struct.pack_into('<II',source,at+12,len(payload),len(source)-at-4);source.extend(payload)
    source.extend(bytes((-len(source))%4));imagebank.inspect(source,0)
    return bytes(source)


def test_all_six_existing_slots_keep_other_records_old_payloads_and_inverse():
    imagebank,_=menuicons.vertical_modules();source=bank()
    icons={i:iconfile.from_text(text) for i,text in enumerate(('NC','CC','NN','As','GR+','GR-'),1)}
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


def test_main_window_firmware_selection_embeds_icons_and_avoids_preset_conflicts(tmp_path):
    from PySide6 import QtWidgets as W
    from desktopapp.window import Window
    app=W.QApplication.instance() or W.QApplication([])
    path=tmp_path/'icon.a7look';iconfile.save_copy(presets.catalog()[0]['path'],path,iconfile.from_text('Po'))
    with patch.dict(os.environ,A7C2_DESKTOP_DATA=str(tmp_path/'app')):
        window=Window();window.timer.stop()
        try:
            row=window.firmware_look_editor.add_row(6);row.set_file(path)
            assert not window.local_presets.isChecked()
            assert row.icon_button.isEnabled() and '已嵌入' in row.icon_status.text()
            args=window.firmware_args();assert args['looks'][0]['slot']==6 and args['preset_pack'] is None
            window.local_presets.setChecked(True)
            assert not window.firmware_look_editor.rows and window.firmware_args()['preset_pack']==presets.PACK
        finally:window.close()
