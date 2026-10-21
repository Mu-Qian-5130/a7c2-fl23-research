.syntax unified
.arch armv7-a
.arm
.text
.global _arm_start
.global _start
_start:
_arm_start:
    mrc p15, 0, r7, c0, c0, 5
    and r7, r7, #255
    mov r6, #0x0f000000
    add r6, r6, r7, lsl #7
    mrc p15, 0, r0, c0, c0, 5
    str r0, [r6, #4]
    mov r4, #0x0d000000
    add r4, r4, r7, lsl #16
    cps #0x12
    add sp, r4, #0x8000
    cps #0x1f
    mov sp, r4
    ldr r0, =vectors32
    mcr p15, 0, r0, c12, c0, 0
    mrc p15, 0, r0, c1, c0, 0
    bic r0, r0, #0x2000
    mcr p15, 0, r0, c1, c0, 0
    isb
    ldr r5, =0xf13a1000
    ldr r4, =0xf13a2000
    mov r0, #0
    str r0, [r5, #0x80]
    mov r0, #0x60000000
    str r0, [r5, #0x100]
    mov r0, #255
    str r0, [r4, #4]
    mov r0, #1
    str r0, [r4]
    cmp r7, #0
    streq r0, [r5]
    dsb sy
    str r0, [r6]
    dsb sy
    sev
    mov r3, #0x0f000000
ready:
    ldr r0, [r3]
    ldr r1, [r3, #128]
    add r0, r0, r1
    ldr r1, [r3, #256]
    add r0, r0, r1
    ldr r1, [r3, #384]
    add r0, r0, r1
    cmp r0, #4
    beq arm_timer
    wfe
    b ready
arm_timer:
    mrc p15, 0, r2, c14, c0, 0
    str r2, [r6, #16]
    lsr r10, r2, #10
    str r10, [r6, #20]
    mov r0, #0
    mcr p15, 0, r0, c14, c2, 1
    mrrc p15, 0, r8, r9, c14
    str r8, [r6, #24]
    str r9, [r6, #28]
    mcr p15, 0, r10, c14, c2, 0
    mov r0, #1
    mcr p15, 0, r0, c14, c2, 1
    dsb sy
    isb
    cpsie i
await_timer:
    ldr r0, [r6, #36]
    cmp r0, #0
    bne interrupt_returned
    mrrc p15, 0, r0, r1, c14
    subs r2, r0, r8
    sbcs r3, r1, r9
    cmp r3, #0
    bne window_expired
    cmp r2, r10, lsl #2
    blo await_timer
window_expired:
    mrrc p15, 0, r0, r1, c14
    str r0, [r6, #40]
    str r1, [r6, #44]
    mrc p15, 0, r0, c14, c2, 1
    str r0, [r6, #48]
    mov r0, #2
    b finish
interrupt_returned:
    mrrc p15, 0, r0, r1, c14
    str r0, [r6, #40]
    str r1, [r6, #44]
    mrc p15, 0, r0, c14, c2, 1
    str r0, [r6, #48]
    mov r0, #1
finish:
    mrs r1, cpsr
    str r1, [r6, #12]
    dsb sy
    str r0, [r6, #8]
    dsb sy
1:  wfi
    b 1b
irq32:
    sub lr, lr, #4
    push {r0-r3,r12,lr}
    ldr r0, =0xf13a2000
    ldr r1, [r0, #12]
    mrc p15, 0, r2, c0, c0, 5
    and r2, r2, #255
    mov r3, #0x0f000000
    add r3, r3, r2, lsl #7
    str r1, [r3, #32]
    mov r12, #0
    mcr p15, 0, r12, c14, c2, 1
    dsb sy
    isb
    str r1, [r0, #16]
    dsb sy
    ldr r12, [r3, #36]
    add r12, r12, #1
    str r12, [r3, #36]
    dsb sy
    ldmia sp!, {r0-r3,r12,pc}^
fault32:
    mrc p15, 0, r0, c5, c0, 0
    str r0, [r6, #56]
    mrc p15, 0, r0, c6, c0, 0
    str r0, [r6, #60]
    mov r0, #3
    str r0, [r6, #8]
2:  wfi
    b 2b
.balign 32
vectors32:
    b fault32
    b fault32
    b fault32
    b fault32
    b fault32
    b fault32
    b irq32
    b fault32
.ltorg
