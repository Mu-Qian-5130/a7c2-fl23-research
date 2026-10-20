/* Offline AP component. No worker, source binding, installer or live entry.
 * A private adapter must verify actual process/module/fd/shared-map identity.
 * The operation count is bounded; kernel-call wall time is NOT established.
 */
#ifndef PRECAPTURE_AP_PROBE_ONCE_H
#define PRECAPTURE_AP_PROBE_ONCE_H
typedef unsigned char probe_u8;
typedef unsigned int probe_u32;
typedef int probe_i32;
typedef unsigned long long probe_u64;
typedef long long probe_i64;
typedef __UINTPTR_TYPE__ probe_uptr;

struct probe_binding {
    probe_i32 descriptor;
    probe_u32 reserved;
    probe_u64 shared_begin;
    probe_u64 shared_bytes;
};
enum probe_phase {
    PROBE_ALLOCATING=1, PROBE_ALLOCATED, PROBE_SENDING, PROBE_HANDED_OFF,
    PROBE_RELEASING, PROBE_RELEASED, PROBE_REJECTED, PROBE_UNCERTAIN
};
enum probe_ownership { PROBE_NONE, PROBE_CALLER, PROBE_REMOTE, PROBE_UNKNOWN };
struct probe_result {
    probe_u32 magic, version, phase, ownership;
    probe_u32 send_query, nonce, allocation_attempts, send_attempts;
    probe_u32 release_attempts, reserved;
    probe_i64 allocation_status, send_status, release_status;
    probe_u64 message; /* observed address, NEVER dereference after send/free */
};
typedef probe_i64 (*probe_ioctl)(probe_i32, probe_u64, void *);
/* send_query0 allocates/cancels. The legacy send_query1 is retired and
 * returns-95 without allocation; its16-byte packet configures the new CP
 * runtime. Use ap_query_once for the distinct tagged read-only request.
 * A zeroed result is consumed once. No reset API or retry exists.
 * Caller serialization is REQUIRED; this is not atomic/thread-safe state.
 * This is local one-shot state, NOT durable host job deduplication.
 */
int precapture_probe_once(const struct probe_binding *, volatile struct probe_result *,
                         probe_u32 nonce, probe_u32 send_query, probe_ioctl);
probe_i64 precapture_probe_native_ioctl(probe_i32, probe_u64, void *);
#endif
