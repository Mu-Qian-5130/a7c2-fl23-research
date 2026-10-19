/* Exact target entry thunks for OFFLINE linking/execution. No startup hook
 * makes their page executable/loaded, so this file is NOT camera-installable.
 * Keep native free, admission, AF/AE processing and parameter stores intact.
 */
#ifndef PRECAPTURE_RUNTIME_ADDRESS
#error "Exact source runtime address required"
#endif
#ifndef PRECAPTURE_RUNTIME_SOURCE_TAG
#error "Exact source runtime tag required"
#endif
.syntax unified
.thumb
.text
.macro runtime_args
    ldr r0,=PRECAPTURE_RUNTIME_ADDRESS
    ldr r1,=PRECAPTURE_RUNTIME_SOURCE_TAG
.endm

.global precapture_hook_queue
.type precapture_hook_queue,%function
.thumb_func
precapture_hook_queue:
    push {r4,r5,r6,lr}
    mov r4,r0
    mov r5,r1
    mov r2,r0
    mov r3,r1
    runtime_args
    bl precapture_runtime_queue
    cmp r0,#0
    beq 1f
    pop {r4,r5,r6,pc}
1:
    mov r0,r4
    mov r1,r5
    pop {r4,r5,r6,lr}
    ldr r12,=0x4b3e91
    bx r12
.size precapture_hook_queue,.-precapture_hook_queue

.global precapture_hook_replay
.type precapture_hook_replay,%function
.thumb_func
precapture_hook_replay:
    push {r0,r1,r2,r3,r12,lr}
    mrs r12,apsr
    push {r12,lr}
    mov r3,r1
    mov r2,r8
    runtime_args
    bl precapture_runtime_replay
    cmp r0,#0
    bne 2f
    pop {r12,lr}
    msr APSR_nzcvq,r12
    pop {r0,r1,r2,r3,r12,lr}
    ldr.w r0,[r8]
    ldr pc,=0xb20127
2:
    pop {r12,lr}
    msr APSR_nzcvq,r12
    pop {r0,r1,r2,r3,r12,lr}
    ldr pc,=0xb2014f
.size precapture_hook_replay,.-precapture_hook_replay

.global precapture_hook_button
.type precapture_hook_button,%function
.thumb_func
precapture_hook_button:
    push {r0,r1,r2,r3,r12,lr}
    mrs r12,apsr
    push {r12,lr}
    mov r2,r5
    runtime_args
    bl precapture_runtime_button
    cmp r0,#0
    bne 3f
    pop {r12,lr}
    msr APSR_nzcvq,r12
    pop {r0,r1,r2,r3,r12,lr}
    ldrb.w r2,[r10,#0xf1]
    ldr pc,=0x4b5309
3:
    pop {r12,lr}
    msr APSR_nzcvq,r12
    pop {r0,r1,r2,r3,r12,lr}
    ldr pc,=0x4b55ef
.size precapture_hook_button,.-precapture_hook_button

.global precapture_hook_frame
.type precapture_hook_frame,%function
.thumb_func
precapture_hook_frame:
    push {r1,r2,r3,r4,r12,lr}
    mov r3,r0
    ldr r2,[r4,#0x10]
    runtime_args
    bl precapture_runtime_frame
    pop {r1,r2,r3,r4,r12,lr}
    bx lr
.size precapture_hook_frame,.-precapture_hook_frame

.global precapture_hook_reference
.type precapture_hook_reference,%function
.thumb_func
precapture_hook_reference:
    push {r1,r2,r3,r4,r12,lr}
    sub sp,#8
    ldrb.w r2,[r0,#0xf1]
    mov r3,r6
    ldr r0,[r5,#0xc]
    ldrb r0,[r0,#0x2d]
    str r0,[sp]
    runtime_args
    bl precapture_runtime_reference
    add sp,#8
    pop {r1,r2,r3,r4,r12,lr}
    ldr pc,=0x4b555f
.size precapture_hook_reference,.-precapture_hook_reference
