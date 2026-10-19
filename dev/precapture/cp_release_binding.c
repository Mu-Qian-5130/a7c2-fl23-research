/* ARM32 native binding prototype. No CAP-loop interceptor is installed.
 * Only the matched ABI4 backend consumes phase5; legacy ABI3 rejects it.
 * This does not prove RAW drain,
 * acquire exclusive reason4 ownership, change settings or execute a loader.
 */
#include "cp_release_observer.h"
typedef __UINTPTR_TYPE__ uptr;
_Static_assert(sizeof(void *) == 4, "Exact native ARM32 binding");

int precapture_release_after_query(u32 generation, u32 desired, u32 task, int query_status) {
    u32 packet[8];
    int (*post)(void *,u32,const void *,u32) = (void *)(uptr)0x4b5fe5u;
    int status;
    if (precapture_release_task_valid(task,query_status))
        return -1;
    status=precapture_release_observe((const u8 *)(uptr)PRECAPTURE_RELEASE_ROOT,
                                    generation,desired,packet);
    if (status == -22 && (!generation || desired > 1 ||
                          (desired && generation == 0xffffffffu)))
        return -22;
    /* Busy, lost cancellation and bad-layout results are frozen observations,
     * never success. S1 must match generation/phase/desired before acting.
     * A post error must not be retried or interpreted as rollback.
     */
    return post((void *)(uptr)0x1a52b34u,0x900302d9u,packet,sizeof(packet)) ? -5 : 1;
}

int precapture_release_query_dispatch(const u8 *packet, u32 bytes, u32 origin) {
    const volatile u32 *task=(const volatile u32 *)(uptr)0x1a2361cu;
    int (*get_task)(u32 *)=(void *)(uptr)0x5f1f24u; /* Original ARM get_tid. */
    u32 arguments[2], current=0;
    int status=precapture_release_query_parse(packet,bytes,origin,arguments);
    if (status != 1)
        return status;
    if (task[0] != 0x7425b9u || task[2] != 0x4590f9u || task[5] != PRECAPTURE_RELEASE_TASK)
        return -95;
    status=get_task(&current);
    return precapture_release_after_query(arguments[0],arguments[1],current,status);
}

int precapture_release_native_message(const u8 *message) {
    u32 (*native_size)(const void *)=(void *)(uptr)0xbec28fu;
    u32 (*native_origin)(const void *)=(void *)(uptr)0xbec02bu;
    u32 bytes,command;
    if (!message || ((uptr)message & 3u))
        return -22;
    bytes=native_size(message);
    if (bytes < 4)
        return -22;
    command=(u32)message[2] | (u32)message[3]<<8;
    if (command != PRECAPTURE_RELEASE_QUERY)
        return 0;
    return precapture_release_query_dispatch(message,bytes,native_origin(message));
}
