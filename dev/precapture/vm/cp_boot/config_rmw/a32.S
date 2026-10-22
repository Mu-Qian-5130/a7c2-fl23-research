// f5408038 is ordinary test RAM here. Never use this board for native boot.
.syntax unified
.arch armv7-a
.arm
.text
.global _start
_start:
    ldr sp, =0x0d000000
    ldr r6, =0x0f000000
    ldr r4, =0x0f002000
    ldr r8, [r6, #128]
    mov r9, #0
next:
    ldr r2, =0xf5408038
    ldr r0, [r4]
    str r0, [r2]
    ldr r0, [r4, #4]
    ldr r1, [r4, #8]
    ldr r5, =0x89abcdef
    ldr r7, =0x13579bdf
    ldr r3, =0xb74731
    blx r3
    str r0, [r4, #16]
    ldr r1, =0x1a764f4
    ldr r1, [r1]
    str r1, [r4, #20]
    ldr r2, [r4, #12]
    cmp r0, r2
    bne failed
    cmp r1, r2
    bne failed
    ldr r0, =0xf5408038
    ldr r0, [r0]
    cmp r0, r2
    bne failed
    ldr r0, =0x89abcdef
    cmp r5, r0
    bne failed
    ldr r0, =0x13579bdf
    cmp r7, r0
    bne failed
    ldr r0, =0x0d000000
    cmp sp, r0
    bne failed
    add r9, r9, #1
    str r9, [r6, #4]
    add r4, r4, #24
    cmp r9, r8
    blo next
    mov r0, #1
    str r0, [r6]
park:
    dsb sy
    wfi
    b park
failed:
    mov r0, #2
    str r0, [r6]
    b park
