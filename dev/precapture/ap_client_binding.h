/* Isolated AArch64 Linux child ONLY. This binds the caller's own scheduling
 * context; it does not qualify a live worker, loaded code or CP transaction.
 */
#ifndef PRECAPTURE_AP_CLIENT_BINDING_H
#define PRECAPTURE_AP_CLIENT_BINDING_H
#include "ap_probe_once.h"
#include "ap_linux_aarch64.h"
enum client_binding_phase { CLIENT_INSPECT=1,CLIENT_BLOCK_SIGNALS,CLIENT_BIND_CPU,
    CLIENT_BOUND,CLIENT_RESTORE_CPU,CLIENT_RESTORE_SIGNALS,CLIENT_RESTORED,
    CLIENT_REJECTED,CLIENT_UNKNOWN };
enum client_binding_owner { CLIENT_NO_CHANGES=0,CLIENT_SIGNALS_CHANGED=1,CLIENT_CPU_CHANGED=2 };
struct client_binding_result {
    probe_u32 magic,version,phase,ownership;
    probe_u32 expected_parent,selected_CPU,enter_calls,leave_calls;
    probe_i64 pid,parent,policy_before,priority_before,policy_after,priority_after;
    probe_u64 affinity_before,affinity_after,affinity_restored;
    probe_u64 signals_before,signals_after,signals_restored;
    probe_u32 observed_CPU,reserved;
    probe_i64 last_result,enter_status,leave_status;
};
int precapture_client_bind_once(volatile struct client_binding_result *,probe_u32 expected_parent,
    probe_u32 selected_CPU,ap_a64_syscall);
/* Caller must independently prove all native work/context ownership resolved.
 * This function cannot establish that proof and never frees a native context.
 */
int precapture_client_unbind_once(volatile struct client_binding_result *,ap_a64_syscall);
#endif
