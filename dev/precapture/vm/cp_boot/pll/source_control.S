// Original CP is loaded only as reference-table data, never executed here.
// Input artifact at 0xf002000 uses the private CPLLSRC1 layout.
.text
.global _start
_start:
    adr x0, vectors
    msr vbar_el3, x0
    isb
    mov x6, #0x0f000000
    ldr w7, [x6, #128]
    ldr w8, [x6, #132]
    mov x10, #0x8100
    movk x10, #0xf138, lsl #16
    add x9, x10, x8, lsl #2
    mov x11, #0x8200
    movk x11, #0xf138, lsl #16
    mov x12, #0x2000
    movk x12, #0x0f00, lsl #16
    add x12, x12, #108 // second tuple: preset0/mode1
    ldr w1, [x12]
    cmp w7, #1
    b.ne selector
    eor w1, w1, #1
selector:
    str w1, [x11, #4]
    mov w0, #0xfd13
    bic w0, w0, w1
    str w0, [x11, #8]
    ldr w0, [x12, #24]
    cmp w7, #3
    b.ne div0
    cmp w8, #1
    b.ne div0
    eor w0, w0, #2
div0:
    str w0, [x10, #0x50]
    ldr w0, [x12, #28]
    cmp w7, #3
    b.ne div1
    cmp w8, #3
    b.ne div1
    eor w0, w0, #2
div1:
    str w0, [x10, #0x58]
    add x12, x12, #4
    ldr w1, [x12, x8, lsl #2]
    cmp w7, #2
    b.ne coefficient
    eor w1, w1, #0x100
coefficient:
    str w1, [x9]
    orr w2, w1, #0x18000000
    str w2, [x9]
    cbnz w7, negative
    mov w3, #0
poll:
    ldr w0, [x9]
    tbnz w0, #24, complete
    add w3, w3, #1
    cmp w3, #0x100000
    b.lo poll
    b failed
complete:
    str w0, [x6, #8]
    mov w0, #1
    str w0, [x6]
    b park
negative:
    mov w3, #128
negative_poll:
    ldr w0, [x9]
    tbnz w0, #24, failed
    subs w3, w3, #1
    b.ne negative_poll
    str w0, [x6, #8]
    mov w0, #2
    str w0, [x6]
    b park
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
