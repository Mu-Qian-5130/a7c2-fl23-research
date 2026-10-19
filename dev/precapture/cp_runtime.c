/* Non-installable runtime state publication primitive. No static storage,
 * constructor, allocator, hardware/OS call, code-page mapping or boot hook.
 * Requires the exact source's extended data copy and proven region ownership.
 */
#include "cp_runtime.h"
typedef __UINTPTR_TYPE__ uptr;

static uptr expected_address(u32 tag) {
    if (tag == PRECAPTURE_RUNTIME_STOCK_TAG)
        return 0x1208b80u;
    if (tag == PRECAPTURE_RUNTIME_CURRENT_TAG)
        return 0x1209fa0u;
    return 0;
}

struct precapture_runtime *precapture_target_runtime_resolve(struct precapture_runtime *r, u32 tag) {
    uptr address = expected_address(tag);
    if (!address || (uptr)r != address)
        return 0;
    if (__atomic_load_n(&r->magic, __ATOMIC_ACQUIRE) != PRECAPTURE_RUNTIME_MAGIC ||
        r->abi != 1 || r->source_tag != tag || r->region_bytes != PRECAPTURE_RUNTIME_BYTES ||
        (uptr)r->operations.send != 0x4b3c49u ||
        (uptr)r->operations.post != 0x4b5fe5u ||
        (uptr)r->operations.defer != 0xb1feafu ||
        (uptr)r->operations.reply != 0x8daa15u)
        return 0;
    return r;
}

int precapture_target_runtime_initialize(struct precapture_runtime *r, u32 tag) {
    uptr address = expected_address(tag);
    if (!address || (uptr)r != address)
        return -95;
    if (precapture_target_runtime_resolve(r, tag))
        return 1; /* Never reset enabled, generation, cancellation or fault. */
    for (u32 i = 0; i < PRECAPTURE_RUNTIME_BYTES; ++i)
        if (((const volatile u8 *)r)[i])
            return -16; /* No takeover of an unknown/stale/live object. */
    r->abi = 1;
    r->source_tag = tag;
    r->region_bytes = PRECAPTURE_RUNTIME_BYTES;
    r->state.control.trigger = 1;
    r->state.control.duration_ms = 500;
    r->operations.send = (void *)(uptr)0x4b3c49u;
    r->operations.post = (void *)(uptr)0x4b5fe5u;
    r->operations.defer = (void *)(uptr)0xb1feafu;
    r->operations.reply = (void *)(uptr)0x8daa15u;
    /* All other state words were verified zero. Publish only after constants,
     * disabled state and operations are initialized. ARM emits release DMB.
     * This does not initialize a missing executable page or prove boot order.
     */
    __atomic_store_n(&r->magic, PRECAPTURE_RUNTIME_MAGIC, __ATOMIC_RELEASE);
    return 0;
}
