"""Self-contained small image-bank additions and recovery over current bytes."""
import json
import struct
from . import imagebank,portraitlayout,portraitlines

MAGIC=b'A7PFBK01'
RETIRED_PANEL_OPTIONS=bytes.fromhex('0200010001000000000004000400040004000000')


def restore_shared_panel(original,target,plan):
    """Retire .4's shared slicing edit after its physical landscape regression.

    Keep its receipt as undo evidence. Both original and experimental bytes
    are recorded there already, so restoring the original options needs no
    extra appended receipt or resource payload.
    """
    row=imagebank.inspect(original,1)['records'][0x291]
    at=row['at']+12
    before=original[at:at+20]
    if row['field']!=32 or before!=bytes.fromhex('020001000000000000007e0000007e0000000000'):
        raise ValueError('Native Creative Look panel slice options differ')
    existing=next((w for w in plan['windows'] if w['offset']==at),None)
    if existing is None:return target,plan
    if (existing['before_hex']!=before.hex() or
            existing['after_hex'] not in (before.hex(),RETIRED_PANEL_OPTIONS.hex()) or
            target[at:at+20] not in (before,RETIRED_PANEL_OPTIONS)):
        raise ValueError('Creative Look panel slice plan differs')
    changed=bytearray(target);changed[at:at+20]=before
    windows=[dict(w,after_hex=before.hex(),previous_hex=RETIRED_PANEL_OPTIONS.hex())
        if w['offset']==at else w for w in plan['windows']]
    return bytes(changed),dict(plan,windows=windows)


def compatible(current,before,after,previous=None):
    previous=before if previous is None else previous
    return len(current)==len(before)==len(after)==len(previous) and all(c in (a,b,p) for c,a,b,p in zip(current,before,after,previous))


def seal(target,plan):
    receipt={key:value for key,value in plan.items() if key not in ('append_hex','camera_io')}
    payload=json.dumps(receipt,sort_keys=True,separators=(',',':')).encode('ascii')
    payload+=b' '*((-len(payload))%4)
    result=target+payload+struct.pack('<I8s',len(payload),MAGIC)
    plan=dict(plan,target_bytes=len(result),append_hex=result[plan['source_bytes']:].hex())
    return result,plan


def current(source,group):
    """Recover the last complete footer, including an interrupted later append."""
    source=bytes(source);marker=source.rfind(MAGIC)
    if marker<0:
        parsed=imagebank.inspect(source,group)
        end=max(max(row['at']+row['field']+8,row['start']+row['size']) for row in parsed['records'].values())
        return source[:(end+3)&~3],None,None
    if marker<4:raise ValueError('Portrait resource footer is incomplete')
    size=struct.unpack_from('<I',source,marker-4)[0]
    if size>65536 or size+4>marker:raise ValueError('Portrait resource footer is incomplete')
    saved=json.loads(source[marker-4-size:marker-4])
    if saved.get('schema')!='a7c2-image-bank-additions/1' or saved.get('group')!=group:
        raise ValueError('Portrait resource footer identifies a different bank')
    original_size=saved['source_bytes'];end=marker+len(MAGIC)
    if not original_size<=saved['target_bytes']<=marker-4-size:
        raise ValueError('Portrait resource footer sizes differ')
    original=bytearray(source[:original_size]);committed=bytearray(source[:end])
    for window in saved['windows']:
        at=window['offset'];before=bytes.fromhex(window['before_hex']);after=bytes.fromhex(window['after_hex'])
        previous=bytes.fromhex(window.get('previous_hex',window['before_hex']))
        if not 0<=at<=at+len(before)<=original_size or not compatible(source[at:at+len(before)],before,after,previous):
            raise ValueError('Portrait resource edit conflicts at '+hex(at))
        original[at:at+len(before)]=before;committed[at:at+len(after)]=after
    imagebank.inspect(original,group)
    plan=dict(saved,target_bytes=end,append_hex=bytes(committed[original_size:]).hex(),camera_io=False)
    return bytes(original),bytes(committed),plan


def baseline(source,group):return current(source,group)[0]


def prepare(source,group):
    source=bytes(source);original,committed,saved=current(source,group)
    images=[]
    for row in portraitlines.specs():
        old=0x02000000+row['group']*8192+row['index']
        if row['group']!=group or old not in portraitlayout.IMAGES:continue
        new=portraitlayout.IMAGES[old]
        images.append(dict(index=(new-0x02000000)%8192,width=row['portrait'][0],height=row['portrait'][1],
            payload=portraitlines.compress(portraitlines.raster(row)),options_hex=row.get('options_hex','')))
    if saved is None:
        target,plan=imagebank.add(original,group,images)
        target,plan=seal(target,plan)
    else:
        records=imagebank.inspect(committed,group)['records'];missing=[];revised=False
        for image in images:
            row=records.get(image['index'])
            if row is None:missing.append(image);continue
            if (image['index'] not in saved['new_indices'] or
                (row['width'],row['height'])!=(image['width'],image['height']) or
                committed[row['start']:row['start']+row['size']]!=image['payload']):
                raise ValueError('An installed portrait image conflicts at '+hex(image['index']))
            actual=committed[row['at']+12:row['at']+row['field']]
            if actual!=bytes.fromhex(image['options_hex']):
                legacy=bytes.fromhex('020001000000000000007e0000007e0000000000')
                if not (image['index']==0x1ebe and row['field']==32 and actual==legacy and not image['options_hex']):
                    raise ValueError('An installed portrait option conflicts at '+hex(image['index']))
                # The first panel candidate retained horizontal slice margins.
                # Keep its pixels and use a plain native-sized portrait image.
                at=row['at'];value=struct.pack('<IIHHII',0x1a000000+group*8192+image['index'],
                    0xc0000000,image['width'],image['height'],row['size'],row['start']-at-4)
                updated=bytearray(committed);updated[at:at+20]=value;committed=bytes(updated)
                owner=next(w for w in saved['windows'] if w['offset']<=at and at+40<=w['offset']+len(bytes.fromhex(w['after_hex'])))
                owner['previous_hex']=owner['after_hex']
                owner['after_hex']=committed[owner['offset']:owner['offset']+len(bytes.fromhex(owner['after_hex']))].hex()
                revised=True
        if not missing:
            target,plan=committed,saved
            if revised:
                plan=dict(plan,target_bytes=len(target));target,plan=seal(target,plan)
        else:
            # Keep former appended pixels at their old offsets while mapped.
            target,addition=imagebank.add(committed,group,missing)
            windows=list(saved['windows'])
            for row in addition['windows']:
                at=row['offset'];size=len(bytes.fromhex(row['before_hex']))
                if at+size>len(original):raise ValueError('Incremental portrait metadata exceeds original bank')
                if any(at<old['offset']+len(bytes.fromhex(old['before_hex'])) and old['offset']<at+size for old in windows):
                    raise ValueError('Incremental portrait metadata overlaps an existing edit')
                windows.append(dict(row,before_hex=original[at:at+size].hex()))
            plan=dict(saved,source_bytes=len(original),target_bytes=len(target),windows=windows,
                new_indices=saved['new_indices']+addition['new_indices'],
                additional_relocated_indices=saved.get('additional_relocated_indices',[])+[addition['relocated_index']],
                append_hex=target[len(original):].hex())
            target,plan=seal(target,plan)
    if group==1:target,plan=restore_shared_panel(original,target,plan)
    if len(source)<len(original) or len(source)>len(target):raise ValueError('Portrait resource size is outside this operation')
    tail=source[len(original):]
    if tail!=target[len(original):len(source)]:
        raise ValueError('Unrecognized data after the original image bank; no bytes were removed')
    for window in plan['windows']:
        at=window['offset'];before=bytes.fromhex(window['before_hex']);after=bytes.fromhex(window['after_hex'])
        previous=bytes.fromhex(window.get('previous_hex',window['before_hex']))
        if not compatible(source[at:at+len(before)],before,after,previous):
            raise ValueError('Portrait resource edit conflicts at '+hex(at))
    return original,target,plan
