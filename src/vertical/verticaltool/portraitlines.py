"""Render corrected portrait line artwork without touching a camera."""
import json
from pathlib import Path
import struct

ASSET=Path(__file__).resolve().parents[1]/'assets/portrait-lines-v2.json'


def specs():
    return json.loads(ASSET.read_text(encoding='utf-8'))['assets']


def raster(row):
    width,height=row['portrait']
    stride=(width+15)&~15
    pixels=bytearray(stride*height*2)
    for x,y,w,h,color in row['rectangles']:
        if not (0<=x<x+w<=width and 0<=y<y+h<=height and 0<=color<=65535):
            raise ValueError('Portrait line rectangle outside canvas')
        fill=struct.pack('<H',color)*w
        for line in range(y,y+h):
            start=(line*stride+x)*2
            pixels[start:start+len(fill)]=fill
    return bytes(pixels)


def compress(raw):
    """Use 4096-byte pages understood by the native image decoder."""
    lengths=list(range(3,17))+[32,64]
    output=bytearray()
    for base in range(0,len(raw),4096):
        data=raw[base:base+4096]
        history={};tokens=[];at=0
        while at<len(data):
            key=data[at:at+3]
            prior=history.get(key)
            size=0
            if len(key)==3 and prior is not None and at-prior<=4095:
                limit=min(64,len(data)-at)
                matched=0
                while matched<limit and data[prior+matched]==data[at+matched]:matched+=1
                for candidate in lengths:
                    if candidate<=matched:size=candidate
            if size:
                distance=at-prior
                tokens.append((1,bytes([(lengths.index(size)<<4)|(distance>>8),distance&255])))
            else:
                size=1
                tokens.append((0,data[at:at+1]))
            for index in range(at,at+size):history[data[index:index+3]]=index
            at+=size
        tokens.append((1,b'\0\0'))
        block=bytearray(b'\xf0')
        for start in range(0,len(tokens),8):
            group=tokens[start:start+8]
            block.append(sum(flag<<bit for bit,(flag,_) in enumerate(group)))
            for _,payload in group:block.extend(payload)
        output.extend(block)
    return bytes(output)
