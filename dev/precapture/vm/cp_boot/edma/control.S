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
    mov r4, #0x0d000000
    cps #0x12
    add sp, r4, #0x8000
    cps #0x1f
    mov sp, r4
    mov r6, #0x0f000000
    ldr r0, =vectors
    mcr p15, 0, r0, c12, c0, 0
    mrc p15, 0, r0, c1, c0, 0
    bic r0, r0, #0x2000
    mcr p15, 0, r0, c1, c0, 0
    isb
    ldr r0, =0x0f001010
    ldr r7, [r0]
    str r7, [r6, #60]
    mov r0, #1
    str r0, [r6]
    mov r11, #0
    cmp r7, #1
    moveq r11, #1
    ldr r8, =0xf6780000
    mov r9, #0x05000000
    mov r10, #0x40000000
    add r10, r10, #0x1000
    cmp r7, #1
    moveq r0, r9
    moveq r9, r10
    moveq r10, r0
    cmp r7, #3
    ldreq r10, =0x400ffff8
    mov r0, #0
fill_source:
    eor r1, r0, #0x5a
    strb r1, [r9, r0]
    add r0, r0, #1
    cmp r0, #512
    blo fill_source
    cmp r7, #2
    beq configure
    mov r0, #0xa5
    strb r0, [r10, #-1]
    mov r2, #512
    cmp r7, #3
    moveq r2, #8
    mov r1, #0
fill_destination:
    strb r0, [r10, r1]
    add r1, r1, #1
    cmp r1, r2
    blo fill_destination
    cmp r7, #3
    strbne r0, [r10, r2]
configure:
    ldr r4, =0xf13a1000
    ldr r5, =0xf13a2000
    mov r0, #0
    str r0, [r4, #0xb0] @ SPI403 group0
    mov r0, #0x80000
    str r0, [r4, #0x130]
    mov r0, #1
    strb r0, [r4, #0x993]
    str r0, [r4]
    str r0, [r5]
    mov r0, #255
    str r0, [r5, #4]
    ldr r1, =0xf11e0274
    ldr r0, =0xffff
    str r0, [r1]
    mov r0, #1
    cmp r11, #0
    streq r0, [r8, #0xc]
    strne r0, [r8, #0x2c]
    streq r0, [r8, #0x128]
    strne r0, [r8, #0x168]
    mov r0, #0
    cmp r7, #4
    mvneq r0, #0
    cmp r11, #0
    streq r0, [r8, #0x54]
    strne r0, [r8, #0xa8]
    add r4, r8, #0x200
    cmp r11, #1
    addeq r4, r4, #0x100
    mov r0, #8
    str r0, [r4]
    mov r0, #512
    cmp r7, #3
    moveq r0, #16
    str r0, [r4, #8]
    cmp r11, #0
    beq write_addresses
    mov r0, #0x1000
    str r0, [r4, #12]
    mov r0, #4
    str r0, [r4, #16]
    mov r0, #0x05000000
    str r0, [r4, #20]
    mov r0, #0
    str r0, [r4, #24]
    b start
write_addresses:
    str r9, [r4, #12]
    mov r0, #0
    str r0, [r4, #16]
    mov r0, #0x1000
    cmp r7, #3
    ldreq r0, =0xffff8
    str r0, [r4, #20]
    mov r0, #4
    str r0, [r4, #24]
start:
    dsb sy
    cpsie i
    mov r0, #0
    cmp r11, #0
    streq r0, [r8, #0x10]
    strne r0, [r8, #0x30]
    cmp r7, #2
    beq absent
    cmp r7, #4
    bne await_irq
    bl wait_window
    ldr r0, [r6, #8]
    str r0, [r6, #32]
    ldr r0, [r8, #0x4c]
    str r0, [r6, #36]
    mov r0, #0
    str r0, [r8, #0x54]
await_irq:
    cpsid i
    ldr r0, [r6, #8]
    cmp r0, #0
    bne verify
    wfi
    cpsie i
    b await_irq
verify:
    cpsie i
    ldr r0, [r4]
    str r0, [r6, #24]
    ldr r0, [r4, #8]
    str r0, [r6, #28]
    mov r2, #512
    cmp r7, #3
    moveq r2, #8
    mov r0, #0
verify_bytes:
    ldrb r1, [r10, r0]
    eor r3, r0, #0x5a
    and r3, r3, #255
    cmp r1, r3
    bne fail
    add r0, r0, #1
    cmp r0, r2
    blo verify_bytes
    str r0, [r6, #40]
    ldrb r0, [r10, #-1]
    cmp r0, #0xa5
    bne fail
    cmp r7, #3
    beq done
    ldrb r0, [r10, r2]
    cmp r0, #0xa5
    bne fail
done:
    mov r0, #4
    str r0, [r6, #4]
    b park
absent:
    bl wait_window
    ldr r0, [r8, #0x4c]
    str r0, [r6, #16]
    ldr r0, [r4]
    str r0, [r6, #24]
    ldr r0, [r4, #8]
    str r0, [r6, #28]
    mov r0, #2 @ tested retained RUN, not a completed DMA
    str r0, [r6, #4]
park:
    wfi
    b park
wait_window:
    movw r3, #5000
    mrrc p15, 0, r0, r1, c14
    mov r2, r0
    str r0, [r6, #44]
1:  mrrc p15, 0, r0, r1, c14
    sub r1, r0, r2
    cmp r1, r3
    blo 1b
    str r0, [r6, #48]
    bx lr
fail:
    mov r0, #0xbad
    str r0, [r6, #4]
    b park
fault:
    mrc p15, 0, r0, c5, c0, 0
    str r0, [r6, #52]
    mrc p15, 0, r0, c6, c0, 0
    str r0, [r6, #56]
    mov r0, #0xdead
    str r0, [r6, #4]
    b park
irq:
    sub lr, lr, #4
    push {r0-r5,r12,lr}
    ldr r0, =0xf13a2000
    ldr r1, [r0, #12]
    str r1, [r6, #12]
    cmp r11, #0
    ldreq r2, [r8, #0x4c]
    ldrne r2, [r8, #0xa0]
    str r2, [r6, #16]
    add r3, r8, #0x200
    cmp r11, #1
    addeq r3, r3, #0x100
    ldr r4, [r3]
    bic r4, r4, #8
    str r4, [r3]
    cmp r11, #0
    streq r2, [r8, #0x58]
    strne r2, [r8, #0xac]
    ldreq r2, [r8, #0x4c]
    ldrne r2, [r8, #0xa0]
    str r2, [r6, #20]
    str r1, [r0, #16]
    dsb sy
    ldr r0, [r6, #8]
    add r0, r0, #1
    str r0, [r6, #8]
    ldmia sp!, {r0-r5,r12,pc}^
.balign 32
vectors:
    b fault
    b fault
    b fault
    b fault
    b fault
    b fault
    b irq
    b fault
.ltorg
