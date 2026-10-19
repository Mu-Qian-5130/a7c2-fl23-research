/* Target entry bindings, still no boot/code-page hook or installer.
 * The original queue is the sole writer of settings/control state. Runtime
 * publication must precede these calls; missing readiness forwards ordinary
 * events and rejects private commands/events without native unsupported dispatch.
 */
#include "cp_runtime.h"
typedef __UINTPTR_TYPE__ uptr;

int precapture_runtime_queue(struct precapture_runtime *r, u32 tag,
                             const u8 *root, const u8 *message) {
    struct precapture_owner_view view;
    u32 bytes, command, origin;
    u32 (*native_size)(const void *) = (u32 (*)(const void *))(uptr)0xbec28fu;
    u32 (*native_origin)(const void *) = (u32 (*)(const void *))(uptr)0xbec02bu;
    int result;
    r = precapture_target_runtime_resolve(r, tag);
    if (!message || ((uptr)message & 3u))
        return -22;
    bytes = native_size(message);
    if (bytes < 4 || bytes > 0x1000)
        return -22;
    command = (u32)message[2] | (u32)message[3] << 8;
    if (message[0] != 5 || (command != 0x4172 && command != 0x4173))
        return precapture_target_queue_event(r ? &r->state : 0,
            r ? &r->operations : 0, root, message);
    /* Known private wire requests must never reach the stock command table. */
    if (message[1])
        return -22;
    if (!r || (uptr)root != 0x1a52b38u)
        return -95;
    if (bytes != (command == 0x4172 ? 16u : 12u))
        return -22;
    result = precapture_target_bind_owner(&view, root + 0x98,
        (const u8 *)(uptr)0x165a720u, (void *)(uptr)0x1a52b34u);
    if (result < 0)
        return result;
    if (command == 0x4172) {
        /* Reconfigure only while fully disabled. Disable/configure/enable is
         * explicit: changing trigger/duration in a live retention transaction
         * needs an additional native transition, not naked multiword stores.
         */
        if (r->state.fault || r->state.control.enabled || r->state.requested ||
            r->state.cancel_sent || r->state.control.stage)
            return -16;
        return precapture_cp_setting(&r->state.control, message, bytes);
    }
    /* A disabled trigger cannot arm frame routing without a start source. */
    if (message[8] && (!r->state.control.trigger || r->state.control.trigger > 3 ||
        r->state.control.duration_ms < 5 || r->state.control.duration_ms > 1000))
        return -22;
    origin = native_origin(message); /* Actual IPC allocation prefix only. */
    return precapture_backend_begin(&r->state, &r->operations,
                                    view.message_owner, message, bytes, origin);
}

int precapture_runtime_replay(struct precapture_runtime *r, u32 tag,
                              const u8 *controller, const u32 *event) {
    r = precapture_target_runtime_resolve(r, tag);
    return precapture_target_replay_event(r ? &r->state : 0,
        r ? &r->operations : 0, controller, event);
}

int precapture_runtime_button(struct precapture_runtime *r, u32 tag, const u8 *controller) {
    r = precapture_target_runtime_resolve(r, tag);
    if (!r)
        return 0;
    return precapture_target_button_event(&r->state, &r->operations, controller);
}

u32 precapture_runtime_frame(struct precapture_runtime *r, u32 tag, u32 context, u32 mode,
                             u32 subtype) {
    r = precapture_target_runtime_resolve(r, tag);
    return precapture_target_frame_gate(r ? &r->state : 0, context, mode, subtype);
}

u32 precapture_runtime_reference(struct precapture_runtime *r, u32 tag,
                                u32 flags, u32 pressed, u32 recording) {
    r = precapture_target_runtime_resolve(r, tag);
    return precapture_target_reference_flags(r ? &r->state : 0, flags, pressed, recording);
}
