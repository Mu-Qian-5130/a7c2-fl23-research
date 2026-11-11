"""Portable menu artwork; no Sony frame, resource ID, slot or file offset."""
import base64
import io
from pathlib import Path

SCHEMA='a7c2-menu-icon/1'
SIZE=(26,19)
MAX_PNG=16384
MAX_TEXT=4


def mask(value):
    from PIL import Image
    if not isinstance(value,dict) or value.get('schema')!=SCHEMA or not {'schema','png_base64'}<=set(value)<={'schema','png_base64','label'}:
        raise ValueError('Unsupported menu icon format')
    label=value.get('label','')
    if not isinstance(label,str) or len(label)>32 or any(ord(c)<32 for c in label):raise ValueError('Invalid menu icon label')
    encoded=value.get('png_base64')
    if not isinstance(encoded,str) or len(encoded)>4*((MAX_PNG+2)//3):raise ValueError('Menu icon PNG is too large')
    try:
        raw=base64.b64decode(encoded,validate=True)
        if not 0<len(raw)<=MAX_PNG:raise ValueError('Menu icon PNG size differs')
        with Image.open(io.BytesIO(raw)) as image:
            if image.format!='PNG' or image.size!=SIZE or getattr(image,'n_frames',1)!=1 or image.mode!='L':
                raise ValueError('Menu icon must be a single 26 x 19 grayscale PNG mask')
            image.load();pixels=image.tobytes()
    except (OSError,ValueError) as exc:raise ValueError('Invalid embedded menu icon PNG') from exc
    if not any(pixels):raise ValueError('Menu icon is empty')
    return pixels


def from_mask(pixels,*,label=''):
    from PIL import Image
    if not isinstance(pixels,bytes) or len(pixels)!=SIZE[0]*SIZE[1]:raise ValueError('Menu icon mask size differs')
    stream=io.BytesIO();Image.frombytes('L',SIZE,pixels).save(stream,format='PNG')
    value=dict(schema=SCHEMA,png_base64=base64.b64encode(stream.getvalue()).decode('ascii'))
    if label:value['label']=label
    mask(value)
    return value


def from_png(path):
    """Import a glyph mask. Artwork is resized by the author, never silently."""
    from PIL import Image
    path=Path(path)
    if not 0<path.stat().st_size<=MAX_PNG:raise ValueError('图标 PNG 不能超过 16 KiB')
    with Image.open(path) as image:
        if image.format!='PNG' or image.size!=SIZE or getattr(image,'n_frames',1)!=1:
            raise ValueError('请选择 26×19 像素的透明或黑白 PNG；请先明确调整尺寸')
        alpha=image.getchannel('A') if 'A' in image.getbands() else None
        pixels=(alpha if alpha is not None and alpha.getextrema()!=(255,255) else image.convert('L')).tobytes()
    return from_mask(pixels,label=path.stem[:32])


def from_text(text,*,font=None):
    from PIL import Image,ImageDraw,ImageFont
    if not isinstance(text,str) or not 1<=len(text)<=MAX_TEXT or any(not (c.isalnum() or c in '+-') for c in text):
        raise ValueError('图标缩写使用 1–4 个字母、数字或汉字')
    candidates=[font] if font else ['C:/Windows/Fonts/arialnb.ttf','C:/Windows/Fonts/arialn.ttf','C:/Windows/Fonts/msyh.ttc',
        '/System/Library/Fonts/Supplemental/Arial Narrow.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    chosen=None
    for path in candidates:
        if not path or not Path(path).is_file():continue
        for size in range(96,7,-1):
            face=ImageFont.truetype(str(path),size);box=face.getbbox(text)
            if box[3]-box[1]<=60:
                missing=face.getmask(chr(0x10ffff));signature=(missing.size,bytes(missing))
                if any((face.getmask(c).size,bytes(face.getmask(c)))==signature for c in text):break
                chosen=(face,box);break
        if chosen:break
    if chosen is None:raise ValueError('本机字体不能绘制此缩写；可改用 PNG 图标')
    face,box=chosen;canvas=Image.new('L',(104,76))
    glyph=Image.new('L',(box[2]-box[0],box[3]-box[1]))
    ImageDraw.Draw(glyph).text((-box[0],-box[1]),text,font=face,fill=255)
    if glyph.width>96:glyph=glyph.resize((96,glyph.height),Image.Resampling.LANCZOS)
    canvas.paste(glyph,((104-glyph.width)//2,(76-glyph.height)//2))
    return from_mask(canvas.resize(SIZE,Image.Resampling.LANCZOS).tobytes(),label=text)


def reject_device_import(document):
    if document.get('menu_icon') is not None:
        raise ValueError('此调用路径尚未支持菜单图标（USB 直接导入未接入）；请使用已更新的机内图标 API 或在生成固件时内嵌，未开始连接相机')


def save_copy(source,destination,icon,*,name=None):
    import json
    from . import lookfile
    document=lookfile.read(source)
    if name is not None:
        if not isinstance(name,str) or not 1<=len(name.encode('utf-8'))<=63 or any(ord(c)<32 for c in name):
            raise ValueError('外观名称使用 1–63 字节的完整名称')
        document['name']=name
    if icon is None:document.pop('menu_icon',None)
    else:document['menu_icon']=icon
    lookfile.validate(document)
    with Path(destination).open('x',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps(document,ensure_ascii=False,allow_nan=False,indent=2)+'\n')
    return document
