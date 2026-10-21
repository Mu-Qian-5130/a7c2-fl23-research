.text
.global _start
_start:
    mrs x7, mpidr_el1
    and x7, x7, #0xff
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
    mrs x7, mpidr_el1
    and x7, x7, #0xff
    mov x6, #0x0f000000
    add x6, x6, x7, lsl #7
    mrs x0, esr_el3
    str x0, [x6, #56]
    mov x0, #3
    str x0, [x6, #8]
1:  wfi
    b 1b
.balign 2048
vectors:
.rept 16
    b fault
    .space 124
.endr
