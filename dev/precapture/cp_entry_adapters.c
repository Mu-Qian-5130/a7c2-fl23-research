/* Exact A7C II 2.01 queue/replay adapters, NOT installed hooks.
 * Only the queue entry may inspect an IPC allocation prefix. Deferred replay
 * receives a28-byte stack copy and must never read an allocation prefix.
 * Return0 forwards ordinary events. Nonzero consumes/rejects private input.
 * These adapters do not free an IPC message, dequeue a ring or create state.
 */
#include "cp_backend.h"
typedef __UINTPTR_TYPE__ uptr;
_Static_assert(sizeof(void *) == 4, "Target CP adapters require ARM32");

static u32 word(const u8 *p) {
    return (u32)p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24;
}

int precapture_target_queue_event(struct precapture_backend_state *state,
    const struct precapture_native_operations *ops, const u8 *root,
    const u8 *message) {
    u32 length;
    u32 (*native_size)(const void *) = (u32 (*)(const void *))(uptr)0xbec28fu;
    if (!message || ((uptr)message & 3u))
        return -22;
    /* Native IPC receive pointer only, never a deferred stack-copy pointer.
     * Original file0xae428e and allocation stores are pinned by the audit. */
    length = native_size(message);
    if (length < 4 || length > 0x1000)
        return -22;
    if (word(message) != 0)
        return 0;
    if (length < 8)
        return -22;
    if (word(message + 4) != 0x8240u)
        return 0;
    if ((uptr)root != 0x1a52b38u)
        return -95;
    return precapture_target_task_event(state, ops, root + 0x98,
        (const u32 *)(message + 4), length - 4);
}

int precapture_target_replay_event(struct precapture_backend_state *state,
    const struct precapture_native_operations *ops, const u8 *controller,
    const u32 *event) {
    if (!event || ((uptr)event & 3u))
        return -22;
    if (event[0] != 0x8240u)
        return 0;
    if ((uptr)controller != 0x1a52c14u)
        return -95;
    /* The original pop copied exactly28 bytes. No heap header exists here. */
    return precapture_target_task_event(state, ops,
        (const u8 *)(uptr)0x1a52bd0u, event, 28);
}

/* Invoked only after the original S1 handler commits controller+0x24.
 * Returning nonzero replaces only its pre-capture/debug start/stop decision;
 * the original event's normal postprocessing must still execute. */
int precapture_target_button_event(struct precapture_backend_state *state,
    const struct precapture_native_operations *ops, const u8 *controller) {
    struct precapture_owner_view view;
    int result;
    if (!state || !ops || (uptr)controller != 0x1a52c14u)
        return -22;
    result = precapture_target_bind_owner(&view,
        (const u8 *)(uptr)0x1a52bd0u, (const u8 *)(uptr)0x165a720u,
        (void *)(uptr)0x1a52b34u);
    if (result < 0)
        return result;
    return precapture_backend_buttons(state, ops, &view);
}
