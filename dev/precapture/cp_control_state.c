/* Independent CP control-state prototype. No target master fields are used.
 *
 * The caller must serialize these operations in the eventual native owner
 * task. This source provides no transport, locking, task hook or allocator.
 * Stages deliberately stop before native release and completion reply.
 */
#include "cp_control_state.h"

static u32 read_word(const u8 *p) {
    return (u32)p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24;
}

/* Stage0=idle; stage1=pending; stage2=committed but native release/ACK absent.
 * No stage2->idle helper is supplied: a real backend completion is required.
 */
int precapture_cp_setting(struct precapture_control *state,
                          const u8 *packet, u32 length) {
    u32 trigger, duration;
    if (!state || !packet || length != 16 || packet[0] != 5 || packet[1] ||
        packet[2] != 0x72 || packet[3] != 0x41)
        return -22;
    trigger = read_word(packet + 8);
    duration = read_word(packet + 12);
    if (trigger > 3 || duration > 1000 ||
        (trigger == 0 ? duration != 0 : duration < 5))
        return -22;
    state->trigger = trigger;
    state->duration_ms = duration;
    return 1;
}

/* origin is obtained from the native message-origin accessor (target file
 * 0xae402a). It is not guessed from the wire header or a fixed queue ID.
 * Accepting a request only records it; enabled remains unchanged.
 */
int precapture_cp_begin(struct precapture_control *state,
                        const u8 *packet, u32 length, u32 origin) {
    u32 enabled;
    if (!state || !packet || length != 12 || packet[0] != 5 || packet[1] ||
        packet[2] != 0x73 || packet[3] != 0x41)
        return -22;
    enabled = read_word(packet + 8);
    if (enabled > 1)
        return -22;
    if (state->stage)
        return -16;
    state->pending_enabled = enabled;
    state->pending_command = 0x4173;
    state->pending_context = read_word(packet + 4);
    state->pending_origin = origin;
    state->stage = 1;
    return 1;
}

/* Native donor/target busy predicates both read context+0xc !=0. The real
 * target owner/context binding and deferred-event adapter remain unbound.
 * A positive result means state committed; it is NOT a completed camera
 * operation or permission to send a success reply before native release.
 */
int precapture_cp_apply_if_idle(struct precapture_control *state,
                                const volatile u32 *native_context) {
    if (!state || !native_context || state->stage != 1)
        return -22;
    if (native_context[3] != 0)
        return -16;
    state->enabled = state->pending_enabled;
    state->stage = 2;
    return 1;
}
