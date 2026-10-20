#include "ap_reply_once.h"
#include "ap_binding_guard.h"
struct release_request {probe_u32 route,pad;probe_u64 argument;};
_Static_assert(sizeof(struct reply_result)==80,"reply result ABI");
_Static_assert(sizeof(struct release_request)==16,"release argument ABI");
static probe_u32 get32(const probe_u8*p){return p[0]|(probe_u32)p[1]<<8|(probe_u32)p[2]<<16|(probe_u32)p[3]<<24;}
static int uncertain(volatile struct poll_result*p,volatile struct reply_result*r){
    p->ownership=POLL_UNKNOWN;p->phase=POLL_UNCERTAIN;
    r->ownership=REPLY_UNKNOWN;r->phase=REPLY_UNCERTAIN;return -5;
}

int precapture_reply_once(const struct probe_binding*b,volatile struct poll_result*pol,
    volatile struct reply_result*r,probe_u32 nonce,probe_u32 tag,probe_ioctl invoke){
    if(!invoke||!nonce||!tag||!precapture_private_binding(b,pol,sizeof(*pol))||
       !precapture_private_binding(b,r,sizeof(*r))||
       !precapture_spans_disjoint(pol,sizeof(*pol),r,sizeof(*r)))return -22;
    const volatile probe_u8*initial=(const volatile probe_u8*)r;
    for(probe_u32 i=0;i<sizeof(*r);i++)if(initial[i])return -16;
    if(pol->magic!=0x314c4f50u||pol->version!=1||pol->consumed!=1||pol->reserved||
       pol->attempts!=1||pol->status||!precapture_own_queue_id(pol->own_id))return -22;
    if(pol->phase!=POLL_RETURNED||pol->ownership!=POLL_CALLER)return -16;
    r->magic=0x31505251u;r->version=1;r->phase=REPLY_INSPECTING;r->ownership=REPLY_CALLER;
    r->own_id=pol->own_id;r->nonce=nonce;r->expected_tag=tag;r->release_status=-1;r->message=pol->message;
    pol->phase=POLL_INSPECTING;pol->ownership=POLL_UNKNOWN;
    probe_u64 message=r->message;
    if((message&63u)||message<b->shared_begin+64||
       message>b->shared_begin+b->shared_bytes-PRECAPTURE_QUERY_REPLY_BYTES-4)return uncertain(pol,r);
    const probe_u8*p=(const probe_u8*)(probe_uptr)message;
    if(p[-16]!=2||p[-15]!=0x41||p[-14]!=1||p[-13]||
       get32(p-8)!=PRECAPTURE_QUERY_REPLY_BYTES||get32(p-4)!=0x55555555u||
       get32(p+PRECAPTURE_QUERY_REPLY_BYTES)!=0x77777777u)return uncertain(pol,r);
    r->reply_nonce=get32(p+4);r->reply_tag=get32(p+12);
    r->generation=get32(p+16);r->flags=get32(p+20);r->stage=get32(p+24);r->duration_ms=get32(p+28);
    probe_u32 trigger=(r->flags>>8)&3u;
    r->kind=(get32(p-12)==0x90030001u&&get32(p)==0x41720001u&&
        get32(p+8)==PRECAPTURE_QUERY_REPLY_MAGIC&&r->reply_nonce==nonce&&r->reply_tag==tag&&
        !(r->flags&~0x31fu)&&r->stage<=7&&r->duration_ms<=1000&&
        (trigger?r->duration_ms>=5:r->duration_ms==0))?REPLY_MATCHED:REPLY_UNEXPECTED;
    r->phase=REPLY_VALIDATED;
    struct release_request request={pol->own_id,0,message};
    r->phase=REPLY_RELEASING;r->ownership=REPLY_UNKNOWN;r->release_attempts=1;
    probe_i64 status=invoke(b->descriptor,0x8000000bull,&request);
    r->release_status=status;
    if(status)return uncertain(pol,r);
    pol->ownership=POLL_NONE;pol->phase=POLL_RELEASED;
    r->ownership=REPLY_NONE;r->phase=REPLY_RELEASED;
    return r->kind==REPLY_MATCHED?0:-84;
}
