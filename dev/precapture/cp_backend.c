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
extern u32 precapture_target_s1_active(u32, u32, const u8 *, u32, u32, u32);
#define EVENT 0x8240u
#define COOKIE 0x50435231u
#define FAULT_PHASE 3u

static u32 read_word(const u8 *p) {
    return (u32)p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24;
}
static void word(u8 *p, u32 v) {
    p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24;
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
    result = precapture_cp_begin(&s->control, packet, length, origin);
    if (result < 0)
        return result;
    if (++s->generation == 0)
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
    if (s->fault || s->control.stage != 1 || event[1] != s->generation ||
        event[3] != s->control.pending_enabled)
        return 1; /* stale request; never modify unrelated native state */
    phase = event[2];
    if (phase != 1 && phase != 2)
        return fail(s, ops);
    if (owner->context[3] && (phase == 2 || !s->requested)) {
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
        buttons = read_word(owner->controller + 0x24);
        want = precapture_target_s1_active(s->control.pending_enabled, s->control.trigger,
                                          owner->master, buttons, 0, 0);
        if (want != s->requested) {
            if (precapture_native_request(ops, want ? 0x4038 : 0x4039, 0))
                return fail(s, ops);
            s->requested = want;
        }
        if (post(s, ops, owner->message_owner, 2))
            return fail(s, ops);
        return 1;
    }
    if (!s->cancel_sent)
        return fail(s, ops);
    /* Buttons may change while phase2 is deferred. Reconcile using the
     * current native mask, then queue another idle check; never commit and
     * release against the stale phase1 start/stop decision.
     */
    buttons = read_word(owner->controller + 0x24);
    want = precapture_target_s1_active(s->control.pending_enabled, s->control.trigger,
                                      owner->master, buttons, 0, 0);
    if (want != s->requested) {
        if (precapture_native_request(ops, want ? 0x4038 : 0x4039, 0))
            return fail(s, ops);
        s->requested = want;
        if (post(s, ops, owner->message_owner, 2))
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
