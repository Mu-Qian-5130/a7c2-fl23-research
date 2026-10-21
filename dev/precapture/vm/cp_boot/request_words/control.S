// CP source is reference-code data for admission, not executed firmware.
.text
.global _start
_start:
    adr x0, vectors
    msr vbar_el3, x0
    isb
    mov x6, #0x0f000000
    ldr w7, [x6, #128]
    ldr w8, [x6, #136]
    mov x10, #0
    movk x10, #0xf540, lsl #16
    add x9, x10, #0x5d0
    cmp w7, #1
    b.eq bad_bit
    cmp w7, #2
    b.eq bad_offset
    cmp w7, #3
    b.eq unknown_word
    cmp w7, #4
    b.eq bad_width
    cmp w7, #5
    b.eq bad_code
    cmp w7, #6
    b.eq late_code_drift
    mov x12, #0x2000
    movk x12, #0x0f00, lsl #16
    ldr w13, [x12, #72]
    add x12, x12, #140
    mov w14, #0
loop:
    ldr w1, [x12]
    ldr w2, [x12, #4]
    add x9, x10, w1, uxtw
    str w2, [x9, #4]
    ldr w0, [x9]
    cmp w0, w2
    b.ne failed
    ldr w0, [x9, #4]
    cmp w0, w8
    b.ne failed
    str w2, [x9]
    ldr w0, [x9]
    cbnz w0, failed
    add x12, x12, #8
    add w14, w14, #1
    cmp w14, w13
    b.lo loop
    str w14, [x6, #8]
    mov w0, #1
    str w0, [x6]
    b park
bad_bit:
    mov w0, #2
    str w0, [x9, #4]
    b failed
bad_offset:
    mov w0, #1
    str w0, [x9, #8]
    b failed
unknown_word:
    ldr w0, [x10, #0xff0]
    b failed
bad_width:
    mov w0, #1
    strb w0, [x9, #4]
    b failed
bad_code:
    mov w0, #1
    str w0, [x9, #4]
    b failed
late_code_drift:
    mov w0, #1
    str w0, [x9, #4]
    mov x11, #0xb064
    movk x11, #0x52, lsl #16
    ldr w0, [x11]
    str w0, [x6, #16]
    eor w0, w0, #1
    str w0, [x11] // explicit mutation of reference data, not executed CP code
    dsb sy
    ldr w0, [x11]
    str w0, [x6, #20]
    mov w0, #4
    str w0, [x9, #4]
failed:
    mov w0, #0xbad
    str w0, [x6]
park:
    wfi
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
