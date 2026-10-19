/* Exact-source task-entry adapter; not installed or executable placement.
 *
 * A future hook must invoke this BEFORE native manager classification, in
 * that manager's serialized task, with the real remaining message length.
 * Return0 forwards the ordinary event unchanged; any other return consumes
 * the private event, including malformed private events. Never forward a
 * rejected0x8240 into native classification. No global state/constructor.
 */
#include "cp_backend.h"
typedef __UINTPTR_TYPE__ uptr;
#define EVENT 0x8240u
#define COOKIE 0x50435231u

int precapture_target_task_event(struct precapture_backend_state *state,
    const struct precapture_native_operations *ops, const u8 *manager,
    const u32 *event, u32 bytes) {
    struct precapture_owner_view view;
    int result;
    if (!event || bytes < sizeof(u32) || ((uptr)event & 3u))
        return -22;
    if (event[0] != EVENT)
        return 0;
    if (bytes != 28 || event[4] != COOKIE || !state || !ops ||
        (uptr)manager != 0x1a52bd0u)
        return -22;
    /* Values are original getter results, separately executed/pinned by
     * audit_owner_binding.py; they are not donor master-field guesses. */
    result = precapture_target_bind_owner(&view, manager,
        (const u8 *)(uptr)0x165a720u, (void *)(uptr)0x1a52b34u);
    if (result < 0)
        return result;
    result = precapture_backend_event(state, ops, &view, event);
    return result < 0 ? result : 1;
}
