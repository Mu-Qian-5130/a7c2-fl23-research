// CP is loaded only as source-admission data in this control, never executed.
.text
.global _start
_start:
    adr x0, vectors
    msr vbar_el3, x0
    isb
    mov x6, #0x0f000000
    ldr w7, [x6, #128]
    ldr w8, [x6, #132]
    mov x9, #0x8038
    movk x9, #0xf540, lsl #16
    cmp w7, #1
    b.eq unknown_bit
    cmp w7, #2
    b.eq wrong_width
    cmp w7, #3
    b.eq neighbour
    cmp w7, #4
    b.eq changed_code
    cmp w7, #5
    b.eq late_changed_code
    ldr w0, [x9]
    cmp w0, w8
    b.ne failed
    orr w0, w0, #0x4000
    str w0, [x9]
    ldr w1, [x9]
    cmp w0, w1
    b.ne failed
    bic w0, w0, #0x4000
    str w0, [x9]
    ldr w1, [x9]
    cmp w0, w1
    b.ne failed
    str w1, [x6, #8]
    mov w0, #1
    str w0, [x6]
    b park
unknown_bit:
    eor w0, w8, #1
    str w0, [x9]
    b failed
wrong_width:
    ldrb w0, [x9]
    b failed
neighbour:
    ldr w0, [x9, #4]
    b failed
changed_code:
    ldr w0, [x9]
    b failed
late_changed_code:
    ldr w0, [x9]
    str w0, [x6, #16]
    orr w0, w0, #0x4000
    str w0, [x9]
    mov x10, #0x4730
    movk x10, #0xb7, lsl #16
    ldr w0, [x10]
    str w0, [x6, #20]
    eor w0, w0, #1
    str w0, [x10] // mutate reference data only, not executed firmware
    dsb sy
    ldr w0, [x10]
    str w0, [x6, #24]
    ldr w0, [x9]
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
