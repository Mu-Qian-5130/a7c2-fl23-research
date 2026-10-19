/* Exact-layout, read-only adapter for the original A7C II 2.01 owner.
 * Not a task hook or installation. Caller must already have verified the
 * complete program and supply real native getter/hook arguments. Ordinary
 * wire input must never be used as a pointer. No OS operation is issued.
 */
#include "cp_backend.h"
typedef __UINTPTR_TYPE__ uptr;

static u32 value(const u8 *p) {
    return (u32)p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24;
}

int precapture_target_bind_owner(struct precapture_owner_view *out,
    const u8 *manager, const u8 *master, void *message_owner) {
    uptr at = (uptr)manager, output = (uptr)out, root;
    const u8 *controller, *context;
    if (!out || !master || !message_owner || at < 0x98 || at > 0xfffff000u ||
        ((at | output | (uptr)master | (uptr)message_owner) & 3u))
        return -22;
    root = at - 0x98;
    /* Exclude output aliases before performing any output write. */
    if (output < root + 0x5e0 && output + sizeof(*out) > root)
        return -22;
    if (value(manager) != 0xe77a94u || value(manager + 4) != root + 0xac ||
        value(manager + 8) != root + 0xdc || value(manager + 12) != root + 0x108 ||
        value(manager + 16) != root + 0x34)
        return -95;
    controller = (const u8 *)(root + 0xdc);
    context = (const u8 *)(root + 0x108);
    if (value(controller) != 0xe77b40u || value(controller + 4) != root + 0x398 ||
        value(controller + 8) != root + 0x34 || value(controller + 12) != (uptr)context ||
        value(controller + 0x1c) != root + 0xac || value(context) != 0xe77f08u)
        return -95;
    out->master = master;
    out->context = (const volatile u32 *)context;
    out->controller = controller;
    out->deferred_ring = (void *)(root + 0x398);
    out->message_owner = message_owner;
    return 1;
}
