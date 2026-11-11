"""C2 full-record runtime candidate. Offline compilation and byte inspection.

The additional prefix allocation follows the existing full-file six-grid
loader contract. It is integrity gated, does not grow a segment or BSS, and
requires separate loader/lifetime and physical qualification.
"""
import json
import struct
from pathlib import Path
from . import editrecipe, photoformat as photo, photobasis, photobuild, six

MAGIC = 0x33465041
VERSION = 1
PREFIX_FILE = 0xa000
PREFIX_VA = photobuild.BASE + PREFIX_FILE
PREFIX_END = 0x20000
HEADER = 128
MATRIX = 16*27*2
CHROMA = 24*2
CURVES = 14*576
FIXED = MATRIX+CHROMA+CURVES
CODE_FILE = photobuild.CODE_FILE
CODE_VA = photobuild.CODE_VA


def present(cp):
    return cp[photobuild.DATA_FILE:photobuild.DATA_FILE+4] == struct.pack('<I',MAGIC)


def encode_stage(stage):
    if stage is None:return 0,b''
    if stage.get('schema') == editrecipe.SCHEMA:return 2,editrecipe.pack(stage)
    basis=stage.get('runtime_basis',{})
    if basis.get('schema') != photobasis.SCHEMA:raise ValueError('Unsupported full-runtime source stage')
    values=basis['tone_q10']+[v for row in basis['matrix_planes'] for v in row]+[v for row in basis['chroma_planes'] for v in row]
    return 1,struct.pack('<45h',*values)


def decode_stage(kind,raw,bank):
    if kind==0 and not raw:return None
    if kind==2:return editrecipe.unpack(raw)
    if kind==1 and len(raw)==90:
        a=struct.unpack('<45h',raw)
        return photobasis.pack(bank,list(a[:3]),[list(a[3+p*6:9+p*6])for p in range(3)],
                              [list(a[21+p*8:29+p*8])for p in range(3)])[1]
    raise ValueError('Invalid full-runtime stage encoding')


def authored(stage,bank):
    """Match the original R5 fit export's native fields without reducing them.

    The RAW context has 128 ordinates; native record point128 is separate.
    Preserve a template endpoint when valid, otherwise raise it to point127.
    No fitted ordinate is clipped, smoothed or approximated.
    """
    editrecipe.validate(stage)
    p=stage['fitted'];raw=bytes.fromhex(p['matrix_780f_hex'])
    y=p['gamma_7806_y']
    if any(v&1 for v in y):raise ValueError('An odd RAW Gamma ordinate cannot be exported losslessly')
    gamma=[v//2 for v in y]
    # Same signed packed-coefficient extraction used by the original v4
    # compiler. Verify the complete meaningful bitfield on the way back.
    matrix=[[struct.unpack_from('<h',raw,24+2*(16*k+(s^1)))[0]>>2 for k in range(6)]for s in range(16)]
    for s,row in enumerate(matrix):
        for k,v in enumerate(row):
            if ((v<<2)&0xfffc)!=(struct.unpack_from('<H',raw,24+2*(16*k+(s^1)))[0]&0xfffc):
                raise ValueError('Packed matrix conversion differs')
    cc=p['cc1_direct_raw']
    if any(v&1 for v in cc[4:]):raise ValueError('An odd RAW CC1 gain cannot be exported losslessly')
    chroma=[cc[i]for i in (1,2,3,0)]+[cc[i]//2 for i in (5,6,7,4)]
    if any(not 0<=v<=1023 for v in chroma[4:]):raise ValueError('Native CC1 gain is outside its 10-bit field')
    original=struct.unpack('<288h',bank.matrices)
    matrix_delta=[[[matrix[s][j]-original[p*96+s*6+j]for j in range(6)]for s in range(16)]for p in range(3)]
    old=photo.expand_chroma(bank.chroma)
    # Preserve native user adjustments in the loader; author all three source
    # planes explicitly, rather than silently omitting two of them.
    chroma_delta=[[chroma[j]-old[p*8+j]for j in range(8)]for p in range(3)]
    return gamma,matrix_delta,chroma_delta


def entry(source,bank,stage):
    kind,encoded=encode_stage(stage)
    if kind==2:gamma,matrices,chroma=authored(stage,bank)
    else:
        basis=stage['runtime_basis'] if stage else dict(tone_q10=[0]*3,matrix_planes=[[0]*6 for _ in range(3)],chroma_planes=[[0]*8 for _ in range(3)])
        if stage:photobasis.compile_delta(bank,stage)
        matrices=[[basis['matrix_planes'][p]for _ in range(16)]for p in range(3)]
        chroma=basis['chroma_planes']
    expanded=[v for s in range(16)for p in range(3)for v in photo.expand_matrix(matrices[p][s],(0,0,0))]
    if any(not -32768<=v<=32767 for v in expanded):raise ValueError('Full matrix delta overflows native int16')
    blob=bytearray(struct.pack('<432h24h',*expanded,*[v for row in chroma for v in row]))
    for domain,row in enumerate((0,10)):
        for column in range(7):
            pointer=struct.unpack_from('<I',source,0x1209480-photobuild.BASE+row*28+column*4)[0]
            if not pointer:pointer=struct.unpack_from('<I',source,0x1209480-photobuild.BASE+24)[0]
            at=pointer-photobuild.BASE
            if not pointer or not 0<=at<=len(source)-576:raise ValueError('Native ST curve pointer differs')
            record=source[at:at+576]
            if kind==2:
                coordinates=photo.gamma_coordinates(record)
                axis=stage['gamma_7805_x']
                if tuple(axis)!=tuple(v*32 for v in (*coordinates[:127],coordinates[-1])):
                    raise ValueError('Native curve axis differs from the fitted C2 axis')
                # The native endpoint was absent from the 128-node fit.
                endpoint=max(photo.gamma_values(record)[-1],gamma[-1])
                record=photo.replace_gamma_values(record,gamma+[endpoint])
            else:record=photobasis.curve(record,basis['tone_q10'])
            blob.extend(record)
    assert len(blob)==FIXED
    blob.extend(struct.pack('<I',len(encoded)));blob.extend(encoded)
    return kind,bytes(blob)


def _assembler():
    from keystone import Ks,KS_ARCH_ARM,KS_MODE_THUMB,KS_MODE_V8
    ks=Ks(KS_ARCH_ARM,KS_MODE_THUMB|KS_MODE_V8)
    return lambda text,addr:bytes(ks.asm(text,addr=addr)[0])


def template():
    value=json.loads((Path(__file__).resolve().parents[1]/'assets/native-photo-full-v1.json').read_text(encoding='utf-8'))
    if value.get('schema')!='a7c2-full-native-code-template/1' or value.get('code_va')!=CODE_VA:
        raise ValueError('Full native code template differs')
    return value


def build(source,bank,stages,*,assemble=False):
    if len(stages)!=6:raise ValueError('Six source stages required')
    if any(source[PREFIX_FILE:PREFIX_END]):
        raise ValueError('Full-native prefix is occupied; validate and remove the previous owned image first')
    target=bytearray(source);mask=sum((s is not None)<<i for i,s in enumerate(stages))
    data=bytearray(HEADER);data.extend(bank.pack());directory=[]
    table=bytearray(source[0x1209480-photobuild.BASE:0x1209480-photobuild.BASE+50*28])
    for slot,stage in enumerate(stages):
        while len(data)&3:data.append(0)
        offset=len(data);kind,raw=entry(source,bank,stage);data.extend(raw)
        directory.append((offset,len(raw),six.fnv(raw),kind))
        for domain in range(2):
            table.extend(struct.pack('<7I',*[PREFIX_VA+offset+MATRIX+CHROMA+(domain*7+c)*576 for c in range(7)]))
    if PREFIX_FILE+len(data)>PREFIX_END:raise ValueError('Full native payload exceeds its declared prefix allocation')
    struct.pack_into('<6I',data,0,MAGIC,VERSION,len(data),mask,six.fnv(data[HEADER:]),len(bank.pack()))
    for i,row in enumerate(directory):struct.pack_into('<4I',data,32+i*16,*row)
    if len(table)!=photobuild.GAMMA_ROWS*28:raise ValueError('Native Gamma table shape differs')
    target[PREFIX_FILE:PREFIX_END]=data+bytes(PREFIX_END-PREFIX_FILE-len(data))
    target[photobuild.TABLE_FILE:photobuild.CODE_FILE]=table
    state=struct.pack('<4I',MAGIC,VERSION,mask,0)
    state+=b''.join(struct.pack('<2I',50+2*i,51+2*i)for i in range(6))
    legacy_at=0x12099f8-photobuild.BASE+29*8
    state+=source[legacy_at:legacy_at+32]
    target[photobuild.DATA_FILE:photobuild.DATA_FILE+len(state)]=state
    if not assemble:
        spec=template();code=bytes.fromhex(spec['code'])
        if len(code)!=spec['code_bytes'] or CODE_VA+len(code)>photobuild.CODE_END:
            raise ValueError('Full native code dimensions differ')
        target[CODE_FILE:CODE_FILE+len(code)]=code
        for hook in spec['hooks']:
            at=hook['offset'];old=bytes.fromhex(hook['before']);new=bytes.fromhex(hook['after'])
            if len(old)!=len(new)or source[at:at+len(old)]!=old:
                raise ValueError('Full native source hook differs at '+hex(at))
            target[at:at+len(new)]=new
        regions=[(PREFIX_FILE,PREFIX_END-PREFIX_FILE),(photobuild.TABLE_FILE,len(table)+len(code)),
                 (photobuild.DATA_FILE,len(state))]+[(h['offset'],len(bytes.fromhex(h['after'])))for h in spec['hooks']]
        return bytes(target),dict(spec,camera_io=False,regions=regions,prefix_bytes=len(data),mask=mask,
            full_file_prefix_loader_required=True,physical_acceptance=False,stage_types=[r[3]for r in directory])
    asm=_assembler()
    code=bytearray();labels={}
    def literal(reg,value):return [f'movw {reg},#{value&65535}',f'movt {reg},#{value>>16}']
    def allocate(name,lines):
        while len(code)&3:code.extend(b'\0\xbf')
        at=CODE_VA+len(code);raw=asm('\n'.join(lines),at)
        labels[name]=dict(address=at,bytes=len(raw));code.extend(raw);return at
    check=allocate('check_slot',[
        'cmp r0,#5','bhi invalid','push {r0,r4,r5,r6,r7,lr}',*literal('r4',PREFIX_VA),
        'ldr r1,[r4]',*literal('r2',MAGIC),'cmp r1,r2','bne failed',
        'ldr r1,[r4,#4]','cmp r1,#1','bne failed','ldr r1,[r4,#12]',
        *literal('r2',photobuild.DATA_VA+8),'ldr r2,[r2]','cmp r1,r2','bne failed',
        'lsr.w r1,r1,r0','tst r1,#1','beq failed','add.w r3,r4,#32','add.w r3,r3,r0,lsl #4',
        'ldr r5,[r3]','ldr r6,[r3,#4]','ldr r7,[r3,#8]','movw r1,#1920','cmp r5,r1','blo failed',
        f'movw r1,#{FIXED+4}','cmp r6,r1','blo failed',f'movw r1,#{FIXED+4+2200}',
        'cmp r6,r1','bhi failed','add.w r0,r5,r6',*literal('r1',PREFIX_END-PREFIX_FILE),
        'cmp r0,r1','bhi failed','add r5,r4','mov r3,r5',*literal('r1',2166136261),
        *literal('r2',16777619),'loop:','ldrb r0,[r3],#1','eors r1,r0','muls r1,r2,r1',
        'subs r6,#1','bne loop','cmp r1,r7','bne failed',
        # An interrupted prefix replacement can relocate later slots while the
        # shared Gamma pointer table is still old. Never activate that mixture.
        'ldr r0,[sp]','movs r1,#56','muls r0,r1,r0',
        *literal('r1',photobuild.TABLE_VA+50*28),'add r1,r0',
        f'addw r2,r5,#{MATRIX+CHROMA}','movs r6,#14','curve_pointer:',
        'ldr r0,[r1],#4','cmp r0,r2','bne failed','addw r2,r2,#576',
        'subs r6,#1','bne curve_pointer','mov r0,r5',
        'pop {r1,r4,r5,r6,r7,pc}','failed:','movs r0,#0','pop {r1,r4,r5,r6,r7,pc}',
        'invalid:','movs r0,#0','bx lr'])
    primary_tramp=allocate('primary_trampoline',['push {r4,r5,r6,r7,lr}','add r7,sp,#12','b.w 0x7512e8'])
    secondary_tramp=allocate('secondary_trampoline',['push {r4,r5,r6,r7,lr}','add r7,sp,#12','b.w 0x751640'])
    def wrapper(name,native,context,parameter,count,offset,selected=False):
        lines=[f'cmp {parameter},#0','bne native',f'cmp {context},#0','beq native',
            f'ldr ip,[{context}]','cmp.w ip,#0','beq native','ldrb.w ip,[ip,#1]',
            'cmp.w ip,#1','bhi native',f'ldr ip,[{context}]','ldrb.w ip,[ip,#0x2e]',
            'sub.w ip,ip,#249','cmp.w ip,#5','bhi native',
            'push {r0,r1,r2,r3,r4,r5,r6,lr}','mov r4,r0','mov r5,r1','mov r0,ip',
            f'bl 0x{check:x}','cmp r0,#0','beq inactive','mov r6,r0','ldm.w sp,{r0,r1,r2,r3}',
            f'bl 0x{native:x}']
        if selected:lines+=['cmp r5,#15','it hi','movhi r5,#0','movs r0,#54','mla r6,r5,r0,r6']
        if offset:lines += [f'addw r6,r6,#{offset}']
        lines += [f'movs r3,#{count}','loop:','ldrh r0,[r4]','ldrsh r1,[r6],#2',
            'add r0,r1','strh r0,[r4],#2','subs r3,#1','bne loop','add sp,#16','pop {r4,r5,r6,pc}',
            'inactive:','pop {r0,r1,r2,r3}','pop {r4,r5,r6,lr}','native:',f'b.w 0x{native:x}']
        return allocate(name,lines)
    matrix=wrapper('matrix',0x751092,'r2','r3',27,0,True)
    primary=wrapper('primary_chroma',primary_tramp,'r2','r1',24,MATRIX)
    secondary=wrapper('secondary_chroma',secondary_tramp,'r3','r1',8,MATRIX)
    selector=allocate('gamma_selector',[
        'sub.w r1,r0,#249','cmp r1,#5','bhi native','push {r0,r1,r2,lr}','mov r0,r1',
        f'bl 0x{check:x}','cmp r0,#0','pop {r0,r1,r2,lr}','beq inactive',
        'mov r0,r1',*literal('r1',photobuild.MODE_VA),'bx lr','inactive:','movs r0,#0',
        'native:','cmp r0,#29','blo old','cmp r0,#32','bhi old','subs r0,#29',
        *literal('r1',photobuild.DATA_VA+64),'bx lr','old:','b.w 0x240832'])
    if CODE_VA+len(code)>photobuild.CODE_END:raise ValueError(f'Full native code exceeds owned text: {len(code)}')
    target[CODE_FILE:CODE_FILE+len(code)]=code
    patches=[]
    def hook(at,before,after):
        old=asm(before,at+photobuild.BASE);new=asm(after,at+photobuild.BASE)
        if len(old)!=len(new)or source[at:at+len(old)]!=old:raise ValueError('Full native source hook differs at '+hex(at))
        target[at:at+len(new)]=new;patches.append(dict(offset=at,before=old.hex(),after=new.hex()))
    hook(0xb27500,'subw r1,r0,#249',f'b.w 0x{selector:x}')
    hook(0x6492e4,'push {r4,r5,r6,r7,lr};add r7,sp,#12',f'b.w 0x{primary:x}')
    hook(0x64963c,'push {r4,r5,r6,r7,lr};add r7,sp,#12',f'b.w 0x{secondary:x}')
    hook(0x64836c,'bl 0x751092',f'bl 0x{matrix:x}')
    for low,high,reg in [(0x32345a,0x323464,'r11'),(0x323d82,0x323d8a,'r1'),
        (0x323dd0,0x323dd8,'r1'),(0x323eb6,0x323eba,'r0'),(0x9cf436,0x9cf43e,'r1')]:
        hook(low,f'movw {reg},#0x9480',f'movw {reg},#{photobuild.TABLE_VA&65535}')
        hook(high,f'movt {reg},#0x120',f'movt {reg},#{photobuild.TABLE_VA>>16}')
    for at in (0x32325c,0x323278,0x9cf404):hook(at,'cmp r0,#50','cmp r0,#62')
    regions=[(PREFIX_FILE,PREFIX_END-PREFIX_FILE),(photobuild.TABLE_FILE,len(table)+len(code)),
             (photobuild.DATA_FILE,len(state))]+[(p['offset'],len(bytes.fromhex(p['after'])))for p in patches]
    if target[0x20124:0x20154]!=source[0x20124:0x20154]or len(target)!=len(source):raise ValueError('Full native allocation changed program extents')
    return bytes(target),dict(camera_io=False,code=code.hex(),code_bytes=len(code),hooks=patches,labels=labels,
        regions=regions,prefix_bytes=len(data),mask=mask,full_file_prefix_loader_required=True,
        physical_acceptance=False,stage_types=[r[3]for r in directory])


def read_state(cp):
    if not present(cp):return None
    if len(cp)<PREFIX_END:raise ValueError('Full native prefix is truncated')
    header=struct.unpack_from('<6I',cp,PREFIX_FILE)
    magic,version,length,mask,checksum,bank_bytes=header
    if (magic,version,bank_bytes)!=(MAGIC,VERSION,photo.BANK_BYTES) or not 0<=mask<64 or not HEADER+bank_bytes<=length<=PREFIX_END-PREFIX_FILE:
        raise ValueError('Full native prefix header differs')
    if cp[PREFIX_FILE+24:PREFIX_FILE+32]!=bytes(8):raise ValueError('Full native reserved header differs')
    payload=cp[PREFIX_FILE+HEADER:PREFIX_FILE+length]
    if six.fnv(payload)!=checksum:raise ValueError('Full native prefix checksum differs')
    bank=photo.PhotoBank.unpack(payload[:bank_bytes]);stages=[]
    for slot in range(6):
        at,size,check,kind=struct.unpack_from('<4I',cp,PREFIX_FILE+32+slot*16)
        if at<HEADER+bank_bytes or not FIXED+4<=size<=FIXED+4+2200 or at+size>length:
            raise ValueError('Full native slot extent differs')
        raw=cp[PREFIX_FILE+at:PREFIX_FILE+at+size]
        if six.fnv(raw)!=check:raise ValueError('Full native slot checksum differs')
        encoded_size=struct.unpack_from('<I',raw,FIXED)[0]
        if encoded_size!=size-FIXED-4:raise ValueError('Full native stage length differs')
        stage=decode_stage(kind,raw[FIXED+4:],bank)
        if bool(stage)!=bool(mask&(1<<slot)):raise ValueError('Full native activation mask differs')
        stages.append(stage)
    return dict(mask=mask,bank=bank,stages=stages,revision='C2-full-record-prefix-v1',full=True,
                prefix_bytes=length,full_file_prefix_loader_required=True)


def underlay(cp):
    if not present(cp):raise ValueError('Full native runtime is absent')
    target=bytearray(cp)
    for hook in template()['hooks']:
        at=hook['offset'];target[at:at+len(bytes.fromhex(hook['before']))]=bytes.fromhex(hook['before'])
    target[PREFIX_FILE:PREFIX_END]=bytes(PREFIX_END-PREFIX_FILE)
    target[photobuild.DATA_FILE:photobuild.DATA_FILE+32]=cp[photobuild.DATA_FILE+64:photobuild.DATA_FILE+96]
    return bytes(target)


def inspect(cp,baseline=None):
    state=read_state(cp)
    if state is None:return None
    if baseline is not None and baseline!=state['bank']:
        raise ValueError('Fresh native ST records differ from the installed full native basis')
    from . import photoio
    source=underlay(cp);photoio.allocation(source)
    expected,report=build(source,state['bank'],state['stages'])
    for at,size in report['regions']:
        if cp[at:at+size]!=expected[at:at+size]:
            raise ValueError('Full native runtime bytes conflict at '+hex(at))
    # Keep private body records out of ordinary state/report serialization.
    return {k:v for k,v in state.items()if k!='bank'}


def update(cp,changes,baseline,*,allocation_proved=False):
    from . import photoio
    if baseline is None:raise ValueError('Fresh native ST records are required for full stages')
    state=read_state(cp)
    if state:
        inspect(cp,baseline);stages=state['stages'];source=underlay(cp)
    else:
        old=photoio.inspect(cp,baseline)
        stages=[photobasis.pack(baseline,**k)[1]if old['mask']&(1<<i)else None for i,k in enumerate(old['knobs'])]if old else [None]*6
        if not old and not allocation_proved:raise ValueError('Canonical six-table allocation must be established')
        source=photoio.underlay(cp)if old else cp
    source=photoio.preview_helper(source);photoio.allocation(source)
    for slot,stage in changes.items():
        if type(slot)is not int or slot not in range(1,7):raise ValueError('Select custom slots 1..6')
        if stage is not None:
            if stage.get('schema')==editrecipe.SCHEMA:editrecipe.validate(stage)
            else:photobasis.compile_delta(baseline,stage)
        stages[slot-1]=stage
    result,report=build(source,baseline,stages)
    inspect(result,baseline)
    return result


def refresh_gamma_table(cp):
    target=bytearray(cp)
    start=0x1209480-photobuild.BASE;size=50*28
    target[photobuild.TABLE_FILE:photobuild.TABLE_FILE+size]=cp[start:start+size]
    inspect(bytes(target))
    return bytes(target)
