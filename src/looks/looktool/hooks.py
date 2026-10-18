"""Bounded assembler sources for six ST-based custom markers; offline only."""
BASE=0x108000
HELPER=BASE+0xb27490


def assembler():
    from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB
    ks = Ks(KS_ARCH_ARM,KS_MODE_THUMB)
    return lambda text,at:bytes(ks.asm(text,addr=at)[0])


def ap_converter():
    from keystone import Ks,KS_ARCH_ARM64,KS_MODE_LITTLE_ENDIAN
    ks = Ks(KS_ARCH_ARM64,KS_MODE_LITTLE_ENDIAN)
    lines = ['cbnz w1,legacy','sub w0,w0,#10','cmp w0,#5','b.hi legacy',
             'add w0,w0,#249','strb w0,[x2]','ret',
             'legacy:','cmp w1,#11','b.hi 0x3528874','adr x0,values','ldrb w0,[x0,w1,uxtw]',
             'strb w0,[x2]','ret','values:','.byte 0,3,2,1,16,15,17,18,5,13,19,20']
    code = bytes(ks.asm('\n'.join(lines),addr=0x3528804)[0])
    if len(code) > 112 or (112-len(code))%4:
        raise ValueError("Six-slot converter does not fit")
    return code+bytes.fromhex('1f2003d5')*((112-len(code))//4)


def helper_code(assemble, table_base=0x110000, source_kind=1):
    """Historical unguarded instruction fixture; not the full7 camera helper.

    New six-program work must use sixbuild.helper with sixbuild.checker.
    This function remains only to reproduce earlier controlled hook tests.
    """
    gate = HELPER+0xc8
    legacy = HELPER+0x48
    lines = ['ldrb.w r3,[sl,#1]','cmp r3,#1',f'bne 0x{gate:x}',
             'ldrb.w r3,[sl,#0x2e]','sub.w r3,r3,#249','cmp r3,#5',f'bhi 0x{legacy:x}',
             'ldr.w r3,[sb,#4]','ldrb r3,[r3,#6]','cmp r3,#1',f'bhi 0x{legacy:x}',
             'ldrb.w r3,[sl,#0x2e]','sub.w r3,r3,#249',
             f'movw r2,#{table_base&65535}',f'movt r2,#{table_base>>16}',
             'movw r0,#1215','mla r2,r3,r0,r2','movs r0,#2',f'movs r1,#{source_kind}']
    code = assemble('\n'.join(lines),HELPER)
    if len(code) > 0x48:
        raise ValueError("Six-slot helper overlaps the preserved store path")
    store = assemble('cmp r2,#0;it eq;moveq r1,r2;str.w r2,[r5,#0x184];strb.w r1,[r5,#0x188];strb.w r0,[r5,#0x189];bx lr',legacy)
    if 0x48+len(store) > 0x70:
        raise ValueError("Helper store exceeds its region")
    blob = bytearray(256)
    blob[:len(code)] = code
    blob[0x48:0x48+len(store)] = store
    gamma = assemble('subw r1,r0,#249;cmp r1,#5;it ls;movls r0,#0;b.w 0x240832',HELPER+0x70)
    blob[0x70:0x70+len(gamma)] = gamma
    guard = assemble('\n'.join(['cmp r4,#0','bne build','ldrb.w r0,[sl,#0x2e]',
        'sub.w r0,r0,#249','cmp r0,#5','bhi skip','ldr.w r0,[sb,#4]',
        'ldrb r0,[r0,#6]','cmp r0,#1','beq build','bhi skip',
        'ldr.w r0,[r8,#0xc]','ldr.w r0,[r0,#0x6b0]','cmp r0,#0','beq skip',
        'build:','mov r0,sb','b.w 0x23d4e8','skip:','b.w 0x23d516']),HELPER+0x90)
    if len(guard) > 0x38:
        raise ValueError("Preview guard exceeds its region")
    blob[0x90:0x90+len(guard)] = guard
    helper_gate = assemble('\n'.join(['cmp r3,#0',f'bne 0x{legacy:x}',
        'ldr.w r3,[sb,#4]','ldrb r3,[r3,#6]','cmp r3,#1','beq resume',f'bhi 0x{legacy:x}',
        'ldr.w r3,[r8,#0xc]','ldr.w r3,[r3,#0x6b0]','cmp r3,#0',f'beq 0x{legacy:x}',
        'resume:',f'b.w 0x{HELPER+8:x}']),gate)
    if 0xc8+len(helper_gate) > 256:
        raise ValueError("Helper availability gate exceeds its region")
    blob[0xc8:0xc8+len(helper_gate)] = helper_gate
    return bytes(blob)
