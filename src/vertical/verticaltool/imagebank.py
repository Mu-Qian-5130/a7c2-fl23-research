"""Add line images to unused UXC indices without duplicating a bank on camera.

This module only plans bytes offline. It does not open a device or change AP
references. Existing image data remains available through its original ID.
"""
import struct

MAGIC=b'uxd\x07\0\0\0\0'


def inspect(source,group):
    if source[:8]!=MAGIC:raise ValueError('Unsupported image-bank header')
    version,actual,descriptor=struct.unpack_from('<HHI',source,8)
    count=descriptor&8191
    if version!=8 or actual!=group or descriptor!=count|(((count+1)&~1)<<12):
        raise ValueError('Unsupported image-bank layout')
    base=16+((descriptor>>11)&0x7ffc)
    records={};unused=[]
    for index in range(count):
        pointer=struct.unpack_from('<H',source,16+2*index)[0]
        if pointer==65535:
            unused.append(index);continue
        at=base+4*pointer
        rid,flags,width,height=struct.unpack_from('<IIHH',source,at)
        if rid!=0x1a000000+group*8192+index:raise ValueError('Image index differs from record ID')
        field=32 if flags&0x08000000 else 12
        size,offset=struct.unpack_from('<II',source,at+field)
        start=at+4+offset
        if not base<=at<at+field+8<=start<=start+size<=len(source):
            raise ValueError('Image record or payload outside bank')
        records[index]=dict(at=at,field=field,width=width,height=height,
                            flags=flags,start=start,size=size)
    return dict(count=count,base=base,records=records,unused=unused)


def add(source,group,images):
    """Return a small append and edited ranges, plus the host-side target.

    Each image supplies index/width/height/payload. To keep the 16-bit metadata
    pointers, move one existing encoded payload to EOF and use its former
    location for the new 20-byte metadata records. No original image is lost.
    """
    if not images:raise ValueError('Select at least one image')
    parsed=inspect(source,group);records=parsed['records'];base=parsed['base']
    indices=[image['index'] for image in images]
    if len(set(indices))!=len(indices) or not set(indices)<=set(parsed['unused']):
        raise ValueError('New images must use distinct unused indices')
    options=[bytes.fromhex(image.get('options_hex','')) for image in images]
    if any(len(option) not in (0,20) for option in options):raise ValueError('Unsupported image option layout')
    record_sizes=[20+len(option) for option in options]
    starts=[];needed=0
    for size in record_sizes:starts.append(needed);needed+=size
    metadata_end=max(row['at']+row['field']+8 for row in records.values())
    donors=[]
    ordered=sorted(records.items(),key=lambda item:item[1]['start'])
    for index,row in ordered:
        start,end=row['start'],row['start']+row['size']
        if row['size']<needed or start<metadata_end or (start-base)%4:continue
        if (start+starts[-1]-base)//4>=65535:continue
        if any(other!=index and r['start']<end and start<r['start']+r['size']
               for other,r in records.items()):continue
        donors.append((row['size'],index,row))
    if not donors:raise ValueError('No independent payload can hold new metadata')
    _,donor_id,donor=min(donors,key=lambda item:item[:2])
    target=bytearray(source);windows=[]

    def append(payload):
        target.extend(bytes((-len(target))%4))
        at=len(target);target.extend(payload);return at

    def change(at,value,label):
        before=source[at:at+len(value)]
        target[at:at+len(value)]=value
        windows.append(dict(offset=at,before_hex=before.hex(),after_hex=value.hex(),label=label))

    moved=append(source[donor['start']:donor['start']+donor['size']])
    change(donor['at']+donor['field']+4,struct.pack('<I',moved-donor['at']-4),'relocate_original_payload')
    metadata=bytearray()
    for number,image in enumerate(images):
        at=donor['start']+starts[number]
        payload_at=append(image['payload'])
        metadata.extend(struct.pack('<IIHH',0x1a000000+group*8192+image['index'],
            0xc8000000 if options[number] else 0xc0000000,image['width'],image['height']))
        metadata.extend(options[number])
        metadata.extend(struct.pack('<II',len(image['payload']),payload_at-at-4))
    change(donor['start'],bytes(metadata),'new_image_metadata')
    for number,index in enumerate(indices):
        pointer=(donor['start']+starts[number]-base)//4
        change(16+2*index,struct.pack('<H',pointer),'publish_new_image_index')
    target.extend(bytes((-len(target))%4))
    # Every pre-existing record still resolves to its exact encoded image.
    after=inspect(target,group)
    for index,row in records.items():
        current=after['records'][index]
        if source[row['start']:row['start']+row['size']]!=target[current['start']:current['start']+current['size']]:
            raise ValueError('An original image changed during planning')
    plan=dict(schema='a7c2-image-bank-additions/1',group=group,source_bytes=len(source),
              target_bytes=len(target),relocated_index=donor_id,new_indices=indices,
              append_hex=bytes(target[len(source):]).hex(),windows=windows,camera_io=False)
    return bytes(target),plan


def apply(source,plan,*,reverse=False):
    """Exercise the byte plan offline; device execution is not implemented."""
    original_size,target_size=plan['source_bytes'],plan['target_bytes']
    if len(source)!=(target_size if reverse else original_size):raise ValueError('Image-bank size differs')
    old_key,new_key=('after_hex','before_hex') if reverse else ('before_hex','after_hex')
    for row in plan['windows']:
        before=bytes.fromhex(row[old_key]);at=row['offset']
        if source[at:at+len(before)]!=before:raise ValueError('Image-bank edit bytes differ')
    target=bytearray(source)
    if not reverse:target.extend(bytes.fromhex(plan['append_hex']))
    for row in plan['windows']:
        value=bytes.fromhex(row[new_key]);at=row['offset'];target[at:at+len(value)]=value
    return bytes(target[:original_size] if reverse else target)
