"""Data-only image references in C2 2.01 portrait layout tables."""
import struct
from . import portraitgauge

# Original public image ID -> new index in the same existing bank.
IMAGES={0x02000f96:0x02001e9f,0x02000f97:0x02001e9e,
        0x020023d2:0x02003ebc,0x02002cac:0x02003eb3,
        0x02002291:0x02003ebe,
        0x02002397:0x02002797,0x02002398:0x02002798,0x020023ec:0x020027ec,
        0x0200228c:0x0200328c,0x0200228d:0x0200328d,
        0x0200228e:0x0200328e,0x0200228f:0x0200328f}
# Portrait canvas root, corresponding landscape root, image-field displacement,
# and original public ID. Roots explicitly describe 480x640 and 640x480.
PAIRS=(
    (0x3f4bff0,0x3f4d5e0,0x18c,0x02002291),
    (0x3f4bff0,0x3f4d5e0,0x1c0,0x02002291),
    (0x3fa5a98,0x3fa6a40,0x4cc,0x02000f96),
    (0x4023278,0x4023a68,0x1f4,0x02000f96),
    (0x3fa5a98,0x3fa6a40,0x158,0x02000f97),
    (0x4023278,0x4023a68,0x18c,0x02000f97),
    (0x40381e0,0x4039600,0x3c8,0x020023d2),
    (0x40381e0,0x4039600,0x12d0,0x020023d2),
    (0x3f47088,0x3f47810,0x18c,0x02002cac),
    (0x3f482f8,0x3f48b80,0x18c,0x02002cac),
    (0x3f497b8,0x3f4a078,0x18c,0x02002cac),
    (0x3f497b8,0x3f4a078,0x6d4,0x02002cac),
    (0x3f4ad60,0x3f4b480,0x18c,0x02002cac),
    (0x40381e0,0x4039600,0x32c,0x02002cac),
    (0x408dab0,0x408e1d0,0x18c,0x02002cac),
    (0x408ec10,0x408f500,0x124,0x02002cac),
    (0x40929f0,0x4092ea0,0x124,0x02002cac),
)


def canonical_windows(ap,*,pairs=PAIRS):
    windows=[]
    for portrait,landscape,delta,original in pairs:
        for root,size in ((portrait,0x028001e0),(landscape,0x01e00280)):
            if ap[root:root+24]!=struct.pack('<6I',0x82,0xb81,0x250e,0,0,size):
                raise ValueError('Portrait/landscape layout canvas differs at '+hex(root))
        at=portrait+delta;land_at=landscape+delta;new=IMAGES[original]
        old_bytes,new_bytes=struct.pack('<I',original),struct.pack('<I',new)
        current=ap[at:at+4]
        if len(current)!=4 or any(c not in (a,b) for c,a,b in zip(current,old_bytes,new_bytes)):
            raise ValueError('Portrait image reference differs at '+hex(at))
        if struct.unpack_from('<I',ap,land_at)[0]!=original:
            raise ValueError('Landscape image reference differs at '+hex(land_at))
        windows.append(dict(offset=at,before_hex=old_bytes.hex(),after_hex=new_bytes.hex(),label='portrait_image_reference'))
    if pairs is PAIRS:windows.extend(portraitgauge.windows(ap))
    return windows


def references(ap,enabled,*,pairs=PAIRS):
    target=bytearray(ap);windows=[]
    for row in canonical_windows(ap,pairs=pairs):
        at=row['offset'];value=bytes.fromhex(row['after_hex'] if enabled else row['before_hex'])
        if ap[at:at+len(value)]!=value:
            windows.append(dict(row,before_hex=ap[at:at+len(value)].hex(),after_hex=value.hex()))
            target[at:at+len(value)]=value
    return bytes(target),windows


def active(ap):
    if portraitgauge.active(ap):return True
    for p,_,delta,original in PAIRS:
        at=p+delta;current=ap[at:at+4];old=struct.pack('<I',original);new=struct.pack('<I',IMAGES[original])
        if len(current)==4 and current!=old and all(c in (a,b) for c,a,b in zip(current,old,new)):return True
    return False
