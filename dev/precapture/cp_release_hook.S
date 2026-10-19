/* Emulator-only CAP receive-loop adapter. No loader or installer places it.
 * Ordinary commands execute the displaced native origin getter. Consumed
 * private input reaches the original free tail exactly once. No free is
 * performed here. Preserve caller registers, APSR and stack ownership.
 */
.syntax unified
.thumb
.text
.global precapture_hook_release
.type precapture_hook_release,%function
.thumb_func
precapture_hook_release:
    push {r0,r1,r2,r3,r12,lr}
    mrs r12,apsr
    push {r12,lr}
    bl precapture_release_native_message
/* Explicit after-handler test slice. It is not an OS-success substitute. */
.global precapture_release_hook_after
.type precapture_release_hook_after,%function
.thumb_func
precapture_release_hook_after:
    cmp r0,#0
    bne 1f
    pop {r12,lr}
    msr APSR_nzcvq,r12
    pop {r0,r1,r2,r3,r12,lr}
    ldr pc,=0xbec02b
1:
    pop {r12,lr}
    msr APSR_nzcvq,r12
    pop {r0,r1,r2,r3,r12,lr}
    ldr pc,=0x459385
.size precapture_release_hook_after,.-precapture_release_hook_after
.size precapture_hook_release,.-precapture_hook_release
