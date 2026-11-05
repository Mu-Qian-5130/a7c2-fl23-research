"""Replace existing C2 menu records offline; no AP/CP routes or new image IDs."""
import struct
import sys
from .paths import ROOT


def vertical_modules():
    sys.path.insert(0,str(ROOT/'src/vertical'))
    from verticaltool import imagebank,portraitlines
    return imagebank,portraitlines


def decode(encoded):
    """Decode exactly two native F0 pages for 70x35 pixels, stride 80."""
    lengths=tuple(range(3,17))+(32,64)
    if not isinstance(encoded,bytes) or not 0<len(encoded)<=11200:raise ValueError('Menu image compressed size differs')
    output=bytearray();at=0
    for count in (4096,1504):
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


def paint(original,icon,selected):
    from PIL import Image,ImageFilter
    from looktool import iconfile
    pixels=iconfile.mask(icon);outline=Image.frombytes('L',iconfile.SIZE,pixels).filter(ImageFilter.MaxFilter(3)).tobytes()
    result=bytearray(original)
    palette=(13,6,3) if selected else (15,15,15)
    # This includes the original ST antialiasing rows y=10 and y=28.
    for y in range(19):
        for x in range(26):
            i=y*26+x;alpha=(outline[i]+8)//17;white=(pixels[i]+8)//17
            r,g,b=((white*c+7)//15 for c in palette)
            word=(r<<12)|(g<<8)|(b<<4)|max(alpha,white)
            struct.pack_into('<H',result,((y+10)*80+x+27)*2,word)
    return bytes(result)


def replace(source,icons):
    """Return one bank plus a source-bound byte plan, keeping old payloads."""
    imagebank,codec=vertical_modules();before=imagebank.inspect(source,0)
    if not icons or any(type(s) is not int or s not in range(1,7) for s in icons):raise ValueError('Select C2 menu slots 1..6')
    target=bytearray(source);windows=[];chosen={}
    for slot,icon in sorted(icons.items()):
        for selected,index in ((False,0x6c5+slot-1),(True,0x8ef+13*(slot-1))):
            row=before['records'].get(index)
            if not row or (row['width'],row['height'],row['flags'],row['field'])!=(70,35,0xc0000000,12):
                raise ValueError('C2 menu image record differs at '+hex(index))
            old=source[row['start']:row['start']+row['size']]
            raw=paint(decode(old),icon,selected);payload=codec.compress(raw)
            if decode(payload)!=raw:raise ValueError('Generated menu image readback differs')
            chosen[index]=payload
            if decode(old)==raw:continue
            target.extend(bytes((-len(target))%4));at=len(target);target.extend(payload)
            field=row['at']+row['field'];new=struct.pack('<II',len(payload),at-row['at']-4)
            windows.append(dict(offset=field,before_hex=source[field:field+8].hex(),after_hex=new.hex(),index=index,slot=slot,selected=selected))
            target[field:field+8]=new
    target.extend(bytes((-len(target))%4));target=bytes(target);after=imagebank.inspect(target,0)
    if (before['count'],before['unused'],set(before['records']))!=(after['count'],after['unused'],set(after['records'])):
        raise ValueError('Menu image registration changed')
    for index,row in before['records'].items():
        now=after['records'][index];payload=target[now['start']:now['start']+now['size']]
        if source[row['start']:row['start']+row['size']]!=target[row['start']:row['start']+row['size']]:raise ValueError('Old image payload overwritten')
        if index in chosen:
            if decode(payload)!=decode(chosen[index]):raise ValueError('Menu payload differs')
        elif now!=row or payload!=source[row['start']:row['start']+row['size']]:raise ValueError('Unselected menu record changed')
    cursor=0
    for window in sorted(windows,key=lambda w:w['offset']):
        at=window['offset']
        if target[cursor:at]!=source[cursor:at]:raise ValueError('Unowned menu bytes changed')
        cursor=at+8
    if target[cursor:len(source)]!=source[cursor:]:raise ValueError('Unowned menu tail changed')
    plan=dict(schema='a7c2-existing-menu-icons/1',source_bytes=len(source),target_bytes=len(target),windows=windows,
        append_hex=target[len(source):].hex(),slots=sorted(icons),registered_ids_preserved=True,old_payloads_preserved=True,camera_io=False)
    return target,plan
