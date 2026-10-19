/* Non-installable empty/idle queue-policy ownership primitive. No allocation,
 * pixel access, native send, task switch or backend cancellation operation.
 * The caller must already be running in the native retention owner task.
 * A mutex or a caller-supplied "owner" boolean cannot establish that contract.
 */
#include "cp_retention_lease.h"
typedef __UINTPTR_TYPE__ uptr;

int precapture_retention_owner_apply(struct precapture_retention_lease *s,
                                     u32 *q, u32 generation, u32 duration) {
    if (!s || !q || ((uptr)s & 3u) || ((uptr)q & 3u) || !generation ||
        (duration && (duration < 5 || duration > 1000 || generation == 0xffffffffu)))
        return -22;
    /* Exact target constructor anchors, not a donor-layout reinterpretation.
     * In particular, count0 by itself is insufficient proof of emptiness.
     */
    if (q[0] != 0xe75730u || q[4] != 0x1a444f4u || q[5] > 1 ||
        (!s->duration_ms && (s->saved_policy || s->saved_limit)) ||
        (s->duration_ms && (!s->generation || s->saved_policy > 1 ||
                      s->duration_ms < 5 || s->duration_ms > 1000)))
        return -22;
    if (q[3] || q[7] || q[1] != (u32)(uptr)(q + 1) ||
        q[2] != (u32)(uptr)(q + 1))
        return -16;
    if (generation < s->generation)
        return -116;
    /* If another flow reconfigured this queue, do not overwrite it, even
     * while restoring. The original saved values remain available to review.
     */
    if (s->duration_ms && (q[5] != 0 || q[6] != s->duration_ms))
        return -116;
    if (generation == s->generation)
        return duration == s->duration_ms ? 1 : -116;

    if (duration) {
        if (!s->duration_ms) {
            s->saved_policy = q[5];
            s->saved_limit = q[6];
        }
        q[5] = 0;
        q[6] = duration;
        s->duration_ms = duration;
    } else if (s->duration_ms) {
        q[5] = s->saved_policy;
        q[6] = s->saved_limit;
        s->saved_policy = 0;
        s->saved_limit = 0;
        s->duration_ms = 0;
    }
    s->generation = generation;
    return 1;
}
