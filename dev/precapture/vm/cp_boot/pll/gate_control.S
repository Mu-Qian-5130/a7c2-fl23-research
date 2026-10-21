.text
.global _start
_start:
    adr x0, vectors
    msr vbar_el3, x0
    isb
    mov x6, #0x0f000000
    ldr w7, [x6, #128]
    mov x9, #0x8070
    movk x9, #0xf138, lsl #16
    mov x10, #0x8000
    movk x10, #0xf138, lsl #16
    cmp w7, #1
    b.eq unknown_logic
    cmp w7, #2
    b.eq unknown_media
    cmp w7, #3
    b.eq direct_media
    cmp w7, #4
    b.eq outside_media
    cmp w7, #5
    b.eq wrong_width
    cmp w7, #6
    b.eq reserved_logic
    mov w0, #0xfde3
    movk w0, #0x1ff, lsl #16
    str w0, [x9, #4]
    ldr w0, [x9]
    str w0, [x6, #8]
    mov w0, #0x100
    movk w0, #0x40, lsl #16
    str w0, [x9, #8]
    ldr w0, [x9]
    str w0, [x6, #12]
    mov w0, #0x100
    str w0, [x10, #4]
    ldr w0, [x10]
    str w0, [x6, #16]
    ldr w0, [x9]
    str w0, [x6, #20]
    ldr w0, [x9, #4]
    str w0, [x6, #24]
    ldr w0, [x10, #8]
    str w0, [x6, #28]
    mov w0, #0x100
    str w0, [x10, #8]
    ldr w0, [x10]
    str w0, [x6, #32]
    mov w0, #0xfde3
    movk w0, #0x1ff, lsl #16
    str w0, [x9, #8]
    ldr w0, [x9]
    str w0, [x6, #36]
    ldr w0, [x10, #0x100]
    str w0, [x6, #40] // separate PLL0 state has not changed
    mov w0, #1
    str w0, [x6]
park:
    wfi
    b park
unknown_logic:
    mov w0, #0x200
    str w0, [x9, #4]
    b failed
unknown_media:
    mov w0, #0x200
    str w0, [x10, #4]
    b failed
direct_media:
    str wzr, [x10]
    b failed
outside_media:
    ldr w0, [x10, #12]
    b failed
wrong_width:
    mov w0, #1
    strb w0, [x9, #4]
    b failed
reserved_logic:
    mov w0, #0x80000000
    str w0, [x9, #4]
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
