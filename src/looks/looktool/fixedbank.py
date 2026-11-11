"""Fixed look image: stable per-slot addresses, no runtime generation/ready."""
import struct
from .fixedlayout import DATA_START,DATA_BYTES,MAX_LOOK_SLOTS,ROOT_VA

GAMMA_OFFSET=0x20
DIRECTORY_OFFSET=0xA00
MODES_OFFSET=0xB40
BASIS_OFFSET=0xC00
BASIS_BYTES=1792
SLOTS_OFFSET=0x2000
SLOT_STRIDE=0x3100
RECORD_OFFSET=0x500
GRID_BYTES=1215
FIXED_RECORD=8976
NATIVE_ROWS=50
NATIVE_TABLE=0x1209480


def build(native,basis,entries,mask):
    count=len(entries)
    if len(native)!=1400 or len(basis)!=BASIS_BYTES or not 1<=count<=MAX_LOOK_SLOTS:
        raise ValueError('Fixed look image dimensions differ')
    if type(mask)is not int or not 0<=mask<1<<count:
        raise ValueError('Selected look mask exceeds the stored slots')
    total=SLOTS_OFFSET+count*SLOT_STRIDE
    if total>DATA_BYTES:raise ValueError('Fixed look image exceeds512KiB')
    out=bytearray(total)
    struct.pack_into('<4I',out,0,total,count,mask,SLOT_STRIDE)
    out[GAMMA_OFFSET:GAMMA_OFFSET+1400]=native
    out[BASIS_OFFSET:BASIS_OFFSET+BASIS_BYTES]=basis
    for index,(grid,record,kind)in enumerate(entries):
        if len(grid)!=GRID_BYTES or kind not in (0,1,2):raise ValueError('Fixed look entry differs')
        if len(record)!=FIXED_RECORD+4+(0,90,2200)[kind]:raise ValueError('Fixed look record length differs')
        start=SLOTS_OFFSET+index*SLOT_STRIDE;rec=start+RECORD_OFFSET
        if rec+len(record)>start+SLOT_STRIDE:raise ValueError('Fixed look record overlaps its neighbor')
        out[start:start+GRID_BYTES]=grid;out[rec:rec+len(record)]=record
        struct.pack_into('<4I',out,DIRECTORY_OFFSET+index*16,DATA_START+start,DATA_START+rec,len(record),kind)
        struct.pack_into('<2I',out,MODES_OFFSET+index*8,50+index*2,51+index*2)
        for column in range(14):
            struct.pack_into('<I',out,GAMMA_OFFSET+1400+index*56+column*4,
                             DATA_START+rec+912+column*576)
    result=bytes(out);parse(result);return result


def parse(raw):
    if len(raw)<SLOTS_OFFSET:raise ValueError('Fixed image is truncated')
    total,count,mask,stride=struct.unpack_from('<4I',raw)
    if stride!=SLOT_STRIDE or not 1<=count<=MAX_LOOK_SLOTS or mask>>count:
        raise ValueError('Fixed image slot layout differs')
    if total!=len(raw) or total!=SLOTS_OFFSET+count*SLOT_STRIDE or total>DATA_BYTES:
        raise ValueError('Fixed image extent differs')
    entries=[]
    for index in range(count):
        grid,record,size,kind=struct.unpack_from('<4I',raw,DIRECTORY_OFFSET+index*16)
        expected=SLOTS_OFFSET+index*SLOT_STRIDE
        if grid!=DATA_START+expected or record!=grid+RECORD_OFFSET or kind>2:
            raise ValueError('Fixed image entry address differs')
        if size!=FIXED_RECORD+4+(0,90,2200)[kind] or record-DATA_START+size>expected+SLOT_STRIDE:
            raise ValueError('Fixed image record extent differs')
        rec=raw[record-DATA_START:record-DATA_START+size]
        if struct.unpack_from('<I',rec,FIXED_RECORD)[0]!=(0,90,2200)[kind]:
            raise ValueError('Fixed image recipe length differs')
        g=raw[expected:expected+GRID_BYTES]
        if any(64<=v<192 for v in g):raise ValueError('Fixed image grid range differs')
        if struct.unpack_from('<2I',raw,MODES_OFFSET+index*8)!=(50+index*2,51+index*2):
            raise ValueError('Fixed mode pointer row differs')
        for column in range(14):
            if struct.unpack_from('<I',raw,GAMMA_OFFSET+1400+index*56+column*4)[0]!=record+912+column*576:
                raise ValueError('Fixed curve pointer differs')
        entries.append((g,rec,kind))
    return dict(count=count,mask=mask,bytes=total,capacity=DATA_BYTES,
                native=raw[GAMMA_OFFSET:GAMMA_OFFSET+1400],
                basis=raw[BASIS_OFFSET:BASIS_OFFSET+BASIS_BYTES],entries=entries)


def from_cp(cp,*,mask=None):
    """Relocate the original static records without an intermediate bank."""
    from . import six
    if len(cp)<0x11019f8 or struct.unpack_from('<2I',cp,0xa000)!=(0x33465041,1):
        raise ValueError('A compiled static full-record source is required')
    length=struct.unpack_from('<I',cp,0xa008)[0]
    if not 1920<=length<=0x16000:raise ValueError('Static record source extent differs')
    if mask is None:mask=struct.unpack_from('<I',cp,0xa00c)[0]
    entries=[]
    for index in range(6):
        at,size,_,kind=struct.unpack_from('<4I',cp,0xa020+index*16)
        if at<1920 or size<FIXED_RECORD+4 or size>FIXED_RECORD+2204 or at+size>length or kind>2:
            raise ValueError('Static record source exceeds its declared extent')
        grid=six.TABLE_FILE+32+index*GRID_BYTES
        entries.append((cp[grid:grid+GRID_BYTES],cp[0xa000+at:0xa000+at+size],kind))
    native_at=NATIVE_TABLE-0x108000
    return build(cp[native_at:native_at+1400],cp[0xa080:0xa780],entries,mask)


def from_documents(cp,basis,documents,*,mask):
    """Build the ordinary generator's fixed source without a dynamic bank."""
    from . import device_layout,lookfile,photofull
    grids=device_layout.tables(cp);entries=[]
    for index in range(6):
        doc=documents.get(index+1)
        grid=lookfile.writer_document(doc)if doc else grids[index]
        kind,record=photofull.entry(cp,basis,(doc.get('edit_native')or doc.get('native_photo'))if doc else None)
        entries.append((grid,record,kind))
    native_at=NATIVE_TABLE-0x108000
    return build(cp[native_at:native_at+1400],basis.pack(),entries,mask)


def replace(raw,replacements):
    old=parse(raw);entries=list(old['entries'])
    if any(type(slot)is not int or not 1<=slot<=old['count']for slot in replacements):
        raise ValueError('Selected fixed look slot is outside the image')
    for slot,entry in replacements.items():entries[slot-1]=entry
    return build(old['native'],old['basis'],entries,
                 old['mask']|sum(1<<(slot-1)for slot in replacements))


def update_documents(cp,raw,documents):
    from . import lookfile,photoformat,photofull
    parsed=parse(raw);basis=photoformat.PhotoBank.unpack(parsed['basis']);updates={}
    for slot,document in documents.items():
        grid=lookfile.writer_document(document)
        kind,record=photofull.entry(cp,basis,document.get('edit_native')or document.get('native_photo'))
        updates[slot]=(grid,record,kind)
    return replace(raw,updates)


def extract_cp(cp):
    """Read the persisted cold-start source, independent of RAM addresses."""
    from .fixedregion import SOURCE_DATA_START
    if cp[ROOT_VA-0x108000:ROOT_VA-0x108000+8]!=struct.pack('<2I',DATA_START,DATA_BYTES):
        raise ValueError('Fixed CP base/size descriptor is absent')
    if len(cp)<SOURCE_DATA_START+16:raise ValueError('Fixed source extent is truncated')
    total=struct.unpack_from('<I',cp,SOURCE_DATA_START)[0]
    if total<SLOTS_OFFSET or total>len(cp)-SOURCE_DATA_START:
        raise ValueError('Fixed CP persisted source size differs')
    raw=cp[SOURCE_DATA_START:SOURCE_DATA_START+total];info=parse(raw)
    native_at=NATIVE_TABLE-0x108000
    if info['native']!=cp[native_at:native_at+1400]:raise ValueError('Fixed CP original native rows differ')
    return raw


def replace_cp(cp,raw):
    """Replace only the declared persistent image; consumer pointers stay fixed."""
    from .fixedregion import SOURCE_DATA_START
    old=extract_cp(cp);a=parse(old);b=parse(raw)
    if len(old)!=len(raw) or a['count']!=b['count'] or a['native']!=b['native']or a['basis']!=b['basis']:
        raise ValueError('A per-slot update cannot resize/rebase the fixed source')
    out=bytearray(cp);out[SOURCE_DATA_START:SOURCE_DATA_START+len(raw)]=raw
    return bytes(out)


def state(cp,baseline=None):
    """Expose the original host slot interface from the relocated source."""
    from . import photofull,photoformat
    info=parse(extract_cp(cp));bank=photoformat.PhotoBank.unpack(info['basis'])
    if baseline is not None and baseline.pack()!=info['basis']:
        raise ValueError('Fresh native ST records differ from the fixed source basis')
    stages=[photofull.decode_stage(kind,record[FIXED_RECORD+4:],bank)for _,record,kind in info['entries'][:6]]
    return dict(revision='cp-fixed-v1',full=True,mask=sum((v is not None)<<i for i,v in enumerate(stages)),
                fixed_slot_mask=info['mask'],stages=stages,bank=bank)


def update_tables(cp,replacements,stages=None,baseline=None):
    from . import photofull,native
    current=state(cp,baseline);updates={}
    for slot,grid in replacements.items():
        if type(slot)is not int or not 1<=slot<=6:raise ValueError('Select custom slots 1..6')
        native.decode(grid)
        kind,record=photofull.entry(cp,current['bank'],(stages or{}).get(slot))
        updates[slot]=(grid,record,kind)
    return replace_cp(cp,replace(extract_cp(cp),updates))


def refresh_native(cp):
    """Follow an existing native FL23 edit without changing custom records."""
    from .fixedregion import SOURCE_DATA_START
    total=struct.unpack_from('<I',cp,SOURCE_DATA_START)[0]
    raw=cp[SOURCE_DATA_START:SOURCE_DATA_START+total];old=parse(raw)
    at=NATIVE_TABLE-0x108000
    image=build(cp[at:at+1400],old['basis'],old['entries'],old['mask'])
    out=bytearray(cp);out[SOURCE_DATA_START:SOURCE_DATA_START+len(image)]=image
    extract_cp(bytes(out));return bytes(out)
