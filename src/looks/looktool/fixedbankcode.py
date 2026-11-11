"""Fixed high-address consumers with small absolute Thumb branch veneers."""
import struct
from . import fixedbank as bank
from .fixedlayout import CODE_START,ROOT_VA,DATA_BYTES

BASE=0x108000
START=0xC2F590
END=0xC2FF0E
CHECKER=0xC2FF10
CHECKER_END=0xC2FF70
NOP=bytes.fromhex('00bf')
# Existing instructions, not a file fingerprint. Recognition must also work
# for legacy writers that deliberately run without the optional assembler.
READER_ENTRY=bytes.fromhex('0eb549f64031c0f2')
VENEER_ENTRY=bytes.fromhex('dff800f04d007002')


def generate():
    from keystone import Ks,KS_ARCH_ARM,KS_MODE_THUMB,KS_MODE_V8
    k=Ks(KS_ARCH_ARM,KS_MODE_THUMB|KS_MODE_V8)
    def asm(lines,at):return bytes(k.asm(';'.join(lines),addr=at)[0])
    def literal(reg,value):return [f'movw {reg},#{value&65535}',f'movt {reg},#{value>>16}']
    def jump(target,label):return [f'ldr.w pc,{label}', '.align 2',f'{label}: .word {target|1}']
    def call(target):return [*literal('ip',target|1),'blx ip']
    code=bytearray();labels={}
    def add(name,lines):
        while len(code)&3:code.extend(NOP)
        at=CODE_START+len(code);raw=asm(lines,at);labels[name]=dict(address=at,bytes=len(raw));code.extend(raw);return at
    check=add('check_slot',[
        'push {r1,r2,r3,lr}',*literal('r1',ROOT_VA),'ldr r1,[r1]',
        'cmp r1,#0','beq invalid','ldr r2,[r1,#4]','cmp r0,r2','bhs invalid',
        'ldr r3,[r1,#8]','lsr.w r3,r3,r0','tst r3,#1','beq invalid',
        f'addw r1,r1,#{bank.DIRECTORY_OFFSET}','add.w r1,r1,r0,lsl #4',
        'ldr r0,[r1,#4]','pop {r1,r2,r3,pc}',
        'invalid:movs r0,#0','pop {r1,r2,r3,pc}'])
    primary_tramp=add('primary_trampoline',['push {r4,r5,r6,r7,lr}','add r7,sp,#12',*jump(0x7512E8,'primary_original')])
    secondary_tramp=add('secondary_trampoline',['push {r4,r5,r6,r7,lr}','add r7,sp,#12',*jump(0x751640,'secondary_original')])
    def wrapper(name,native,context,parameter,count,offset,selected=False):
        lines=[f'cmp {parameter},#0','bne native',f'cmp {context},#0','beq native',
            f'ldr ip,[{context}]','cmp.w ip,#0','beq native','ldrb.w ip,[ip,#1]',
            'cmp.w ip,#1','bhi native',f'ldr ip,[{context}]','ldrb.w ip,[ip,#0x2e]',
            'sub.w ip,ip,#249','cmp.w ip,#5','bhi native',
            'push {r0,r1,r2,r3,r4,r5,r6,lr}','mov r4,r0','mov r5,r1','mov r0,ip',
            f'bl {check}','cmp r0,#0','beq inactive','mov r6,r0','ldm.w sp,{r0,r1,r2,r3}',*call(native)]
        if selected:lines+=['cmp r5,#15','it hi','movhi r5,#0','movs r0,#54','mla r6,r5,r0,r6']
        if offset:lines+=[f'addw r6,r6,#{offset}']
        lines += [f'movs r3,#{count}','loop:ldrh r0,[r4]','ldrsh r1,[r6],#2',
            'add r0,r1','strh r0,[r4],#2','subs r3,#1','bne loop',
            'add sp,#16','pop {r4,r5,r6,pc}',
            'inactive:pop {r0,r1,r2,r3}','pop {r4,r5,r6,lr}','native:',*jump(native,name+'_native')]
        return add(name,lines)
    matrix=wrapper('matrix',0x751092,'r2','r3',27,0,True)
    primary=wrapper('primary_chroma',primary_tramp,'r2','r1',24,864)
    secondary=wrapper('secondary_chroma',secondary_tramp,'r3','r1',8,864)
    selector=add('gamma_selector',[
        'sub.w r1,r0,#249','cmp r1,#5','bhi native','push {r0,r1,r2,lr}','mov r0,r1',
        f'bl {check}','cmp r0,#0','pop {r0,r1,r2,lr}','beq inactive',
        'mov r0,r1',*literal('r1',ROOT_VA),'ldr r1,[r1]',f'addw r1,r1,#{bank.MODES_OFFSET}','bx lr',
        'inactive:movs r0,#0','native:cmp r0,#29','blo old','cmp r0,#32','bhi old','subs r0,#29',
        *literal('r1',0x1209B20),'bx lr','old:',*jump(0x240832,'selector_original')])
    checker=add('grid_checker',[
        'push {r0,r1,r4,lr}',*literal('r4',ROOT_VA),'ldr r4,[r4]',
        'cmp r4,#0','beq invalid','ldr r0,[r4,#4]','cmp r3,r0','bhs invalid',
        'ldr r1,[r4,#8]','lsr.w r1,r1,r3','tst r1,#1','beq invalid',
        f'addw r4,r4,#{bank.DIRECTORY_OFFSET}','add.w r4,r4,r3,lsl #4','ldr r2,[r4]',
        'ldr.w r0,[r5,#0x184]','cmp r0,r2','beq current',
        'cmp.w fp,#2','bhi current','ldr.w r0,[r8,#12]','add r0,fp',
        'movs r1,#0','strb.w r1,[r0,#0x54]',
        'current:movs r3,#1','pop {r0,r1,r4,pc}',
        'invalid:movs r3,#0','pop {r0,r1,r4,pc}'])
    low=bytearray();veneers={}
    def veneer(name,target,at=None):
        if at is None:
            while len(low)&3:low.extend(NOP)
            at=START+len(low)
        raw=asm(jump(target,name+'_target'),at)
        if at==START+len(low):low.extend(raw)
        veneers[name]=dict(address=at,target=target,bytes=len(raw))
        return at,raw
    mstub,_=veneer('matrix',matrix);pstub,_=veneer('primary_chroma',primary)
    sstub,_=veneer('secondary_chroma',secondary);gselector,_=veneer('gamma_selector',selector)
    sites=[]
    for index,(lo,hi,reg)in enumerate(((0x32345A,0x323464,'r11'),(0x323D82,0x323D8A,'r1'),
                                    (0x323DD0,0x323DD8,'r1'),(0x323EB6,0x323EBA,'r0'),(0x9CF436,0x9CF43E,'r1'))):
        target=add('table_'+hex(lo),['push {ip,lr}','mrs ip,apsr',
             *literal(reg,ROOT_VA),f'ldr {reg},[{reg}]',f'cmp {reg},#0','beq native',
             f'addw {reg},{reg},#{bank.GAMMA_OFFSET}','b complete',
             'native:',*literal(reg,bank.NATIVE_TABLE),'complete:',
             'msr APSR_nzcvq,ip','pop {ip,lr}',*jump(BASE+lo+4,'table_return')])
        near,_=veneer('table_'+str(index),target)
        sites.append(dict(low=lo,high=hi,register=reg,target=target,veneer=near))
    _,grid_stub=veneer('grid_checker',checker,at=CHECKER)
    if START+len(low)>END or len(grid_stub)>CHECKER_END-CHECKER:
        raise ValueError('Fixed reader veneers exceed the previously owned text window')
    patches={START-BASE:bytes(low)+NOP*((END-START-len(low))//2),
             CHECKER-BASE:grid_stub+NOP*((CHECKER_END-CHECKER-len(grid_stub))//2),
             0xB27500:asm([f'b.w {gselector}'],0xC2F500),
             0x6492E4:asm([f'b.w {pstub}'],BASE+0x6492E4),
             0x64963C:asm([f'b.w {sstub}'],BASE+0x64963C),
             0x64836C:asm([f'bl {mstub}'],BASE+0x64836C)}
    for site in sites:
        patches[site['low']]=asm([f'b.w {site["veneer"]}'],BASE+site['low'])
        patches[site['high']]=NOP*2
    return bytes(code),patches,dict(labels=labels,table_sites=sites,veneers=veneers,
        code_base=CODE_START,code_bytes=len(code),root=ROOT_VA,root_bytes=8,
        native_update_exit_preserved=[CHECKER_END,0xC2FFB0],native_slots=6,
        ready_field=False,generation_field=False,malloc=False)


def prepare(cp):
    """Replace only the identified old adapters; leave other native hooks alone."""
    from . import photofull,photoio,photobuild
    old=photofull.template();blob=bytes.fromhex(old['code']);legacy=False
    if cp[old['code_va']-BASE:old['code_va']-BASE+len(blob)]!=blob:
        old=dict(photoio.template(),code_va=photobuild.CODE_VA);blob=bytes.fromhex(old['code']);legacy=True
    if cp[old['code_va']-BASE:old['code_va']-BASE+len(blob)]!=blob:
        raise ValueError('Current native look adapter is not the expected predecessor')
    for item in old['hooks']:
        at=item['offset'];raw=bytes.fromhex(item['after'])
        if cp[at:at+len(raw)]!=raw:raise ValueError('Existing look hook differs at '+hex(at))
    code,patches,info=generate();out=bytearray(cp);windows=[]
    if legacy:
        at=photobuild.DATA_FILE
        magic,version,mask,stride=struct.unpack_from('<4I',cp,at)
        if (magic,version,stride)!=(photobuild.MAGIC,1,108):raise ValueError('Legacy native mode table differs')
        modes=cp[at+64+6*stride:at+96+6*stride]
        state=struct.pack('<4I',photofull.MAGIC,1,mask,0)+b''.join(struct.pack('<2I',50+2*i,51+2*i)for i in range(6))+modes
        patches[at]=state+bytes(old['basis_bytes']-len(state))
    from .fixedlayout import DATA_START
    patches[ROOT_VA-BASE]=struct.pack('<2I',DATA_START,DATA_BYTES)
    for at,raw in sorted(patches.items()):
        windows.append(dict(offset=at,before_hex=bytes(out[at:at+len(raw)]).hex(),after_hex=raw.hex()))
        out[at:at+len(raw)]=raw
    if out[CHECKER_END-BASE:0xC2FFB0-BASE]!=cp[CHECKER_END-BASE:0xC2FFB0-BASE]:
        raise ValueError('The native preview/update exit helper was changed')
    info['windows']=windows
    return bytes(out),code,info


def present(cp):
    """Recognize partial fixed adapters as well, so old writers cannot take over."""
    from .fixedlayout import DATA_START
    at=ROOT_VA-BASE
    from .fixedregion import SOURCE_CODE_START
    return (cp[START-BASE:START-BASE+8]==VENEER_ENTRY or
            (cp[at:at+8]==struct.pack('<2I',DATA_START,DATA_BYTES)and
             cp[SOURCE_CODE_START:SOURCE_CODE_START+8]==READER_ENTRY))


def inspect(cp):
    from .fixedlayout import DATA_START
    from .fixedregion import SOURCE_CODE_START,SOURCE_DATA_START
    code,patches,info=generate()
    for at,raw in patches.items():
        if cp[at:at+len(raw)]!=raw:
            raise ValueError('Fixed look consumer differs at '+hex(at))
    if cp[ROOT_VA-BASE:ROOT_VA-BASE+8]!=struct.pack('<2I',DATA_START,DATA_BYTES):
        raise ValueError('Fixed look base/size differs')
    if cp[SOURCE_CODE_START:SOURCE_CODE_START+len(code)]!=code:
        raise ValueError('Fixed look code source differs')
    image=bank.extract_cp(cp);parsed=bank.parse(image)
    return dict(revision='cp-fixed-v1',fixed=True,count=parsed['count'],mask=parsed['mask'],
                source_offset=SOURCE_DATA_START,image_bytes=len(image),
                base=DATA_START,size=DATA_BYTES,code_bytes=info['code_bytes'])
