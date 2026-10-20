/* Offline component: receive from the isolated child's newly owned queue.
 * The caller must prove source/device/context identity and queue ownership.
 * No message is sent, inspected, freed, or retried by this component.
 * An UNKNOWN outcome requires retaining the context/process, not exiting.
 * Call serially with private nonoverlapping binding/result storage. A fresh
 * result is not a concurrency interlock or a durable job fence.
 */
#ifndef PRECAPTURE_AP_POLL_ONCE_H
#define PRECAPTURE_AP_POLL_ONCE_H
#include "ap_probe_once.h"

enum poll_phase { POLL_WAITING=1, POLL_EMPTY=2, POLL_RETURNED=3, POLL_UNCERTAIN=4,
    POLL_INSPECTING=5,POLL_RELEASED=6 };
enum poll_ownership { POLL_NONE=0, POLL_CALLER=1, POLL_UNKNOWN=2 };
struct poll_result {
    probe_u32 magic,version,phase,consumed;
    probe_u32 own_id,reserved;
    probe_i64 status;
    probe_u64 message; /* Opaque after inspection/release/UNKNOWN; no later read. */
    probe_u32 attempts,ownership;
};

/* Returns1 for an empty queue,0 for a structurally mapped returned pointer,
 * -5 for UNKNOWN, -22 for invalid binding, -16 for an already used result.
 * A returned pointer still needs original-header/extent/protocol validation
 * before dereference or release. This is not a live channel admission.
 */
int precapture_poll_once(const struct probe_binding *,volatile struct poll_result *,
                         probe_u32 own_id,probe_ioctl);
#endif
