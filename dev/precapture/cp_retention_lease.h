#ifndef PRECAPTURE_CP_RETENTION_LEASE_H
#define PRECAPTURE_CP_RETENTION_LEASE_H
#include "cp_control_state.h"

/* Owner-task prototype. Runtime ABI2 reserves and initializes this object;
 * no actual startup hook, callback installation or completed ACK handshake exists.
 * Only the retention task may own this object and its native queue. Duration0
 * means inactive;5..1000 means active, so no separate active flag is needed.
 */
struct precapture_retention_lease {
    u32 generation, saved_policy, saved_limit, duration_ms;
};
_Static_assert(sizeof(struct precapture_retention_lease) == 16, "retention lease");

/* Immutable job arguments: generation is nonzero and never wraps, duration0
 * restores. Return1=owner-local applied/already applied; negative=no change.
 * This return is NOT an ACK delivered to the S1 task or permission to release
 * capture cancellation. Native stop/quiescence and matched ACK remain needed.
 */
int precapture_retention_owner_apply(struct precapture_retention_lease *,
                                     u32 *native_queue, u32 generation, u32 duration_ms);
#endif
