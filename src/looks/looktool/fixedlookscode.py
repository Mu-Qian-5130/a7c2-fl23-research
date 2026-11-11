"""Reproduce fixed-preset native instructions inside existing function extents.

Used by the offline asset generator and instruction tests. No device I/O.
"""
from keystone import Ks, KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN
K=Ks(KS_ARCH_ARM64,KS_MODE_LITTLE_ENDIAN)
NOP=bytes.fromhex('1f2003d5')
CLASSIFY=0x21ab9e8
PREDICATE=0x1b5cd14
SETTER=0x2614ca0
SETTER_END=0x2614d6c
NORMALIZE=0x2614d4c
# Original recorded-file enum -> normal image, independently executed from C2.
# Zero entries represent the original hidden/unknown icon result.
PLAYBACK_NATIVE=(0x713,0x714,0x719,0,0,0,0x71e,0,0,0,0,0,0x715,0,0,0,0,
                 0x71f,0x2262,0x2261,0x2263,0x2260,0x4aaf,0x4ac7)
def asm(lines,at,size=None):
    b=bytes(K.asm(';'.join(lines),addr=at)[0])
    if size is not None:
        assert len(b)<=size,(hex(at),len(b),size)
        b+=NOP*((size-len(b))//4)
        assert len(b)==size
    return b

def fixed_converter(mask):
    """Fixed slots own their identity even when a producer cached an old base.

    Both production callers can pass snapshots without invoking the live base
    getter. Ordinary/unselected entries retain the original base mapping.
    """
    if type(mask)is not int or not 0<=mask<64:raise ValueError('Expected six-slot bitmap')
    return asm(['cmp w0,#16','b.eq special','sub w3,w0,#10','cmp w3,#5',
        'b.hi legacy',f'mov w0,#{mask}','lsr w0,w0,w3','tbz w0,#0,legacy',
        'add w0,w3,#249','b store','legacy:cmp w1,#11','b.hi 0x3528874',
        'adrp x0,0x4c7c000','add x0,x0,#0xf7c','ldrb w0,[x0,w1,uxtw]',
        'store:strb w0,[x2]','ret','special:mov w0,#-1','b store'],0x35287f0,80)

def code(mask):
    assert type(mask) is int and 0<=mask<64
    # Reuse the original menu-state reader with its original lock. The shared
    # predicate tail has an explicit entry frame, not a jump into arbitrary code.
    classify=asm([
        'stp x19,x30,[sp,#-32]!', 'add x0,sp,#16',
        'bl 0x2e06cc0', 'bl 0x21ab658', 'ldr w19,[x0]',
        'add x0,sp,#16', 'bl 0x2e068cc',
        'tail:sub w19,w19,#0x7f8',f'mov w0,#{63^mask}',
        'lsr w0,w0,w19','cmp w19,#5','and w0,w0,#1',
        'csel w0,w0,wzr,ls','ldp x19,x30,[sp],#32','ret'],CLASSIFY,64)
    predicate=asm(['stp x19,x30,[sp,#-32]!','mov w19,w1',f'b 0x{CLASSIFY+28:x}'],PREDICATE,16)
    # Equivalent valid setter path: same native context, lock, change logger,
    # backing field, main array, attribute notice and group notice. The original
    # invalid-index diagnostic path and entry frame remain unchanged.
    setter=asm([
        'ldr x21,[x29,#0x68]','bl 0x287ee10','mov x20,x0','bl 0x287ee24',
        'sub w3,w19,#10',f'mov w4,#{mask}','lsr w4,w4,w3',
        'cmp w3,#5','csel w4,w4,wzr,ls','tst w4,#1','csel w22,wzr,w22,ne',
        'mov w4,#40','smaddl x3,w19,w4,x0','ldr x25,[x3,#8]',
        'add x20,x20,w19,sxtw #2','mov w1,#0x14e9','add w19,w19,w1',
        'mov x2,x25','cmp x2,#0','csel x2,x20,x2,eq',
        'mov x0,x21','mov w1,w19','add x3,x29,#0x5c','str w22,[x3]',
        'mov x4,#4','bl 0x36830a8','cbz x25,unlinked','str w22,[x25]',
        'unlinked:str w22,[x20]','mov w0,w19','bl 0x2506ff0',
        'mov x0,x24','bl 0x2e068cc','mov x0,x23','bl 0x178f974',
        'mov w0,#0x14e9','bl 0x2506218',
        'ldp x19,x20,[sp,#0x10]','ldp x21,x22,[sp,#0x20]',
        'ldp x23,x24,[sp,#0x30]','ldp x25,x26,[sp,#0x40]',
        'ldp x29,x30,[sp],#0x90','ret'],SETTER)
    assert len(setter)==NORMALIZE-SETTER,(len(setter),NORMALIZE-SETTER)
    normalize=asm([f'str wzr,[x0,#{(slot+10)*4}]' for slot in range(6) if mask>>slot&1]+['ret'],NORMALIZE,SETTER_END-NORMALIZE)
    getter=asm(['adrp x0,0x7eac000','add x0,x0,#0x508',f'b 0x{NORMALIZE:x}'],0x287ee10,20)
    # Fixed items use their own adjustment index, never a cached mutable base.
    parameter=asm(['mov w1,w0',f'bl 0x{PREDICATE:x}','cbz w0,0x21b1344'],0x21b1290,12)
    # The same widget model as the ordinary preset: show the parameter panel,
    # hide the base picker, retaining all original placement and later logic.
    layout=asm([
        'stp x29,x30,[sp,#-0x40]!','mov x29,sp','stp x19,x20,[sp,#0x10]',
        'mov x19,x0','stp x21,x22,[sp,#0x20]','add x20,x29,#0x38',
        'ldr w1,[x19,#0x3950]',f'bl 0x{PREDICATE:x}','mov w22,w0',
        'ldr x0,[x19,#0x90]','add x0,x0,#0x80','str x0,[x29,#0x38]',
        'mov x0,x20','bl 0x1ac45ec','strb w22,[x0,#0x2c]',
        'ldr x0,[x19,#0x90]','add x0,x0,#0x90','str x0,[x29,#0x38]',
        'mov x0,x20','bl 0x1ac45ec','eor w1,w22,#1','strb w1,[x0,#0x2c]',
        'ldr x0,[x19,#0x90]','add x0,x0,#0xf0','str x0,[x29,#0x38]',
        'mov x0,x20','bl 0x2120bdc','strb w22,[x0,#0x2c]',
        'ldr x0,[x19,#0x90]','add x0,x0,#0x280','str x0,[x29,#0x38]',
        'mov x0,x20','bl 0x1ac45ec','strb w22,[x0,#0x2c]'],0x21b1434,0x21b14c4-0x21b1434)
    # Keep the original 0x40-byte frame, validity flags, source-mode selection,
    # complete invalid-mode diagnostic and native view-icon publication fields.
    # The compact native lookup frees space within this exact original function;
    # neither an executable segment nor an image registration is added.
    import struct
    table=struct.pack('<24H',*PLAYBACK_NATIVE)
    playback=asm([
        'none:mov w0,#-1','str w0,[x19,#0x3c]','b finish',
        'mode0:ldrb w0,[x3,#0xd60]','ldr w1,[x3,#0xd64]','b gate',
        'mode1:add x0,x3,#2,lsl #12','ldr w1,[x3,#0x2f14]','ldrb w0,[x0,#0xf10]',
        'gate:cbz w0,none','sub w2,w1,#249','cmp w2,#5','b.hi legacy',
        f'mov w0,#{mask}','lsr w0,w0,w2','tbz w0,#0,legacy','add w0,w2,#0x6c5','b publish',
        'legacy:cmp w1,#23','b.hi none','adr x0,table','ldrh w0,[x0,w1,uxtw #1]','cbz w0,none',
        'publish:movk w0,#0x200,lsl #16','str w0,[x19,#0x3c]',
        'mov w0,#0x6025','movk w0,#0x206,lsl #16','str w0,[x19,#0x48]',
        'mov w0,#1','str w0,[x19,#0x4c]',
        'finish:ldp x19,x20,[sp,#0x10]','ldp x21,x22,[sp,#0x20]',
        'ldr x23,[sp,#0x30]','ldp x29,x30,[sp],#0x40','ret',
        'table:','.byte '+','.join(str(v) for v in table)],0x23d1da4,0x23d1e78-0x23d1da4)
    playback_mode=asm(['b.eq 0x23d1dbc'],0x23d1d14,4)
    return {PREDICATE:predicate, CLASSIFY:classify, SETTER:setter+normalize,
        0x287ee10:getter,0x21b1290:parameter,0x21b1434:layout,
        0x23d1d14:playback_mode,0x23d1da4:playback}
