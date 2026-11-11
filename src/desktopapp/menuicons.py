"""Replace existing C2 menu records offline; no AP/CP routes or new image IDs."""
import struct
import sys
from .paths import ROOT


def vertical_modules():
    sys.path.insert(0,str(ROOT/'src/vertical'))
    from verticaltool import imagebank,portraitlines
    return imagebank,portraitlines


def decode(encoded,decoded_bytes=5600):
    """Decode the reviewed 70x35/stride80 and 58x30/stride64 F0 layouts."""
    lengths=tuple(range(3,17))+(32,64)
    if type(decoded_bytes)is not int or decoded_bytes not in (3840,5600):raise ValueError('Icon decoded layout differs')
    if not isinstance(encoded,bytes) or not 0<len(encoded)<=decoded_bytes*2:raise ValueError('Menu image compressed size differs')
    output=bytearray();at=0
    for start in range(0,decoded_bytes,4096):
        count=min(4096,decoded_bytes-start)
        if at>=len(encoded) or encoded[at]!=0xf0:raise ValueError('Menu image F0 header differs')
        at+=1;page=bytearray();done=False
        while not done:
            if at>=len(encoded):raise ValueError('Truncated menu image flags')
            flags=encoded[at];at+=1
            for bit in range(8):
                if flags>>bit&1:
                    if at+2>len(encoded):raise ValueError('Truncated menu image token')
                    a,b=encoded[at:at+2];at+=2
                    if not (a or b):done=True;break
                    distance=((a&15)<<8)|b;size=lengths[a>>4]
                    if not 0<distance<=len(page) or len(page)+size>count:raise ValueError('Menu image reference exceeds page')
                    for _ in range(size):page.append(page[-distance])
                else:
                    if at>=len(encoded) or len(page)>=count:raise ValueError('Menu image literal exceeds page')
                    page.append(encoded[at]);at+=1
        if len(page)!=count:raise ValueError('Menu image decoded size differs')
        output.extend(page)
    if at!=len(encoded):raise ValueError('Menu image has trailing bytes')
    return bytes(output)


def paint(original,icon,selected,*,compact=False):
    from PIL import Image,ImageFilter
    from looktool import iconfile
    pixels=iconfile.mask(icon);mask=Image.frombytes('L',iconfile.SIZE,pixels)
    if compact:mask=mask.resize((22,16),Image.Resampling.LANCZOS)
    pixels=mask.tobytes();outline=mask.filter(ImageFilter.MaxFilter(3)).tobytes()
    result=bytearray(original)
    width,height=mask.size;stride=64 if compact else 80;ox,oy=(22,8) if compact else (27,10)
    palette=((10,5,1) if selected else (10,10,10)) if compact else ((13,6,3) if selected else (15,15,15))
    # This includes the original ST antialiasing rows y=10 and y=28.
    for y in range(height):
        for x in range(width):
            i=y*width+x;alpha=(outline[i]+8)//17;white=(pixels[i]+8)//17
            r,g,b=((white*c+7)//15 for c in palette)
            word=(r<<12)|(g<<8)|(b<<4)|max(alpha,white)
            struct.pack_into('<H',result,((y+oy)*stride+x+ox)*2,word)
    return bytes(result)


def replace(source,icons,*,group=0,all_views=False):
    """Return one bank plus a source-bound byte plan, keeping old payloads."""
    imagebank,codec=vertical_modules();before=imagebank.inspect(source,group)
    if not icons or any(type(s) is not int or s not in range(1,7) for s in icons):raise ValueError('Select C2 menu slots 1..6')
    target=bytearray(source);windows=[];chosen={}
    for slot,icon in sorted(icons.items()):
        families=[]
        if group==0:
            families=[(False,0x6c5+slot-1,False),(True,0x8ef+13*(slot-1),False)]
            if all_views:families.append((True,0x181a+13*(slot-1),True))
        elif group==1 and all_views:families=[(False,0x13a3+slot-1,True)]
        else:raise ValueError('Unsupported Creative Look image bank')
        for selected,index,compact in families:
            row=before['records'].get(index)
            shape=(58,30) if compact else (70,35);decoded_bytes=3840 if compact else 5600
            if not row or (row['width'],row['height'],row['flags'],row['field'])!=(*shape,0xc0000000,12):
                raise ValueError('C2 menu image record differs at '+hex(index))
            old=source[row['start']:row['start']+row['size']]
            raw=paint(decode(old,decoded_bytes),icon,selected,compact=compact);payload=codec.compress(raw)
            if decode(payload,decoded_bytes)!=raw:raise ValueError('Generated menu image readback differs')
            chosen[index]=(payload,decoded_bytes)
            if decode(old,decoded_bytes)==raw:continue
            target.extend(bytes((-len(target))%4));at=len(target);target.extend(payload)
            field=row['at']+row['field'];new=struct.pack('<II',len(payload),at-row['at']-4)
            windows.append(dict(offset=field,before_hex=source[field:field+8].hex(),after_hex=new.hex(),index=index,slot=slot,selected=selected))
            target[field:field+8]=new
    target.extend(bytes((-len(target))%4));target=bytes(target);after=imagebank.inspect(target,group)
    if (before['count'],before['unused'],set(before['records']))!=(after['count'],after['unused'],set(after['records'])):
        raise ValueError('Menu image registration changed')
    for index,row in before['records'].items():
        now=after['records'][index];payload=target[now['start']:now['start']+now['size']]
        if source[row['start']:row['start']+row['size']]!=target[row['start']:row['start']+row['size']]:raise ValueError('Old image payload overwritten')
        if index in chosen:
            expected,n=chosen[index]
            if decode(payload,n)!=decode(expected,n):raise ValueError('Menu payload differs')
        elif now!=row or payload!=source[row['start']:row['start']+row['size']]:raise ValueError('Unselected menu record changed')
    cursor=0
    for window in sorted(windows,key=lambda w:w['offset']):
        at=window['offset']
        if target[cursor:at]!=source[cursor:at]:raise ValueError('Unowned menu bytes changed')
        cursor=at+8
    if target[cursor:len(source)]!=source[cursor:]:raise ValueError('Unowned menu tail changed')
    plan=dict(schema='a7c2-existing-menu-icons/1',source_bytes=len(source),target_bytes=len(target),windows=windows,
        append_hex=target[len(source):].hex(),slots=sorted(icons),group=group,all_views=all_views,
        registered_ids_preserved=True,old_payloads_preserved=True,camera_io=False)
    return target,plan
