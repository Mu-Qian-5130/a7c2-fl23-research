// Isolated helper test only. No native boot, device model or reset values.
.text
.global _start
_start:
    adr x0, vectors
    msr vbar_el3, x0
    isb
    mov x6, #0x1000
    movk x6, #0x0f00, lsl #16
    ldr x0, [x6]
    mov x5, #0x30
    msr scr_el3, x5
    mov x5, #0xd3
    msr spsr_el3, x5
    msr elr_el3, x0
    eret
fault:
    mov x6, #0x0f000000
    mrs x0, esr_el3
    str x0, [x6, #16]
    mrs x0, far_el3
    str x0, [x6, #24]
    mov w0, #3
    str w0, [x6]
park:
    wfi
    b park
.balign 2048
vectors:
.rept 16
    b fault
    .space 124
.endr
