/* Exact-source owner-local observation only. Never mutate a native object,
 * allocate, set/clear cancellation, read pixels or announce terminal drain.
 */
#include "cp_release_observer.h"
typedef __UINTPTR_TYPE__ uptr;

static u32 word(const u8 *p) {
    return (u32)p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24;
}
static void store(u8 *p, u32 v) {
    p[0]=v; p[1]=v>>8; p[2]=v>>16; p[3]=v>>24;
}
static int valid(u32 generation, u32 desired) {
    return generation && desired <= 1 && !(desired && generation == 0xffffffffu);
}
static int overlap(uptr a, u32 an, uptr b, u32 bn) {
    /* Subtraction avoids overflowing either endpoint. */
    return a >= b ? a-b < bn : b-a < an;
}

int precapture_release_query_build(u32 generation, u32 desired, u8 *p, u32 capacity) {
    if (!valid(generation, desired) || !p || capacity < 16)
        return -22;
    p[0]=5; p[1]=0; p[2]=(u8)PRECAPTURE_RELEASE_QUERY; p[3]=PRECAPTURE_RELEASE_QUERY>>8;
    store(p+4,generation); store(p+8,desired); store(p+12,PRECAPTURE_RELEASE_COOKIE);
    return 16;
}

int precapture_release_query_parse(const u8 *p, u32 bytes, u32 origin, u32 *args) {
    if (!p || bytes < 4)
        return -22;
    if (((u32)p[2] | (u32)p[3]<<8) != PRECAPTURE_RELEASE_QUERY)
        return 0;
    if (bytes != 16 || p[0] != 5 || p[1] || origin != 0x90030001u ||
        !args || ((uptr)args & 3u) || overlap((uptr)args,8,(uptr)p,bytes) ||
        word(p+12) != PRECAPTURE_RELEASE_COOKIE || !valid(word(p+4),word(p+8)))
        return -22;
    args[0]=word(p+4); args[1]=word(p+8);
    return 1;
}

int precapture_release_task_valid(u32 task, int query_status) {
    return !query_status && task == PRECAPTURE_RELEASE_TASK ? 0 : -1;
}

int precapture_release_observe(const u8 *r, u32 generation, u32 desired, u32 *out) {
    u32 reason=0, selection, active, requested;
    int result=-95;
    if ((uptr)r != PRECAPTURE_RELEASE_ROOT || !valid(generation,desired) ||
        !out || ((uptr)out & 3u) ||
        overlap((uptr)out,32,PRECAPTURE_RELEASE_ROOT,0x310))
        return -22;
    /* Native constructors/pointer binding, not a guessed donor structure.
     * The query never invokes9da0a8: that wrapper resets native state.
     */
    if (word(r) != 0xe6cfb4u || word(r+4) != 0x4593c9u ||
        word(r+8) != 0x459471u || word(r+12) != 0x4594ddu ||
        word(r+0x158) != 0xe6cfccu || word(r+0x15c) != 0x458559u ||
        word(r+0x278) != 0xe6cffcu ||
        word(r+0x27c) != PRECAPTURE_RELEASE_ROOT+0x158 ||
        word(r+0x280) != PRECAPTURE_RELEASE_ROOT+0x298 ||
        word(r+0x284) != PRECAPTURE_RELEASE_ROOT+0x2ac ||
        word(r+0x298) != 0xe6cfe4u)
        goto reply;
    reason=word(r+0x2a0);
    if (!(reason & 4u)) {result=-116; goto reply;}
    selection=word(r+0x288); active=r[0x290]; requested=r[0x291];
    if (selection > 13 || active > 1 || requested > 1) {result=-22; goto reply;}
    if (selection || active || requested || word(r+0x294) != 0xffffffffu) {
        result=-16; goto reply;
    }
    for (u32 index=1;index<14;index++) {
        u32 flag=r[0x158+0x14+index*16];
        if (flag) {result=flag==1 ? -16 : -22; goto reply;}
    }
    result=0;
reply:
    out[0]=0; out[1]=0x8240; out[2]=generation; out[3]=PRECAPTURE_RELEASE_PHASE;
    out[4]=desired; out[5]=PRECAPTURE_RELEASE_COOKIE; out[6]=(u32)result; out[7]=reason;
    return result;
}
