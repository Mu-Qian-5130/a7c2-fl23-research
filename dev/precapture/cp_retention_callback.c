/* Native two-argument callback/queue prototypes, with no startup/installer.
 * Frozen arguments are supplied by the original28-byte native callback job.
 */
#include "cp_runtime.h"
#ifndef PRECAPTURE_RUNTIME_ADDRESS
#error "Exact source runtime address required"
#endif
#ifndef PRECAPTURE_RUNTIME_SOURCE_TAG
#error "Exact source runtime source tag required"
#endif
typedef __UINTPTR_TYPE__ uptr;

int precapture_target_retention_enqueue(u32 generation, u32 duration) {
    const volatile u32 *owner = (const volatile u32 *)(uptr)0x1a3aae0u;
    const volatile u32 *binding = (const volatile u32 *)(uptr)0x1a45ca4u;
    int (*enqueue)(const void *, const void *, u32, u32) =
        (int (*)(const void *, const void *, u32, u32))(uptr)0x50ff1du;
    u32 job[5] = {0x805dcdu, 0, 0, 0, 0};
    if (!generation || (duration && (duration < 5 || duration > 1000 || generation == 0xffffffffu)))
        return -22;
    if (*binding != 0x1a3aae0u || owner[5] != 0x88u || owner[6] != 0x38u)
        return -95;
    job[2] = (u32)(uptr)precapture_runtime_retention;
    /* Original callback sender returns1=accepted/0=failed, unlike send/post.
     * It copies all28 bytes; no job points at a mutable setting or stack.
     */
    return enqueue((const void *)owner, job, generation, duration) == 1 ? 0 : -5;
}

int precapture_runtime_retention(u32 generation, u32 duration) {
    struct precapture_runtime *r = precapture_target_runtime_resolve(
        (struct precapture_runtime *)(uptr)PRECAPTURE_RUNTIME_ADDRESS,
        PRECAPTURE_RUNTIME_SOURCE_TAG);
    int (*is_current)(const void *) = (int (*)(const void *))(uptr)0xb435ffu;
    const volatile u32 *owner = (const volatile u32 *)(uptr)0x1a3aae0u;
    int result;
    if (!r)
        return -95;
    if (owner[5] != 0x88u || owner[6] != 0x38u)
        return -95;
    /* Original Task::is_current queries the real RTOS task ID and compares
     * owner+0x14. A caller boolean or an initialized state is insufficient.
     */
    if (!is_current((const void *)(uptr)0x1a3aae0u))
        return -1;
    result = precapture_retention_owner_apply(&r->retention,
        (u32 *)(uptr)0x1a45c70u, generation, duration);
    {
        /* The receiver must match generation, expected duration/enabled and
         * phase BEFORE using this result. Busy/error is not a drained ACK.
         * Configuration can already have taken effect when posting fails:
         * never clear cancellation or claim rollback from the return code.
         */
        u32 packet[8] = {0, 0x8240, generation, 3, duration != 0,
                        0x50435231, result == 1 ? 0u : (u32)result, duration};
        if (r->operations.post((void *)(uptr)0x1a52b34u,
                               0x900302d9u, packet, sizeof(packet)))
            return -5;
    }
    return result == 1 ? 0 : result;
}
