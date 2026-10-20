#include "ap_poll_once.h"

struct poll_request { probe_u32 route,pad;probe_u64 argument; };
struct receive_request { probe_u64 output;probe_u32 timeout,pad; };
_Static_assert(sizeof(struct poll_result)==48,"poll result ABI");
_Static_assert(sizeof(struct poll_request)==16,"ioctl argument ABI");
_Static_assert(sizeof(struct receive_request)==16,"receive argument ABI");

int precapture_poll_once(const struct probe_binding*b,volatile struct poll_result*r,
                         probe_u32 own_id,probe_ioctl invoke){
    if(!b||!r||!invoke)return -22;
    probe_u64 rb=(probe_u64)(probe_uptr)r,bb=(probe_u64)(probe_uptr)b;
    if(rb+sizeof(*r)<=rb||bb+sizeof(*b)<=bb||
       (rb<bb+sizeof(*b)&&bb<rb+sizeof(*r))||b->descriptor<0||b->reserved||
       b->shared_begin<4096||(b->shared_begin&4095u)||b->shared_bytes!=0x200000ull||
       b->shared_begin+b->shared_bytes<=b->shared_begin||
       (rb<b->shared_begin+b->shared_bytes&&b->shared_begin<rb+sizeof(*r))||
       (bb<b->shared_begin+b->shared_bytes&&b->shared_begin<bb+sizeof(*b))||
       (own_id&0xffff8000u)!=0x803f0000u||!(own_id&0x7fffu))return -22;
    const volatile probe_u8*p=(const volatile probe_u8*)r;
    for(probe_u32 i=0;i<sizeof(*r);i++)if(p[i])return -16;
    r->magic=0x314c4f50u;r->version=1;r->phase=POLL_WAITING;
    r->consumed=1;r->own_id=own_id;r->status=-1;r->attempts=1;
    struct receive_request receive={(probe_u64)(probe_uptr)&r->message,0,0};
    struct poll_request request={own_id,0,(probe_u64)(probe_uptr)&receive};
    probe_i64 status=invoke(b->descriptor,0x80000007ull,&request);
    r->status=status;
    if(status==-1022&&!r->message){r->phase=POLL_EMPTY;return 1;}
    if(!status&&!(r->message&7u)&&r->message>=b->shared_begin+24&&
       r->message<=b->shared_begin+b->shared_bytes-4){
        r->ownership=POLL_CALLER;r->phase=POLL_RETURNED;return 0;
    }
    /* An ioctl error can already have freed a dequeued packet while copying
     * its pointer to userspace. Do not dereference/free an uncertain result.
     */
    r->ownership=POLL_UNKNOWN;r->phase=POLL_UNCERTAIN;return -5;
}
