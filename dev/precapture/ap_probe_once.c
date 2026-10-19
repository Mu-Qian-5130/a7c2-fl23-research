#include "ap_probe_once.h"
#define ROUTE 0x90030001u
#define SOURCE 0x80020002u
#define ALLOCATE 0x8000000aull
#define SEND 0x80000004ull
#define RELEASE 0x8000000bull
#define MAGIC 0x31514f50u

struct native_request { probe_u32 route, reserved; probe_u64 argument; };
struct native_allocation { probe_u64 output; probe_u32 bytes, wait_flag; };
_Static_assert(sizeof(struct native_request)==16, "native outer request");
_Static_assert(sizeof(struct native_allocation)==16, "native allocation");
_Static_assert(sizeof(struct probe_result)==72, "probe report ABI");

static probe_u32 get32(const probe_u8 *p) {
    return (probe_u32)p[0] | (probe_u32)p[1]<<8 | (probe_u32)p[2]<<16 | (probe_u32)p[3]<<24;
}
static void put32(probe_u8 *p, probe_u32 v) {
    p[0]=(probe_u8)v;p[1]=(probe_u8)(v>>8);p[2]=(probe_u8)(v>>16);p[3]=(probe_u8)(v>>24);
}
static int fresh(volatile struct probe_result *r) {
    const volatile probe_u8 *p=(const volatile probe_u8 *)r;
    for(probe_u32 i=0;i<sizeof(*r);i++)if(p[i])return 0;
    return 1;
}
static int pointer_valid(const struct probe_binding *b, probe_u64 p) {
    return !(p&63u) && p>=b->shared_begin+64 &&
        p<=b->shared_begin+b->shared_bytes-20;
}
static int native_header(const probe_u8 *p) {
    /* Derived from pinned remote16-byte allocator's actual instructions.
     * This check does not substitute for a fresh live source/map binding.
     */
    return p[-16]==2 && p[-15]==0x41 && p[-14]==1 && !p[-13] &&
        get32(p-12)==0xa5a5a5a5u && get32(p-8)==16 &&
        get32(p-4)==0x55555555u && get32(p+16)==0x77777777u;
}
static int known_allocation_rejection(probe_i64 v) {
    return v==-22 || v==-1021 || v==-1023 || v==-1024;
}
static int uncertain(volatile struct probe_result *r) {
    r->ownership=PROBE_UNKNOWN;r->phase=PROBE_UNCERTAIN;
    return -5;
}
static int release_once(const struct probe_binding *b, volatile struct probe_result *r,
                         probe_ioctl invoke) {
    struct native_request request={ROUTE,0,r->message};
    r->phase=PROBE_RELEASING;r->release_attempts=1;
    probe_i64 result=invoke(b->descriptor,RELEASE,&request);
    r->release_status=result;
    if(result)return uncertain(r);
    r->ownership=PROBE_NONE;
    r->phase=PROBE_RELEASED;
    return 0;
}

int precapture_probe_once(const struct probe_binding *b, volatile struct probe_result *r,
                         probe_u32 nonce, probe_u32 send_query, probe_ioctl invoke) {
    if(!b || !r || !invoke || !nonce || send_query>1 || b->descriptor<0 || b->reserved ||
       b->shared_begin<4096 || (b->shared_begin&4095u) || b->shared_bytes!=0x200000ull ||
       b->shared_begin+b->shared_bytes<=b->shared_begin)return -22;
    if(!fresh(r))return -16;
    r->magic=MAGIC;r->version=1;r->nonce=nonce;r->send_query=send_query;
    r->allocation_status=r->send_status=r->release_status=-1;
    r->phase=PROBE_ALLOCATING;r->allocation_attempts=1;
    probe_u64 message=0;
    struct native_allocation allocation={(probe_u64)(probe_uptr)&message,16,0};
    struct native_request request={ROUTE,0,(probe_u64)(probe_uptr)&allocation};
    probe_i64 result=invoke(b->descriptor,ALLOCATE,&request);
    r->allocation_status=result;r->message=message;
    if(result) {
        if(!message && known_allocation_rejection(result)) {
            r->ownership=PROBE_NONE;r->phase=PROBE_REJECTED;return -5;
        }
        return uncertain(r);
    }
    if(!pointer_valid(b,message))return uncertain(r);
    probe_u8 *p=(probe_u8 *)(probe_uptr)message;
    if(!native_header(p))return uncertain(r);
    r->ownership=PROBE_CALLER;r->phase=PROBE_ALLOCATED;
    if(!send_query)return release_once(b,r,invoke);
    /* Only payload16 +native source4 may change. Other metadata stays.
     * No pointer/header/payload reads occur after the send attempt.
     */
    put32(p,0x41720005u);put32(p+4,nonce);put32(p+8,0);put32(p+12,0);
    put32(p-12,SOURCE); /* exact original osal_set_msg_src displacement */
    request.argument=message;
    r->phase=PROBE_SENDING;r->send_attempts=1;
    result=invoke(b->descriptor,SEND,&request);
    r->send_status=result;
    if(!result) {
        r->ownership=PROBE_REMOTE;r->phase=PROBE_HANDED_OFF;
        return 0; /* transport handoff ONLY, not a CP response or completion */
    }
    /* Even a tempting error value is not a certificate of no enqueue.
     * Whole-path failure ownership must be proved before adding recovery.
     */
    return uncertain(r); /* no retry/free if transfer ownership is unknown */
}

probe_i64 precapture_probe_native_ioctl(probe_i32 fd, probe_u64 command, void *request) {
#if defined(__aarch64__)
    register probe_i64 x0 __asm__("x0")=fd;
    register probe_u64 x1 __asm__("x1")=command;
    register void *x2 __asm__("x2")=request;
    register probe_u64 x8 __asm__("x8")=29;
    __asm__ volatile("svc 0":"+r"(x0):"r"(x1),"r"(x2),"r"(x8):"memory","cc");
    return x0;
#else
    (void)fd;(void)command;(void)request;
    return -95;
#endif
}
