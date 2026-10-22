"""Numerical Bayer charts for a real DCP renderer, without a camera or photos.

Input RGB is black-subtracted linear camera RGB, before white balance. The
supplied DCP is embedded unchanged. These files are generated test inputs,
not camera captures; they must not be presented as physical validation.
"""
from pathlib import Path
import math
import struct
import numpy as np
from .references import tiff_tags


def profile_records(path):
    order, records = tiff_tags(Path(path).read_bytes())
    model = records.get(50708, (0, 0, b''))[2].rstrip(b'\0').decode('utf-8')
    if model != 'Sony ILCE-7CM2':
        raise ValueError('This measured compiler needs a Sony ILCE-7CM2 DCP')
    if 50941 in records and struct.unpack(order+'I', records[50941][2])[0] == 2:
        raise ValueError('DCP embedding policy does not permit a virtual reference DNG')
    return order, records


def xmp(name, raw_name):
    from xml.sax.saxutils import quoteattr
    settings = dict(Version='18.5.1', ProcessVersion='15.4', CameraProfile=name,
        RawFileName=raw_name, WhiteBalance='As Shot', Exposure2012='0', Contrast2012='0',
        Highlights2012='0', Shadows2012='0', Whites2012='0', Blacks2012='0', Texture='0',
        Clarity2012='0', Dehaze='0', Vibrance='0', Saturation='0', Sharpness='0',
        LuminanceSmoothing='0', ColorNoiseReduction='0', LensProfileEnable='0',
        ToneCurveName2012='Linear', HasSettings='True', AlreadyApplied='False',
        ConvertToGrayscale='False', HasCrop='False', CropTop='0', CropLeft='0',
        CropBottom='1', CropRight='1')
    attributes = ' '.join('crs:'+key+'='+quoteattr(value) for key, value in settings.items())
    curves = ''.join('<crs:'+key+'><rdf:Seq><rdf:li>0, 0</rdf:li><rdf:li>255, 255</rdf:li></rdf:Seq></crs:'+key+'>'
        for key in ('ToneCurvePV2012','ToneCurvePV2012Red','ToneCurvePV2012Green','ToneCurvePV2012Blue'))
    return ('<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"><rdf:RDF><rdf:Description rdf:about="" '+
        attributes+'>'+curves+'</rdf:Description></rdf:RDF></x:xmpmeta>').encode('utf-8')


def write(path, dcp, rgb, *, wb=(2426., 1024., 1657.), black=512, white=16383,
          columns=32, cell=48):
    import tifffile
    path=Path(path);rgb=np.asarray(rgb, dtype=float)
    if rgb.ndim!=2 or rgb.shape[1]!=3 or not np.isfinite(rgb).all() or np.any((rgb<0)|(rgb>1)):
        raise ValueError('Finite Nx3 pre-WB camera-linear RGB in 0..1 required')
    if path.exists():raise ValueError('Choose a new virtual DNG path')
    if cell<16 or cell%2:raise ValueError('Even virtual chart cells of at least16 pixels required')
    order, records=profile_records(dcp)
    name=records[50936][2].rstrip(b'\0').decode('utf-8')
    rows=math.ceil(len(rgb)/columns);height, width=rows*cell, columns*cell
    padded=np.zeros((rows*columns, 3));padded[:len(rgb)]=rgb
    pixels=np.rint(black+padded*(white-black)).astype(np.uint16).reshape(rows, columns, 3)
    mosaic=np.empty((height,width),dtype=np.uint16)
    for y,x,ch in ((0,0,0),(0,1,1),(1,0,1),(1,1,2)):
        mosaic[y::2,x::2]=np.repeat(np.repeat(pixels[:,:,ch],cell//2,axis=0),cell//2,axis=1)
    types={1:('B',1),2:(None,1),3:('H',2),4:('I',4),5:('I',8),7:('B',1),
           9:('i',4),10:('i',8),11:('f',4),12:('d',8)}
    extra=[]
    for code,(typ,count,payload) in records.items():
        if typ==2:value=payload
        else:value=struct.unpack(order+types[typ][0]*(count*(2 if typ in (5,10) else 1)),payload)
        extra.append((code,typ,count,value,False))
    def tag(code,typ,count,value):extra.append((code,typ,count,value,False))
    neutral=tuple(x for gain in wb for x in (round(wb[1]/gain*1000000),1000000))
    for item in ((254,4,1,(0,)),(271,2,0,'SONY'),(272,2,0,'ILCE-7CM2'),(274,3,1,(1,)),
        (33421,3,2,(2,2)),(33422,1,4,(0,1,1,2)),(50706,1,4,(1,4,0,0)),
        (50707,1,4,(1,4,0,0)),(50710,1,3,(0,1,2)),(50711,3,1,(1,)),
        (50713,3,2,(2,2)),(50714,3,4,(black,)*4),(50717,4,1,(white,)),
        (50718,5,2,(1,1,1,1)),(50719,4,2,(0,0)),(50720,4,2,(width,height)),
        (50728,5,3,neutral),(50829,4,4,(0,0,height,width)),
        (50934,2,0,name.encode('utf-8'))):tag(*item)
    metadata=xmp(name,path.name);tag(700,1,len(metadata),metadata)
    path.parent.mkdir(parents=True,exist_ok=True)
    # Opening exclusively also prevents accidental replacement of a source file.
    with path.open('xb') as stream:
        tifffile.imwrite(stream,mosaic,photometric=32803,byteorder='<',metadata=None,
                         description=None,extratags=extra,software='Generated numerical A7C2 DCP reference')
    centers=np.array([(i%columns*cell+cell/2,i//columns*cell+cell/2) for i in range(len(rgb))])
    return dict(profile=name, shape=[height,width], centers=centers.tolist(), cell=cell,
                camera_io=False, synthetic=True, samples=len(rgb), raw_quantization_step=1/(white-black))


def sample(path, chart):
    from PIL import Image
    with Image.open(path) as image:
        if image.size != tuple(chart['shape'][::-1]):
            raise ValueError('Adobe export resized/cropped the numerical chart')
        pixels=np.asarray(image.convert('RGB'),dtype=float)/255
    values=[]
    radius=max(4,chart['cell']//6)
    for x,y in chart['centers']:
        x,y=int(x),int(y)
        values.append(np.median(pixels[y-radius:y+radius,x-radius:x+radius],axis=(0,1)))
    return np.asarray(values)


def export_settings(path):
    """Read the standard XMP packet to check what Adobe actually rendered."""
    import xml.etree.ElementTree as ET
    header=b'http://ns.adobe.com/xap/1.0/\0'
    with Path(path).open('rb') as stream:
        if stream.read(2)!=b'\xff\xd8':raise ValueError('Expected an Adobe JPEG export')
        while True:
            marker=stream.read(2)
            if len(marker)!=2 or marker[0]!=255 or marker[1] in (0xda,0xd9):break
            length=struct.unpack('>H',stream.read(2))[0]
            payload=stream.read(length-2)
            if marker==b'\xff\xe1' and payload.startswith(header):
                root=ET.fromstring(payload[len(header):])
                ns='{http://ns.adobe.com/camera-raw-settings/1.0/}'
                result={}
                for node in root.iter():
                    for key,value in node.attrib.items():
                        if key.startswith(ns):result[key[len(ns):]]=value
                    if node.tag.startswith(ns) and node.text:result[node.tag[len(ns):]]=node.text
                if 'Temperature' in result and 'ColorTemperature' not in result:
                    result['ColorTemperature']=result['Temperature']
                return result
    raise ValueError('Adobe export has no standard Camera Raw XMP packet')
