"""Portable wire integrity, feature negotiation and no partial legacy import."""
import base64
import copy
import hashlib
import json

import pytest
from desktopapp import cameraapi, iconprotocol
from looktool import iconfile, lookfile


def document():
    return dict(schema=lookfile.SCHEMA, target=lookfile.TARGET, base='ST', name='Artwork',
                table_format=lookfile.FORMAT, table_base64=base64.b64encode(bytes(1215)).decode(),
                menu_icon=iconfile.from_mask(bytes((i * 13) % 256 for i in range(494))))


def test_artwork_envelope_retains_exact_legacy_color_and_independent_compact_mask():
    doc=document();before=copy.deepcopy(doc)
    packed=cameraapi.look_payload(doc)
    color,masks=iconprotocol.unpack(packed)
    plain=dict(doc);plain.pop('menu_icon')
    assert color==cameraapi.look_payload(plain)
    assert len(packed)==2218 and len(masks)==846
    assert masks[:494]==iconfile.mask(doc['menu_icon'])
    assert doc==before


def test_artwork_envelope_retains_every_full_native_parameter():
    from test_editrecipe import recipe
    doc=document();doc.update(schema=lookfile.FULL_SCHEMA,edit_native=recipe())
    packed=cameraapi.look_payload(doc);color,_=iconprotocol.unpack(packed)
    plain=dict(doc);plain.pop('menu_icon')
    assert color==cameraapi.look_payload(plain) and len(packed)==4317


@pytest.mark.parametrize('kind',['hash','size','magic','mask','extra','truncated'])
def test_malformed_envelopes_are_rejected(kind):
    raw=bytearray(cameraapi.look_payload(document()))
    if kind=='hash':raw[-1]^=1
    if kind=='size':raw[8]^=1
    if kind=='magic':raw[0]^=1
    if kind=='mask':
        raw[16+1324:16+1324+494]=bytes(494)
        raw[-32:]=hashlib.sha256(raw[:-32]).digest()
    if kind=='extra':raw+=b'0'
    if kind=='truncated':raw=raw[:-1]
    with pytest.raises(ValueError):iconprotocol.unpack(bytes(raw))


def test_old_firmware_is_not_sent_a_partial_color_or_name_write(tmp_path):
    source=tmp_path/'icon.a7look';source.write_text(json.dumps(document()))
    class Old:
        def __init__(self):self.calls=[]
        def execute_api(self,command,payload):
            self.calls.append((command,payload));return {'slots':[1,2,3,4,5,6]}
    old=Old()
    with pytest.raises(ValueError,match='没有发送'):cameraapi.apply_look(old,2,source)
    assert old.calls==[(cameraapi.COMMAND+' info',None)]


def test_capable_firmware_receives_one_complete_transaction(tmp_path):
    source=tmp_path/'icon.a7look';source.write_text(json.dumps(document()))
    class New:
        def __init__(self):self.calls=[]
        def execute_api(self,command,payload):
            self.calls.append((command,payload))
            return {'menu_icons_protocol':1} if command.endswith(' info') else {'state':'pending_reload','menu_icons':True}
    new=New();result=cameraapi.apply_look(new,2,source)
    assert result['menu_icons'] is True and len(new.calls)==2
    assert new.calls[1][0]==cameraapi.COMMAND+' look 2 Artwork'
    assert iconprotocol.unpack(new.calls[1][1])[0]==bytes(1324)
