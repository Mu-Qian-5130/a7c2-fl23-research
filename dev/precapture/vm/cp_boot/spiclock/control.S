.text
.global _start
_start:
    adr x0, vectors
    msr vbar_el3, x0
    isb
    mov x6, #0x0f000000
    ldr w7, [x6, #128]
    mov x9, #0x8230
    movk x9, #0xf138, lsl #16
    cmp w7, #1
    b.eq direct_write
    cmp w7, #2
    b.eq unknown_bit
    cmp w7, #3
    b.eq unknown_read
    cmp w7, #4
    b.eq bad_width
    ldr w0, [x9]
    str w0, [x6, #8]
    mov w0, #0x777
    movk w0, #3, lsl #16
    str w0, [x9, #4]
    ldr w0, [x9]
    str w0, [x6, #12]
    mov w0, #0x30000
    str w0, [x9, #8]
    mov w0, #0x10000
    str w0, [x9, #4]
    mov w0, #0x700
    str w0, [x9, #8]
    mov w0, #0x400
    str w0, [x9, #4]
    mov w0, #0x70
    str w0, [x9, #8]
    mov w0, #0x20
    str w0, [x9, #4]
    mov w0, #7
    str w0, [x9, #8]
    mov w0, #3
    str w0, [x9, #4]
    ldr w0, [x9]
    str w0, [x6, #16]
    ldr w0, [x9, #4]
    str w0, [x6, #20]
    ldr w0, [x9, #8]
    str w0, [x6, #24]
    str wzr, [x9, #4]
    ldr w0, [x9]
    str w0, [x6, #28]
    mov w0, #1
    str w0, [x6]
park:
    wfi
    b park
direct_write:
    str wzr, [x9]
    b failed
unknown_bit:
    mov w0, #8
    str w0, [x9, #4]
    b failed
unknown_read:
    ldr w0, [x9, #12]
    b failed
bad_width:
    mov w0, #1
    strb w0, [x9, #4]
failed:
    mov w0, #0xbad
    str w0, [x6]
    b park
fault:
    mrs x0, esr_el3
    str x0, [x6, #80]
    mrs x0, far_el3
    str x0, [x6, #88]
    mov w0, #3
    str w0, [x6]
    b park
.balign 2048
vectors:
.rept 16
    b fault
    .space 124
.endr
