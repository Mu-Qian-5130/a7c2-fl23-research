#ifndef PRECAPTURE_CP_BACKEND_H
#define PRECAPTURE_CP_BACKEND_H
#include "cp_control_state.h"
struct precapture_backend_state {
    struct precapture_control control;
    u32 requested, generation, cancel_sent, fault;
};
_Static_assert(sizeof(struct precapture_backend_state) == 48, "CP backend layout");
struct precapture_native_operations {
    /* Actual target file offsets, with Thumb bit/load bias applied by a
     * future verified binding. Function pointers are never guessed here. */
    int (*send)(const void *, u32, u32);             /*0x3abc48 */
    int (*post)(void *, u32, const void *, u32);     /*0x3adfe4 */
    int (*defer)(void *, const void *);             /*0xa17eae */
    int (*reply)(const void *, u32, u32);            /*0x7d2a14 */
};
struct precapture_owner_view {
    const u8 *master;
    const volatile u32 *context;
    const u8 *controller;
    void *deferred_ring;
    void *message_owner;
};
/* Requires verified native pointers; does not install an event interceptor. */
int precapture_target_bind_owner(struct precapture_owner_view *, const u8 *manager,
                                const u8 *master, void *message_owner);
/* Future serialized-manager hook: 0 forwards; nonzero consumes/rejects. */
int precapture_target_task_event(struct precapture_backend_state *,
    const struct precapture_native_operations *, const u8 *manager,
    const u32 *event, u32 bytes);
int precapture_native_request(const struct precapture_native_operations *, u32 command, u32 value);
int precapture_backend_begin(struct precapture_backend_state *, const struct precapture_native_operations *,
                             void *owner, const u8 *packet, u32 length, u32 origin);
int precapture_backend_event(struct precapture_backend_state *, const struct precapture_native_operations *,
                             const struct precapture_owner_view *, const u32 *event);
int precapture_backend_buttons(struct precapture_backend_state *, const struct precapture_native_operations *,
                               const struct precapture_owner_view *);
#endif
