/* Consume one successfully polled status reply. No send, retry or teardown.
 * Requires exact live source/context/queue identity and serialized ownership.
 * Consumes the poll token before inspecting; a released/unknown token cannot
 * be reused with a fresh result. UNKNOWN retains the outer process/context.
 */
#ifndef PRECAPTURE_AP_REPLY_ONCE_H
#define PRECAPTURE_AP_REPLY_ONCE_H
#include "ap_poll_once.h"
#include "precapture_query_wire.h"
enum reply_phase { REPLY_INSPECTING=1,REPLY_VALIDATED,REPLY_RELEASING,REPLY_RELEASED,REPLY_UNCERTAIN };
enum reply_ownership { REPLY_NONE=0,REPLY_CALLER,REPLY_UNKNOWN };
enum reply_kind { REPLY_MATCHED=1,REPLY_UNEXPECTED=2 };
struct reply_result {
    probe_u32 magic,version,phase,ownership;
    probe_u32 own_id,nonce,expected_tag,kind;
    probe_i64 release_status;
    probe_u64 message; /* Observed address only; never read after release. */
    probe_u32 generation,flags,stage,duration_ms;
    probe_u32 release_attempts,reserved,reply_nonce,reply_tag;
};
/*0=matched and released; -84=unexpected owned packet released (query still
 * pending); -5=UNKNOWN; -22=bad input; -16=used result/poll token.
 * A released matched reply is NOT remote quiescence or permission to close.
 */
int precapture_reply_once(const struct probe_binding *,volatile struct poll_result *,
    volatile struct reply_result *,probe_u32 nonce,probe_u32 expected_tag,probe_ioctl);
#endif
