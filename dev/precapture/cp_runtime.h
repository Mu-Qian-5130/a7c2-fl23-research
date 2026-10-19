#ifndef PRECAPTURE_CP_RUNTIME_H
#define PRECAPTURE_CP_RUNTIME_H
#include "cp_backend.h"
#include "cp_retention_lease.h"

/* Host-selected exact-source build tags; these are NOT proof of live loading.
 * Addresses come from the pinned images' data ends, not native owner padding.
 * A future loader/startup binding still has to initialize before task use.
 */
#define PRECAPTURE_RUNTIME_STOCK_TAG 0xf5a47758u
#define PRECAPTURE_RUNTIME_CURRENT_TAG 0x3d6656b9u
#define PRECAPTURE_RUNTIME_MAGIC 0x31524350u
#if PRECAPTURE_RELEASE_OBSERVER
#define PRECAPTURE_RUNTIME_ABI 4u
#else
#define PRECAPTURE_RUNTIME_ABI 3u
#endif
#define PRECAPTURE_RUNTIME_BYTES 96u
struct precapture_runtime {
    u32 magic, abi, source_tag, region_bytes;
    struct precapture_backend_state state;
    struct precapture_native_operations operations;
    struct precapture_retention_lease retention;
};
_Static_assert(sizeof(void *) == 4, "Exact runtime layout requires ARM32");
_Static_assert(sizeof(struct precapture_runtime) == PRECAPTURE_RUNTIME_BYTES, "Runtime layout");
_Static_assert(__builtin_offsetof(struct precapture_runtime, retention) == 80, "Retention offset");

/* Startup only, before owner tasks. Refuses nonzero/unrecognized storage;
 * repeated calls to an already valid runtime preserve active transactions.
 */
int precapture_target_runtime_initialize(struct precapture_runtime *, u32 source_tag);
/* Immutable publication/layout/operation check. Mutable control words are
 * deliberately not checked as an incoherent cross-task multiword snapshot.
 */
struct precapture_runtime *precapture_target_runtime_resolve(struct precapture_runtime *, u32 source_tag);
/* Original owner-task entrypoints, with initialized runtime resolution. */
int precapture_runtime_queue(struct precapture_runtime *, u32 tag, const u8 *root, const u8 *message);
int precapture_runtime_replay(struct precapture_runtime *, u32 tag, const u8 *controller, const u32 *event);
int precapture_runtime_button(struct precapture_runtime *, u32 tag, const u8 *controller);
u32 precapture_runtime_frame(struct precapture_runtime *, u32 tag, u32 context_word_10, u32 mode,
                            u32 request_subtype);
u32 precapture_runtime_reference(struct precapture_runtime *, u32 tag, u32 flags, u32 pressed, u32 recording);
/* Frozen-argument retention task callback and native enqueue prototypes.
 * No bootstrap/installer exists. Native current-task query authorizes apply;
 * enqueue acceptance or callback return never implies receipt of its ACK.
 */
int precapture_runtime_retention(u32 generation, u32 duration_ms);
int precapture_target_retention_enqueue(u32 generation, u32 duration_ms);
#endif
