.text
.global _start
_start:
    adr x0, vectors
    msr vbar_el3, x0
    isb
    mov x6, #0x0f000000
    ldr w7, [x6, #128]
    mov x3, #0xf000
    movk x3, #0xf102, lsl #16
    mrs x0, CurrentEL
    str x0, [x6, #80]
    ldr w0, [x3, #0x10]
    str x0, [x6, #8]
    str w7, [x3, #4]
    ldr w0, [x3]
    str x0, [x6, #16]
    str w7, [x3, #8]
    ldr w0, [x3]
    str x0, [x6, #24]
    str w7, [x3, #0x44]
    ldr w0, [x3, #0x40]
    str x0, [x6, #32]
    ldr w0, [x3, #0x10]
    str x0, [x6, #40]
    str w7, [x3, #0x24]
    ldr w0, [x3, #0x20]
    str x0, [x6, #48]
    str w7, [x3, #0x48]
    ldr w0, [x3, #0x10]
    str x0, [x6, #56]
    str w7, [x3, #0x34]
    ldr w0, [x3, #0x30]
    str x0, [x6, #88]
    str w7, [x3, #0x38]
    ldr w0, [x3, #0x30]
    str x0, [x6, #96]
    str wzr, [x3, #0x10] // external input is not a guest-writable completion flag
    mov x0, #0xbad
    str x0, [x6]
park:
    wfi
    b park
fault:
    mrs x0, esr_el3
    str x0, [x6, #64]
    mrs x0, far_el3
    str x0, [x6, #72]
    mov x0, #2
    str x0, [x6]
    b park
.balign 2048
vectors:
.rept 16
    b fault
    .space 124
.endr
