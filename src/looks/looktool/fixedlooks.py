"""Fixed native presets, preserving unselected slots and existing image IDs."""
from functools import lru_cache
import json
from pathlib import Path
import struct

@lru_cache(maxsize=1)
def asset():
    data=json.loads((Path(__file__).resolve().parents[1]/'assets/fixed-looks-v1.json').read_text(encoding='ascii'))
    if data['schema']!='a7c2-fixed-looks/1' or len(data['templates'])!=64:
        raise ValueError('Unknown fixed-look recipe')
    return data

def windows(mask,*,enabled=True):
    if type(mask) is not int or mask not in range(64):raise ValueError('Expected six-slot bitmap')
    data=asset()
    result={int(k):bytes.fromhex(v) for k,v in (data['templates'][mask] if enabled else data['before']).items()}
    for slot,row in enumerate(data['menu_image_fields']):
        result[row['offset']]=(struct.pack('<II',row['normal'],row['selected']) if mask>>slot&1 else bytes.fromhex(row['before']))
    return result

def transport(ap):
    """Recognize only the converter window, including its paired title code."""
    value=ap[0x35287f0:0x3528874].hex();data=asset()
    old=data.get('legacy_transport_templates',())
    for mask,raw in enumerate(data.get('fixed_converter_templates',())):
        if mask<len(old) and value==raw+old[mask][160:]:return dict(kind='fixed',mask=mask)
    for mask,raw in enumerate(old):
        if value==raw:return dict(kind='legacy',mask=mask)
    return dict(kind='other',mask=None)

def inspect(ap):
    """Reject mixed/partial generations rather than silently treating as stock."""
    data=asset();before={int(k):bytes.fromhex(v) for k,v in data['before'].items()}
    for key,value in data['read_only'].items():
        at=int(key);expected=bytes.fromhex(value)
        if ap[at:at+len(expected)]!=expected:raise ValueError('Fixed-look native resource table conflicts')
    marker=0x21ab9e8;current=ap[marker:marker+len(before[marker])]
    candidates=[(False,0)] if current==before[marker] else [(True,m) for m in range(64)
        if current==bytes.fromhex(data['templates'][m][str(marker)])]
    for enabled,mask in candidates:
        if all(ap[at:at+len(raw)]==raw for at,raw in windows(mask,enabled=enabled).items()):
            route=transport(ap)
            if enabled and route['kind']=='fixed' and route['mask']!=mask:
                raise ValueError('Fixed-look snapshot converter and menu masks differ')
            return dict(mask=mask,slots=[i+1 for i in range(6) if mask>>i&1],
                enabled=enabled,
                base_picker_locked=bool(mask),parameters_editable=True,
                snapshot_base_normalized=enabled and route['kind']=='fixed' and route['mask']==mask,
                code_extent_growth=0,registered_image_ids_added=0)
    raise ValueError('Fixed-look native bytes conflict or contain mixed generations')

def patch(ap,mask):
    before=inspect(ap);route=transport(ap);target=bytearray(ap)
    for at,raw in windows(mask).items():target[at:at+len(raw)]=raw
    # A UI-only research patch on stock must not install a color transport.
    # Real composition has already prepared a matching selected-slot converter.
    if route['kind'] in ('fixed','legacy') and route['mask']==mask:
        target[0x35287f0:0x3528840]=bytes.fromhex(asset()['fixed_converter_templates'][mask])
    target=bytes(target)
    if len(target)!=len(ap) or inspect(target)['mask']!=mask:
        raise ValueError('Fixed-look target readback differs')
    return target

def restore(ap):
    state=inspect(ap);target=bytearray(ap)
    for at,raw in windows(0,enabled=False).items():target[at:at+len(raw)]=raw
    if state['snapshot_base_normalized']:
        target[0x35287f0:0x3528840]=bytes.fromhex(asset()['legacy_transport_templates'][state['mask']][:160])
    result=bytes(target)
    if inspect(result)['enabled']:raise ValueError('Fixed-look restoration differs')
    return result

def active(ap):return bool(inspect(ap)['mask'])

def present(ap):
    # Two independent entry markers ensure a partially installed generation is
    # validated and rejected, rather than being misclassified as an old runtime.
    return (ap[0x1b5cd14:0x1b5cd18]==bytes.fromhex('f37bbea9') or
            ap[0x21ab9e8:0x21ab9ec]==bytes.fromhex('f37bbea9'))
