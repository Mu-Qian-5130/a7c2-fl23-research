/* Non-installable target-native backend prototype.
 *
 * Uses checked native send/post helpers instead of unchecked request
 * constructors. Requires a future S1-owner event interceptor, independent
 * initialized48-byte state, exact instruction bindings and executable
 * placement. None is installed by this source. No constructor exists.
 *
 * Proposed private event0x8240 is NOT an existing supported native event.
 * Native routing rejects it without the as-yet-uninstalled interceptor.
 * Tests stop at native boundaries and never fake successful OS delivery.
 */
#include "cp_backend.h"
#if PRECAPTURE_RELEASE_OBSERVER
#include "cp_release_observer.h"
#endif
extern u32 precapture_target_s1_active(u32, u32, const u8 *, u32, u32, u32);
#define EVENT 0x8240u
#define COOKIE 0x50435231u
#define FAULT_PHASE PRECAPTURE_FAULT

static u32 read_word(const u8 *p) {
    return (u32)p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24;
}
static void word(u8 *p, u32 v) {
    p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24;
}

int precapture_backend_query(const struct precapture_backend_state *s,
    const struct precapture_native_operations *ops,u32 source_tag,
    const u8 *packet,u32 length,u32 origin) {
    u8 response[32] = {1,0,0x72,0x41};
    u32 flags;
    if (!s || !ops || !ops->reply || !source_tag || !packet || length != 12 ||
        packet[0] != 5 || packet[1] || packet[2] != 0x72 || packet[3] != 0x41 ||
        !read_word(packet+4) || read_word(packet+8) != PRECAPTURE_QUERY_REQUEST_MAGIC ||
        (origin & 0xffff8000u) != 0x803f0000u || !(origin & 0x7fffu))
        return -22;
    if (s->control.enabled > 1 || s->requested > 1 || s->cancel_sent > 1 ||
        s->fault > 1 || s->control.pending_enabled > 1 || s->control.stage > 7 ||
        s->control.trigger > 3 || s->control.duration_ms > 1000 ||
        (s->control.trigger ? s->control.duration_ms < 5 : s->control.duration_ms != 0))
        return -84;
    flags = s->control.enabled | s->requested << 1 | s->cancel_sent << 2 |
        s->fault << 3 | s->control.pending_enabled << 4 | s->control.trigger << 8;
    word(response+4,read_word(packet+4));
    word(response+8,PRECAPTURE_QUERY_REPLY_MAGIC);
    word(response+12,source_tag);
    word(response+16,s->generation);
    word(response+20,flags);
    word(response+24,s->control.stage);
    word(response+28,s->control.duration_ms);
    /* Error/ambiguous delivery does not rewrite the observed transaction.
     * Remote lifetime and recovery still belong to the future live adapter.
     */
    return ops->reply(response,sizeof(response),origin) ? -5 : 1;
}

/* Native checked sender returns0 after successful enqueue, -1 on failure.
 * A queued request is not evidence that the sensor performed an operation.
 */
int precapture_native_request(const struct precapture_native_operations *ops, u32 command, u32 value) {
    u8 packet[16] = {5, 0, 0, 0};
    if (!ops || !ops->send || (command != 0x4038 && command != 0x4039 && command != 0x403d) ||
        (command == 0x403d ? value > 1 : value != 0))
        return -22;
    packet[2] = command; packet[3] = command >> 8;
    if (command == 0x403d) {
        word(packet + 8, 4); /* same cancel reason used by donor change flow */
        packet[12] = value;
    } else {
        packet[8] = 13; /* original native pre-capture request subtype */
    }
    return ops->send(packet, sizeof(packet), 0x90040193u);
}

#if PRECAPTURE_RELEASE_OBSERVER
int precapture_native_stop_query(const struct precapture_native_operations *ops,
                                 u32 generation, u32 desired) {
    u8 packet[16];
    if (!ops || !ops->send ||
        precapture_release_query_build(generation, desired, packet, sizeof(packet)) != 16)
        return -22;
    return ops->send(packet, sizeof(packet), 0x90040193u);
}

int precapture_backend_query_after_stop(struct precapture_backend_state *s,
                                        const struct precapture_native_operations *ops) {
    if (!s || !ops || !ops->send || s->fault || s->control.stage != PRECAPTURE_PREPARE ||
        s->cancel_sent != 1 || s->requested || !s->generation ||
        s->control.pending_enabled > 1 ||
        (s->control.pending_enabled && s->generation == 0xffffffffu))
        return -22;
    s->control.stage = PRECAPTURE_WAIT_RELEASE_OWNER;
    return precapture_native_stop_query(ops,s->generation,s->control.pending_enabled);
}
#endif

static int post(struct precapture_backend_state *s, const struct precapture_native_operations *ops,
                 void *owner, u32 phase) {
    u32 packet[8] = {0, EVENT, 0, 0, 0, COOKIE, 0, 0};
    packet[2] = s->generation;
    packet[3] = phase;
    packet[4] = s->control.pending_enabled;
    return ops->post(owner, 0x900302d9u, packet, sizeof(packet));
}

static int complete(struct precapture_backend_state *s, const struct precapture_native_operations *ops, u32 status) {
    u8 packet[12] = {1, 0, 0, 0};
    u32 command = s->control.pending_command;
    packet[2] = command; packet[3] = command >> 8;
    word(packet + 4, s->control.pending_context);
    word(packet + 8, status);
    if (ops->reply(packet, sizeof(packet), s->control.pending_origin)) {
        s->fault = 1;
        s->control.stage = FAULT_PHASE;
        return -5; /* unknown receiver outcome: do not retry */
    }
    s->control.stage = s->fault ? FAULT_PHASE : 0;
    return status == 0xf000 ? 1 : -5;
}

static int fail(struct precapture_backend_state *s, const struct precapture_native_operations *ops) {
    /* An accepted cancellation must not be released as generic cleanup.
     * A submitted request13 can still be active or have late frames, even
     * after a successful stop enqueue. Until a future owner/quiescence ACK
     * proves cleanup, retain cancellation and fault without claiming rollback.
     * This prototype has no such recovery transport and is not installable.
     */
    s->fault = 1;
    if (s->cancel_sent) {
        s->control.stage = FAULT_PHASE;
        return -5;
    }
    return complete(s, ops, 0xf001);
}

int precapture_backend_begin(struct precapture_backend_state *s, const struct precapture_native_operations *ops,
                             void *owner, const u8 *packet, u32 length, u32 origin) {
    int result;
    if (!s || !ops || !ops->send || !ops->post || !ops->defer || !ops->reply || !owner || s->fault)
        return -22;
    if (((origin >> 16) & 0xfffu) == 0xbfu || ((origin >> 16) & 0xfffu) == 0xdcu)
        return -22; /* native reply sender intentionally drops these domains */
    /* Never reuse a generation. Reserve the last one for disable/restore. */
    if (s->generation == 0xffffffffu || (s->generation == 0xfffffffeu &&
        packet && length == 12 && read_word(packet + 8) == 1u))
        return -75;
    result = precapture_cp_begin(&s->control, packet, length, origin);
    if (result < 0)
        return result;
    ++s->generation;
    if (post(s, ops, owner, 1))
        return fail(s, ops);
    return 1; /* request pending; actual native completion is still required */
}

int precapture_backend_event(struct precapture_backend_state *s, const struct precapture_native_operations *ops,
                             const struct precapture_owner_view *owner, const u32 *event) {
    u32 want, buttons, phase;
    if (!s || !ops || !owner || !event || !owner->master || !owner->context ||
        !owner->controller || !owner->deferred_ring || !owner->message_owner ||
        !ops->send || !ops->post || !ops->defer || !ops->reply)
        return -22;
    if (event[0] != EVENT || event[4] != COOKIE)
        return 0; /* normal native message: caller must forward unchanged */
    if (s->fault || (s->control.stage != PRECAPTURE_PREPARE &&
#if PRECAPTURE_RELEASE_OBSERVER
        s->control.stage != PRECAPTURE_WAIT_RELEASE_OWNER &&
#endif
        (s->control.stage < PRECAPTURE_WAIT_IDLE || s->control.stage > PRECAPTURE_OWNER_READY)) ||
        event[1] != s->generation ||
        event[3] != s->control.pending_enabled)
        return 1; /* stale request; never modify unrelated native state */
    phase = event[2];
    if (phase < 1 || phase > (PRECAPTURE_RELEASE_OBSERVER ? 5u : 4u))
        return fail(s, ops);
    if (s->control.stage != (phase == 1 ? PRECAPTURE_PREPARE :
            phase == 2 ? PRECAPTURE_WAIT_IDLE :
            phase == 3 ? PRECAPTURE_WAIT_OWNER :
            phase == 5 ? PRECAPTURE_WAIT_RELEASE_OWNER : PRECAPTURE_OWNER_READY))
        return 1; /* duplicate or out-of-order phase; no release or ACK */
    if (phase == 3 && event[6] != (s->control.pending_enabled ? s->control.duration_ms : 0))
        return 1;
    if (phase == 3 && event[5])
        return fail(s, ops); /* busy/error never grants cancellation release */
#if PRECAPTURE_RELEASE_OBSERVER
    if (phase == 5 && (event[5] || !(event[6] & 4u)))
        return fail(s, ops); /* Observation error/lost cancellation is not readiness. */
#endif
    if (owner->context[3] && (phase != 1 || !s->requested)) {
        if (ops->defer(owner->deferred_ring, event))
            return fail(s, ops);
        return 1;
    }
    if (phase == 1) {
        if (s->cancel_sent)
            return 1; /* duplicate prep must not issue another cancellation */
        if (precapture_native_request(ops, 0x403d, 1))
            return fail(s, ops);
        s->cancel_sent = 1;
        /* Stop an old request before asking the retention owner to configure.
         * Starting a new request before its empty/idle ACK is unsafe.
         */
        if (s->requested) {
            if (precapture_native_request(ops, 0x4039, 0))
                return fail(s, ops);
            s->requested = 0;
        }
#if PRECAPTURE_RELEASE_OBSERVER
        /* Same native recipient as cancel/stop. The actor observes its real
         * fields before S1 proceeds; this is NOT a terminal-frame fence.
         */
        if (precapture_backend_query_after_stop(s, ops))
#else
        s->control.stage = PRECAPTURE_WAIT_IDLE;
        if (post(s, ops, owner->message_owner, 2))
#endif
            return fail(s, ops);
        return 1;
    }
    if (!s->cancel_sent)
        return fail(s, ops);
#if PRECAPTURE_RELEASE_OBSERVER
    if (phase == 5) {
        if (s->requested)
            return fail(s, ops);
        s->control.stage = PRECAPTURE_WAIT_IDLE;
        if (post(s, ops, owner->message_owner, 2))
            return fail(s, ops);
        return 1;
    }
#endif
    if (phase == 2) {
        if (s->requested)
            return fail(s, ops);
        s->control.stage = PRECAPTURE_WAIT_OWNER;
        return PRECAPTURE_NEED_OWNER;
    }
    if (phase == 3) {
        s->control.stage = PRECAPTURE_OWNER_READY;
        if (post(s, ops, owner->message_owner, 4))
            return fail(s, ops);
        return 1;
    }
    /* Only a matched owner result reaches this phase. Buttons may change
     * during either native wait; reconcile then queue another idle check.
     */
    buttons = read_word(owner->controller + 0x24);
    want = precapture_target_s1_active(s->control.pending_enabled, s->control.trigger,
                                      owner->master, buttons, 0, 0);
    if (want != s->requested) {
        if (precapture_native_request(ops, want ? 0x4038 : 0x4039, 0))
            return fail(s, ops);
        s->requested = want;
        if (post(s, ops, owner->message_owner, 4))
            return fail(s, ops);
        return 1;
    }
    if (precapture_cp_apply_if_idle(&s->control, owner->context) < 0)
        return -16;
    /* Preserve donor order: commit only when idle, release, then reply.
     * Any send error retains a fault rather than announcing success.
     */
    if (precapture_native_request(ops, 0x403d, 0)) {
        s->fault = 1;
        s->control.stage = FAULT_PHASE;
        return -5; /* retain cancellation state; no automatic second release */
    }
    s->cancel_sent = 0;
    return complete(s, ops, 0xf000);
}

/* Invoke only for the request13 portion AFTER native button-mask updates.
 * A future interceptor must preserve all original AF/AE/event processing,
 * and keep this requested flag synchronized with real capture-end/error
 * notifications. Those hooks remain unbound; this is not installable.
 */
int precapture_backend_buttons(struct precapture_backend_state *s, const struct precapture_native_operations *ops,
                               const struct precapture_owner_view *owner) {
    u32 want;
    if (!s || !ops || !ops->send || !owner || !owner->master || !owner->controller)
        return -22;
    if (s->fault)
        return -5;
    if (s->control.stage)
        return 1; /* prepare/apply owns the pending transition */
    if (!s->control.enabled && !s->requested)
        return 0; /* preserve the ordinary native/debug path */
    want = precapture_target_s1_active(s->control.enabled, s->control.trigger,
                                      owner->master, read_word(owner->controller + 0x24), 0, 0);
    if (want != s->requested) {
        if (precapture_native_request(ops, want ? 0x4038 : 0x4039, 0)) {
            s->fault = 1;
            s->control.stage = FAULT_PHASE;
            return -5;
        }
        s->requested = want;
    }
    return 1;
}
