#ifndef PRECAPTURE_RELEASE_OBSERVER_H
#define PRECAPTURE_RELEASE_OBSERVER_H
#include "cp_control_state.h"

/* NON-INSTALLABLE protocol extension. Stock CAP routing rejects40f0.
 * A future custom-loop interceptor must consume it and preserve native free.
 * This is an ordered owner observation, NOT sensor/terminal-frame completion.
 */
#define PRECAPTURE_RELEASE_QUERY 0x40f0u
#define PRECAPTURE_RELEASE_ROOT 0x1a2332cu
#define PRECAPTURE_RELEASE_TASK 0x6fu
#define PRECAPTURE_RELEASE_COOKIE 0x50435231u
#define PRECAPTURE_RELEASE_PHASE 5u /* Existing S1 prototype rejects this phase. */

int precapture_release_query_build(u32 generation, u32 desired, u8 *packet, u32 capacity);
/*0=ordinary command;1=parsed private query;negative=consume/reject private or
 * malformed input. Output arguments stay unchanged unless return1. */
int precapture_release_query_parse(const u8 *packet, u32 bytes, u32 origin, u32 *arguments);
/* Caller already owns the native CAM_RELEASE task. Checks exact native
 * object anchors and only observes its fields. Writes only caller reply.
 * This pure primitive does not establish task ownership or quiescence. */
int precapture_release_observe(const u8 *root, u32 generation, u32 desired, u32 *reply);
int precapture_release_task_valid(u32 task, int query_status);

/* Native ARM32 binding; no hook, placement, runtime integration or installer.
 * query_dispatch calls the actual task query with an initialized output.
 * after_query is separately testable on explicit synthetic query metadata;
 * calling it alone is not proof that an RTOS task query actually succeeded.
 */
int precapture_release_query_dispatch(const u8 *packet, u32 bytes, u32 origin);
int precapture_release_after_query(u32 generation, u32 desired, u32 task, int query_status);
/* Native IPC pointer only; never pass a deferred stack-copy event. */
int precapture_release_native_message(const u8 *message);
#endif
