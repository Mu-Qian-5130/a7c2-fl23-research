#include "ap_query_once.h"
#include "ap_binding_guard.h"
#define ROUTE 0x90030001u
struct query_request {probe_u32 route,pad;probe_u64 argument;};
struct query_allocation {probe_u64 output;probe_u32 bytes,wait;};
_Static_assert(sizeof(struct query_result)==64,"query result ABI");
_Static_assert(sizeof(struct query_request)==16,"query ioctl ABI");
_Static_assert(sizeof(struct query_allocation)==16,"query allocation ABI");
static probe_u32 get32(const probe_u8*p){return p[0]|(probe_u32)p[1]<<8|(probe_u32)p[2]<<16|(probe_u32)p[3]<<24;}
static void put32(probe_u8*p,probe_u32 v){p[0]=v;p[1]=v>>8;p[2]=v>>16;p[3]=v>>24;}
static int uncertain(volatile struct query_result*r){r->phase=QUERY_UNCERTAIN;r->ownership=QUERY_UNKNOWN;return -5;}

int precapture_query_once(const struct probe_binding*b,volatile struct query_result*r,
    probe_u32 own_id,probe_u32 nonce,probe_ioctl invoke){
    if(!invoke||!nonce||!precapture_own_queue_id(own_id)||
       !precapture_private_binding(b,r,sizeof(*r)))return -22;
    const volatile probe_u8*initial=(const volatile probe_u8*)r;
    for(probe_u32 i=0;i<sizeof(*r);i++)if(initial[i])return -16;
    r->magic=0x31595351u;r->version=1;r->phase=QUERY_ALLOCATING;r->ownership=QUERY_UNKNOWN;
    r->nonce=nonce;r->own_id=own_id;r->allocation_status=r->send_status=-1;r->allocation_attempts=1;
    probe_u64 message=0;
    struct query_allocation alloc={(probe_u64)(probe_uptr)&message,PRECAPTURE_QUERY_REQUEST_BYTES,0};
    struct query_request request={ROUTE,0,(probe_u64)(probe_uptr)&alloc};
    probe_i64 status=invoke(b->descriptor,0x8000000aull,&request);
    r->allocation_status=status;r->message=message;
    if(status){
        if(!message&&(status==-22||status==-1021||status==-1023||status==-1024)){
            r->phase=QUERY_REJECTED;r->ownership=QUERY_NONE;return -5;
        }
        return uncertain(r);
    }
    if((message&63u)||message<b->shared_begin+64||
       message>b->shared_begin+b->shared_bytes-PRECAPTURE_QUERY_REQUEST_BYTES-4)return uncertain(r);
    probe_u8*p=(probe_u8*)(probe_uptr)message;
    if(p[-16]!=2||p[-15]!=0x41||p[-14]!=1||p[-13]||get32(p-12)!=0xa5a5a5a5u||
       get32(p-8)!=PRECAPTURE_QUERY_REQUEST_BYTES||get32(p-4)!=0x55555555u||
       get32(p+PRECAPTURE_QUERY_REQUEST_BYTES)!=0x77777777u)return uncertain(r);
    r->phase=QUERY_READY;r->ownership=QUERY_CALLER;r->header_verified=1;
    put32(p,0x41720005u);put32(p+4,nonce);put32(p+8,PRECAPTURE_QUERY_REQUEST_MAGIC);
    put32(p-12,own_id);r->packet_written=1;
    request.argument=message;r->phase=QUERY_SENDING;r->ownership=QUERY_UNKNOWN;r->send_attempts=1;
    status=invoke(b->descriptor,0x80000004ull,&request);
    r->send_status=status;
    if(status)return uncertain(r);
    r->phase=QUERY_HANDED_OFF;r->ownership=QUERY_TRANSPORT;
    return 0; /* No CP receipt, payload access, free, retry or teardown. */
}
