.text
.global _start
_start:
    mrs x7, mpidr_el1
    and x7, x7, #0xff
    mov x6, #0x0f000000
    add x6, x6, x7, lsl #7
    adr x0, vectors
    msr vbar_el3, x0
    isb
    mrs x0, mpidr_el1
    str x0, [x6, #8]
    mrs x0, CurrentEL
    str x0, [x6, #16]
    mov x0, #1
    str x0, [x6]
    dsb sy
    sev
    mov x5, #0x0f000000
check:
    ldr x0, [x5]
    ldr x1, [x5, #128]
    add x0, x0, x1
    ldr x1, [x5, #256]
    add x0, x0, x1
    ldr x1, [x5, #384]
    add x0, x0, x1
    cmp x0, #4
    b.eq done
    wfe
    b check
done:
    mov x0, #1
    str x0, [x6, #24]
    dsb sy
    sev
1:  wfi
    b 1b
fault:
    mrs x7, mpidr_el1
    and x7, x7, #0xff
    mov x6, #0x0f000000
    add x6, x6, x7, lsl #7
    mrs x0, esr_el3
    str x0, [x6, #32]
    mov x0, #0xbad
    str x0, [x6]
2:  wfi
    b 2b
.balign 2048
vectors:
.rept 16
    b fault
    .space 124
.endr
