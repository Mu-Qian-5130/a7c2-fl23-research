.syntax unified
.arch armv7-a
.arm
.text
.global _start
.global _arm_start
_start:
_arm_start:
    mrc p15, 0, r0, c0, c0, 5
    ands r0, r0, #255
    bne park
    cps #0x1f
    mov sp, #0x0d000000
    mov r6, #0x0f000000
    ldr r0, =vectors
    mcr p15, 0, r0, c12, c0, 0
    mrc p15, 0, r0, c1, c0, 0
    bic r0, r0, #0x2000
    mcr p15, 0, r0, c1, c0, 0
    isb
    ldr r0, =0x0f001010
    ldr r7, [r0]
    str r7, [r6, #8]
    mrc p15, 0, r0, c14, c0, 0
    str r0, [r6, #36]
    mov r0, #1
    str r0, [r6]
    ldr r9, =0xf1052000
    ldr r10, =0xf1388340
    cmp r7, #3
    bne configure
    mov r0, #1 @ unsupported reset bit must abort, never report success
    str r0, [r10, #4]
    b fail
configure:
    mov r0, #0x40000
    str r0, [r10, #4]
    ldr r1, [r10]
    str r1, [r6, #28]
    str r0, [r10, #8]
    ldr r1, [r10]
    str r1, [r6, #32]
    mov r0, #1
    ldr r1, =0xf13883a0
    str r0, [r1]
    mov r0, #0x22 @ TOP_INIT2 and reload TOP2: 65.536ms at4MHz
    str r0, [r9, #4]
    mov r0, #1
    str r0, [r9]
    mrrc p15, 0, r0, r1, c14
    str r0, [r6, #40]
    mov r0, #2
    str r0, [r6, #4]
    ldr r0, =50000 @25ms under the admitted2MHz generic counter
    bl wait_ticks
    ldr r0, [r9, #8]
    str r0, [r6, #12]
    cmp r7, #1
    moveq r0, #0x76
    streq r0, [r9, #12]
    cmp r7, #2
    moveq r0, #0x75
    streq r0, [r9, #12]
    ldr r0, [r9, #8]
    str r0, [r6, #16]
    mov r0, #3
    str r0, [r6, #4]
    ldr r0, =100000 @50ms: beyond the original deadline, within fed deadline
    bl wait_ticks
    ldr r0, [r9, #8]
    str r0, [r6, #20]
    mrrc p15, 0, r0, r1, c14
    str r0, [r6, #44]
    mov r0, #0x40000
    str r0, [r10, #4] @ real modeled block reset stops the watchdog
    mov r0, #4
    str r0, [r6, #4]
park:
    wfi
    b park
wait_ticks:
    mov r3, r0
    mrrc p15, 0, r0, r1, c14
    mov r2, r0
1:  mrrc p15, 0, r0, r1, c14
    sub r0, r0, r2
    cmp r0, r3
    blo 1b
    bx lr
fail:
    mov r0, #0xbad
    str r0, [r6, #4]
    b park
fault:
    mrc p15, 0, r0, c5, c0, 0
    str r0, [r6, #48]
    mrc p15, 0, r0, c6, c0, 0
    str r0, [r6, #52]
    mov r0, #0xdead
    str r0, [r6, #4]
    b park
.balign 32
vectors:
    b fault
    b fault
    b fault
    b fault
    b fault
    b fault
    b fault
    b fault
.ltorg
