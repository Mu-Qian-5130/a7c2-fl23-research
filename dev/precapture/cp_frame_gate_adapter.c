/* Non-installable target frame-parameter adapter.
 *
 * Replaces only the enable-leaf call inside the ORIGINAL parameter producer.
 * The original producer still stores private+0xd97; the original consumer
 * still reads getter+0xd8f and chooses frame marker 2. No live frame, RAW ID,
 * capture job, debug parameter or cached parameter object is edited here.
 *
 * State must already be initialized and have a proven read lifetime across
 * this producer's task and the serialized control task. That contract and
 * context refresh before cancellation release are not supplied by this file.
 */
#include "cp_backend.h"
typedef __UINTPTR_TYPE__ uptr;
_Static_assert(sizeof(void *) == 4, "Exact target CP ABI requires ARM32");
extern u32 precapture_frame_gate(u32, u32, u32, u32, u32);

u32 precapture_target_frame_gate(const struct precapture_backend_state *state,
                                u32 context_word_10, u32 mode, u32 request_subtype) {
    const volatile u8 *debug = (const volatile u8 *)(uptr)0x1a533a4u;
    u32 (*original)(u32) = (u32 (*)(u32))(uptr)0xb370fbu;
    /* Target request13 bypasses ordinary AP capture bookkeeping. Ordinary
     * request types must retain their original route, even while enabled.
     * Conversely a late request13 must retain the donor-matched decision
     * after disable/fault. That decision still has context/mode guards;
     * this hook alone cannot prove safe admission of every late frame.
     * Generation is never zero after the first accepted control request.
     * This is the message-carried subtype stored by the original producer,
     * not a racy read of the capture arbiter's current request.
     */
    if (!state || request_subtype != 13u ||
        (state->control.enabled != 1u && !state->generation))
        return original(mode);
    /* Preserve the donor context guard for special native prepare contexts. */
    return precapture_frame_gate(context_word_10, mode, 1u,
                                  debug[0xf0], debug[0xf1]);
}

/* Hook only the recording-reference debug-bit read after native subtype13
 * exclusion. Keep original flags and use native start/stop helpers; those
 * helpers own their recording byte and suppress duplicate notifications.
 * Fault/pending transitions may close an already-open native recording,
 * but must never start a new one. No callback is delivered by this predicate.
 */
u32 precapture_target_reference_flags(const struct precapture_backend_state *state,
    u32 original_flags, u32 pressed, u32 native_recording) {
    if (state && ((!state->fault && !state->control.stage && state->control.enabled == 1u) ||
        (!pressed && native_recording &&
         (state->fault || state->control.stage))))
        return original_flags | 1u;
    return original_flags;
}
