"""Camera ST / sRGB CUBE to a companion Sony ILCE-7CM2 DCP.

Reuse the project's dcp_author / author_phocus_dcp tone-and-look construction.
Camera calibration is copied, while the new look is an approximation of the
declared reference. This module neither fits camera coefficients nor uses USB.
"""
from pathlib import Path
import struct

import numpy as np
from scipy.interpolate import CubicSpline

from .color import rgb_to_hsv, hsv_to_rgb, srgb_encode, srgb_decode, prophoto_to_srgb
from .references import Cube, DcpLook, tiff_tags

BASE = Path(__file__).resolve().parents[1] / 'assets/cube-dcp-base.dcp'
CALIBRATION_TAGS = (50708,50721,50722,50723,50724,50727,50778,50779,50932,
                    50937,50938,50939,50964,50965,51107,51109)


def reference_attribution(cube):
    credits=[]
    for line in Path(cube).read_text(encoding='utf-8-sig').splitlines():
        text=line.lstrip()
        if text.startswith('#')and any(word in text.casefold()for word in ('copyright','author','license','roger wang','©')):
            credits.append(text.lstrip('#').strip())
    return '; '.join(credits)


def encode(tags, endian):
    sizes={1:1,2:1,3:2,4:4,5:8,7:1,9:4,10:8,11:4,12:8}
    count=len(tags)
    header=bytearray((b'II'if endian=='<'else b'MM')+struct.pack(endian+'HIH',0x4352,8,count))
    start=14+12*count;tail=bytearray()
    for tag,(kind,n,data)in sorted(tags.items()):
        if kind not in sizes or n*sizes[kind]!=len(data):raise ValueError('Invalid DCP field length')
        header.extend(struct.pack(endian+'HHI',tag,kind,n))
        if len(data)<=4:header.extend(data.ljust(4,b'\0'))
        else:
            tail.extend(bytes((-len(tail))%4))
            header.extend(struct.pack(endian+'I',start+len(tail)));tail.extend(data)
    return bytes(header+bytes(4)+tail)


def _tone(reference):
    for count in (65,129,257):
        x=srgb_decode(np.linspace(0,1,count))
        target=reference(np.repeat(x[:,None],3,axis=1))
        linear=srgb_decode(target)@np.linalg.inv(prophoto_to_srgb()).T
        y=np.maximum.accumulate(np.clip(linear.mean(1),0,1))
        # Classic DCP endpoints and neutral behavior constrain lifted/tinted
        # blacks. Keep these limits visible in the representation report.
        y-=y[0]*np.exp(-x/.003);y+=(1-y[-1])*x**16;y[0],y[-1]=0,1
        curve=np.c_[x,y].astype('f4').astype(float)
        spline=CubicSpline(curve[:,0],curve[:,1],bc_type='natural')
        values=spline(np.linspace(0,1,65537))
        if values.min()>=-1e-7 and values.max()<=1+1e-7 and np.diff(values).min()>=-1e-7:return curve,spline
    raise ValueError('Reference needs a different DCP tone representation')


def _inverse_tone(rgb,spline):
    x=np.linspace(0,1,262145);y=np.maximum.accumulate(np.clip(spline(x),0,1))
    y,at=np.unique(y,return_index=True);x=x[at]
    low,high=rgb.min(1),rgb.max(1)
    weight=np.divide(rgb-low[:,None],(high-low)[:,None],out=np.zeros_like(rgb),where=(high-low)[:,None]>1e-14)
    before_low=np.interp(low,y,x);before_high=np.interp(high,y,x)
    return before_low[:,None]+weight*(before_high-before_low)[:,None]


def cube_profile(cube,name,destination,*,bridge=None,base=BASE,dimensions=(90,128,128)):
    """Create one new DCP; preserve all selected original calibration payloads."""
    destination=Path(destination)
    if destination.exists():raise FileExistsError(destination)
    source=Path(base).read_bytes();endian,original=tiff_tags(source)
    if original.get(50708,(None,None,b''))[2].rstrip(b'\0')!=b'Sony ILCE-7CM2':
        raise ValueError('Sony ILCE-7CM2 Camera ST calibration is required')
    parent=DcpLook(base);lut=Cube(cube);input_bridge=Cube(bridge)if bridge else None
    def reference(rgb):
        entering=parent.render(rgb)
        if input_bridge is not None:entering=input_bridge.sample(entering)
        return np.clip(lut.sample(entering),0,1)
    curve,spline=_tone(reference)
    nh,ns,nv=dimensions
    if not 1<=nh<=360 or not 2<=ns<=256 or not 2<=nv<=256:raise ValueError('Unsupported DCP table dimensions')
    table=np.empty((nv,nh,ns,3),dtype=np.float32)
    transform=np.linalg.inv(prophoto_to_srgb()).T
    # Bound temporary arrays rather than holding every intermediate of a dense
    # DCP table. The table order and interpolation remain the original ones.
    for first in range(0,nv,8):
        stop=min(first+8,nv)
        v,h,s=np.meshgrid(np.linspace(0,1,nv)[first:stop],np.arange(nh)*360/nh,np.linspace(0,1,ns),indexing='ij')
        hsv=np.c_[h.ravel(),s.ravel(),srgb_decode(v.ravel())]
        target=reference(hsv_to_rgb(hsv))
        linear=np.clip(srgb_decode(target)@transform,0,1)
        after=rgb_to_hsv(_inverse_tone(linear,spline))
        hue=(after[:,0]-hsv[:,0]+180)%360-180
        saturation=np.divide(after[:,1],hsv[:,1],out=np.ones(len(hsv)),where=hsv[:,1]>0)
        value=np.divide(srgb_encode(after[:,2]),v.ravel(),out=np.ones(len(hsv)),where=v.ravel()>0)
        table[first:stop]=np.c_[hue,saturation,value].reshape(stop-first,nh,ns,3)
    table[0,:,:,2]=table[1,:,:,2];table[:,:,0]=[0,1,1]
    if not np.isfinite(table).all()or np.any(table[...,1:]<0):raise ValueError('Nonfinite DCP look table')
    tags={k:v for k,v in original.items()if k in CALIBRATION_TAGS}
    attribution=reference_attribution(cube)
    copyright_text=(attribution+'; 'if attribution else'')+'Owner-provided CUBE look; Sony ILCE-7CM2 Camera ST calibration: Adobe Inc.'
    for tag,text in ((50936,name),(50942,copyright_text)):
        data=text.encode('utf-8')+b'\0';tags[tag]=(2,len(data),data)
    tags[50941]=(4,1,struct.pack(endian+'I',0))
    tags[50981]=(4,3,struct.pack(endian+'3I',nh,ns,nv))
    tags[50982]=(11,table.size,table.astype(endian+'f4').tobytes())
    tags[51108]=(4,1,struct.pack(endian+'I',1))
    tags[51110]=(4,1,struct.pack(endian+'I',1))
    tags[50940]=(11,curve.size,curve.astype(endian+'f4').tobytes())
    raw=encode(tags,endian);actual_endian,actual=tiff_tags(raw)
    if actual_endian!=endian or actual!=tags:raise ValueError('DCP field encoding differs')
    for tag in CALIBRATION_TAGS:
        if tag in original and actual.get(tag)!=original[tag]:raise ValueError('Camera calibration changed')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.open('xb')as output:output.write(raw)
    authored=DcpLook(destination)
    gray=np.repeat(np.linspace(0,1,257)[:,None],3,axis=1)
    probes=np.r_[np.random.default_rng(20261110).uniform(0,1,(4096,3)),gray]
    error=np.abs(authored.render(probes)-reference(probes))*255
    return dict(profile=name,dimensions=[nh,ns,nv],bytes=len(raw),camera_calibration_preserved=True,reference_attribution=attribution,
        representation_prediction=dict(points=len(error),rmse=float(np.sqrt(np.mean(error**2))),
            p95_channel=float(np.percentile(error,95)),p99_channel=float(np.percentile(error,99)),
            maximum_channel=float(error.max()),severe_gt30_points=int((error.max(1)>30).sum())),
        scope='Local DCP look/tone representation; not an Adobe RAW or camera acceptance',
        input_space='Sony Camera ST / sRGB',output_space='sRGB',input_bridge_used=bool(bridge),
        lifted_or_tinted_neutral_limits=True,actual_Adobe_verified=False,camera_io=False)


def publish(source,destination):
    """Publish/reuse the exact paired reference without replacing other files."""
    source,destination=Path(source),Path(destination);raw=source.read_bytes()
    if destination.exists():
        if destination.read_bytes()!=raw:raise FileExistsError('Choose another companion DCP path: '+str(destination))
        return destination
    destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.open('xb')as output:output.write(raw)
    return destination
