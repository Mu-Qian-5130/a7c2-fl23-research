"""Reproducible AArch64 source for the bundled first-install AP templates.

Used by offline research/tests, not required by ordinary device imports. The
native virtual call stays at its original address. No new RX segment/cave.
"""
ENTRY,END,TITLE=0x35287f0,0x3528874,0x3528840
NATIVE_MAP=bytes([0,3,2,1,16,15,17,18,5,13,19,20])

def assemble(mask):
    if type(mask) is not int or mask not in range(64):raise ValueError('Expected a six-slot bitmap')
    from keystone import Ks,KS_ARCH_ARM64,KS_MODE_LITTLE_ENDIAN
    ks=Ks(KS_ARCH_ARM64,KS_MODE_LITTLE_ENDIAN)
    asm=lambda source,at:bytes(ks.asm(';'.join(source),addr=at)[0])
    converter=asm(['cmp w0,#16','b.eq special','cbnz w1,legacy',
        'sub w0,w0,#10','cmp w0,#5','b.hi legacy',f'mov w3,#{mask}',
        'lsr w3,w3,w0','tbz w3,#0,legacy','add w0,w0,#249','b store',
        'legacy:cmp w1,#11','b.hi 0x3528874','adrp x0,0x4c7c000',
        'add x0,x0,#0xf7c','ldrb w0,[x0,w1,uxtw]',
        'store:strb w0,[x2]','ret','special:mov w0,#-1','b store'],ENTRY)
    # Entry STP is preserved. The original MOV frame-pointer instruction
    # branches here; unselected items resume the original getter at +8.
    title=asm(['mov x29,sp','sub w2,w1,#0x7f8','cmp w2,#5','b.hi fallback',
        f'mov w3,#{mask}','lsr w3,w3,w2','tbz w3,#0,fallback',
        'mov w0,#0xab2c','movk w0,#0x200,lsl #16','add w0,w0,w2',
        'ldp x29,x30,[sp],#16','ret','fallback:b 0x1b5cd80'],TITLE)
    if len(converter)!=80 or len(title)!=52 or len(converter+title)!=END-ENTRY:raise ValueError('Existing function extent exceeded')
    branch=asm(['b 0x3528840'],0x1b5cd7c)
    return converter+title,branch,NATIVE_MAP
