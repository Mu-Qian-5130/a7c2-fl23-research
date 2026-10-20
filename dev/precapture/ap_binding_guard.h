/* Structural checks only. Live source/FD/MM/map/queue provenance is external. */
#ifndef PRECAPTURE_AP_BINDING_GUARD_H
#define PRECAPTURE_AP_BINDING_GUARD_H
#include "ap_probe_once.h"

static int precapture_spans_disjoint(const volatile void*a,probe_u64 as,
    const volatile void*b,probe_u64 bs){
    probe_u64 aa=(probe_u64)(probe_uptr)a,bb=(probe_u64)(probe_uptr)b;
    return a&&b&&as&&bs&&aa+as>aa&&bb+bs>bb&&!(aa<bb+bs&&bb<aa+as);
}
static int precapture_private_binding(const struct probe_binding*b,
    const volatile void*result,probe_u64 bytes){
    if(!b||!result||!bytes)return 0;
    probe_u64 rb=(probe_u64)(probe_uptr)result,bb=(probe_u64)(probe_uptr)b;
    if(!precapture_spans_disjoint(result,bytes,b,sizeof(*b))||b->descriptor<0||b->reserved||
       b->shared_begin<4096||(b->shared_begin&4095u)||b->shared_bytes!=0x200000ull||
       b->shared_begin+b->shared_bytes<=b->shared_begin||
       (rb<b->shared_begin+b->shared_bytes&&b->shared_begin<rb+bytes)||
       (bb<b->shared_begin+b->shared_bytes&&b->shared_begin<bb+sizeof(*b)))return 0;
    return 1;
}
static int precapture_own_queue_id(probe_u32 id){
    return (id&0xffff8000u)==0x803f0000u&&(id&0x7fffu);
}
#endif
