.text
.global _start
_start:
    mrs x7, mpidr_el1
    and x7, x7, #0xff
    mov x0, #0x0d000000
    add x0, x0, x7, lsl #16
    mov sp, x0
    mov x6, #0x0f000000
    add x6, x6, x7, lsl #7
    adr x0, vectors
    msr vbar_el3, x0
    isb
    mrs x0, scr_el3
    orr x0, x0, #2
    msr scr_el3, x0
    isb
    mrs x0, mpidr_el1
    str x0, [x6, #8]
    mrs x0, CurrentEL
    str x0, [x6, #16]
    mov x5, #0x1000
    movk x5, #0xf13a, lsl #16
    mov x4, #0x2000
    movk x4, #0xf13a, lsl #16
    mov w0, #0
    str w0, [x5, #0x80]
    mov w0, #0xff
    str w0, [x4, #4]
    mov w0, #1
    str w0, [x4]
    cbnz x7, local_ready
    str w0, [x5]
    ldr w1, [x5, #4]
    str x1, [x6, #48]
    ldr w1, [x5, #8]
    str x1, [x6, #56]
local_ready:
    dsb sy
    msr daifclr, #2
    mov x0, #1
    str x0, [x6]
    dsb sy
    sev
    cbz x7, primary
secondary_idle:
    wfi
    ldr x0, [x6, #40]
    cbz x0, secondary_idle
    mov x0, #1
    str x0, [x6, #64]
    dsb sy
    sev
    b secondary_idle
primary:
    mov x3, #0x0f000000
check_ready:
    ldr x0, [x3]
    ldr x1, [x3, #128]
    add x0, x0, x1
    ldr x1, [x3, #256]
    add x0, x0, x1
    ldr x1, [x3, #384]
    add x0, x0, x1
    cmp x0, #4
    b.eq send_sgi
    wfe
    b check_ready
send_sgi:
    mov w0, #5
    movk w0, #2, lsl #16
    str w0, [x5, #0xf00]
    dsb sy
wait_ack:
    ldr x0, [x3, #192]
    cbnz x0, completed
    wfe
    b wait_ack
completed:
    mov x0, #1
    str x0, [x6, #24]
    dsb sy
1:  wfi
    b 1b
irq:
    stp x0, x1, [sp, #-48]!
    stp x2, x3, [sp, #16]
    str x4, [sp, #32]
    mov x0, #0x2000
    movk x0, #0xf13a, lsl #16
    ldr w1, [x0, #12]
    mrs x3, mpidr_el1
    and x3, x3, #0xff
    mov x4, #0x0f000000
    add x4, x4, x3, lsl #7
    str x1, [x4, #32]
    str w1, [x0, #16]
    dsb sy
    ldr x2, [x4, #40]
    add x2, x2, #1
    str x2, [x4, #40]
    dsb sy
    sev
    ldr x4, [sp, #32]
    ldp x2, x3, [sp, #16]
    ldp x0, x1, [sp], #48
    eret
.balign 2048
vectors:
.rept 16
    b irq
    .space 124
.endr
