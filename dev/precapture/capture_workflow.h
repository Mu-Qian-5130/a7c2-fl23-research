/* Serialized lifecycle controller. No camera bindings, native calls or storage.
 * The adapter MUST establish source/task/clock/pixel-reference ownership and
 * perform each asynchronous action before supplying its completion. A scalar
 * completion by itself is not native sensor, terminal or restoration evidence.
 * Keep state/adapter/context storage alive while an outcome is unresolved;
 * no timeout permits destroying or reinitializing an uncertain transaction.
 */
#ifndef PRECAPTURE_CAPTURE_WORKFLOW_H
#define PRECAPTURE_CAPTURE_WORKFLOW_H
#include "cp_control_state.h"
typedef __UINT64_TYPE__ wf_tick;
#define WF_CAPACITY 32u
#define WF_MAGIC 0x31464350u
enum wf_phase { WF_IDLE, WF_CONFIGURE, WF_REFRESH, WF_START, WF_BUFFERING,
    WF_STOP, WF_FENCE, WF_DRAIN, WF_RESTORE, WF_REFRESH_RESTORE, WF_DONE,
    WF_UNCERTAIN };
enum wf_action_kind { WF_SET_POLICY=1, WF_REFRESH_ON, WF_START_READOUT,
    WF_STOP_READOUT, WF_TERMINAL_FENCE, WF_SAVE, WF_RELEASE,
    WF_RESTORE_POLICY, WF_REFRESH_BASELINE };
enum wf_outcome { WF_APPLIED=1, WF_UNKNOWN=2 };
enum wf_result { WF_NO_RESULT, WF_SAVED, WF_CANCELLED, WF_NO_PRETRIGGER };
/* Successful SAVE completion must describe this exact owned lease, not a
 * borrowed sibling frame/holder. CONSUMED means durable save AND completed
 * release of that lease, never just accepted native enqueue or zero count.
 */
enum wf_save_reference { WF_REFERENCE_RETAINED, WF_REFERENCE_CONSUMED };
struct wf_frame {
    u32 lease, handle;
    wf_tick begin, end;
};
struct wf_action {
    u32 kind, generation, ticket, lease, handle, value, auxiliary, serial;
    wf_tick trigger;
};
struct wf_completion {
    u32 kind, generation, ticket, outcome, lease, value, auxiliary, serial;
};
struct wf_state {
    u32 magic, generation, phase, ticket;
    u32 duration_ms, capacity, original_policy, original_limit;
    u32 parameter_epoch, issued, pending_slot, triggered;
    u32 cancelled, count, saved, released;
    u32 rejected, last_lease, ingress_serial, terminal_serial;
    u32 result, last_phase, saved_mask, original_flag;
    wf_tick latest, trigger;
    struct wf_action pending;
    struct wf_frame frames[WF_CAPACITY];
};
/* Fresh zero storage only. Epoch comes from the proven adapter clock/context,
 * not a guessed camera address or a claim that native parameters refreshed.
 */
int precapture_workflow_begin(struct wf_state *,u32 generation,u32 duration_ms,
    u32 capacity,u32 original_policy,u32 original_limit,u32 parameter_epoch,
    u32 original_flag);
/* Take the next action exactly once. Return0 while an action is outstanding.
 * A returned action is a request, never proof of enqueue/service completion.
 */
int precapture_workflow_next(struct wf_state *,struct wf_action *);
int precapture_workflow_complete(struct wf_state *,const struct wf_completion *);
/* A caller-owned, already-retained image reference is transferred only on1.
 * Every other result leaves that offered reference with the caller. Full native
 * frame metadata must pass the existing retention admission guard first.
 * begin/end use an independently normalized monotonic native exposure clock;
 * the adapter serializes ingress by exposure-end time and S2 before post-edge
 * ingress. This does not supply a native reorderer or a timestamp getter.
 * Stock frame+b98 is a saved clock latch and +66f4 a separate 32-bit sample;
 * neither store alone certifies exposure end or a normalized 64-bit epoch.
 */
int precapture_workflow_frame(struct wf_state *,u32 generation,u32 serial,
    const struct wf_frame *,const u8 *native_frame);
/* Called at the real S2 reference edge, BEFORE native formal-shoot handling.
 * Ordinary AF/AE/full-press handling must continue through its original path.
 * Releasing S1 after this edge finishes this shot; it cannot cancel its saves.
 */
int precapture_workflow_trigger(struct wf_state *,wf_tick reference);
int precapture_workflow_cancel(struct wf_state *);
/* Reuse only after fully completed restore, with the same qualified native
 * baseline and a strictly newer generation. Never reset an uncertain session.
 */
int precapture_workflow_rearm(struct wf_state *,u32 generation);
_Static_assert(sizeof(struct wf_state)==920,"workflow state ABI");
_Static_assert(sizeof(struct wf_action)==40,"workflow action ABI");
_Static_assert(sizeof(struct wf_completion)==32,"workflow completion ABI");
_Static_assert(sizeof(struct wf_frame)==24,"workflow frame ABI");
#endif
