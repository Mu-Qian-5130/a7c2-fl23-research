/* Tagged12-byte query, no worker/installer or live source admission.
 * Use the isolated context's actual ID, not a fixed queue ID.
 * A handoff is not a CP reply. UNKNOWN needs a durable outer process/context
 * hold; no retry/free/close or post-send shared-memory read is permitted here.
 */
#ifndef PRECAPTURE_AP_QUERY_ONCE_H
#define PRECAPTURE_AP_QUERY_ONCE_H
#include "ap_probe_once.h"
#include "precapture_query_wire.h"

enum query_phase { QUERY_ALLOCATING=1,QUERY_READY,QUERY_SENDING,
    QUERY_HANDED_OFF,QUERY_REJECTED,QUERY_UNCERTAIN };
enum query_ownership { QUERY_NONE=0,QUERY_CALLER,QUERY_TRANSPORT,QUERY_UNKNOWN };
struct query_result {
    probe_u32 magic,version,phase,ownership;
    probe_u32 nonce,own_id,allocation_attempts,send_attempts;
    probe_i64 allocation_status,send_status;
    probe_u64 message;
    probe_u32 header_verified,packet_written;
};
/* Returns0 only for transport handoff; all other operation outcomes return-5.
 * Invalid inputs return-22, already-used result-16. Serialized calls only;
 * local one-use state is not a concurrency interlock or durable job fence.
 */
int precapture_query_once(const struct probe_binding *,volatile struct query_result *,
    probe_u32 own_id,probe_u32 nonce,probe_ioctl);
#endif
