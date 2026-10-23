#include "ap_client_binding.h"
#define GETPOLICY 120
#define GETPARAM 121
#define SETAFFINITY 122
#define GETAFFINITY 123
#define SIGMASK 135
#define GETCPU 168
#define GETPID 172
#define GETPPID 173
#define SIG_BLOCK 0
#define SIG_SETMASK 2
#define CATCHABLE (~((1ull<<8)|(1ull<<18)))
_Static_assert(sizeof(struct client_binding_result)==160,"client binding ABI");
static int unknown(volatile struct client_binding_result*r){r->phase=CLIENT_UNKNOWN;return -5;}
static probe_i64 call(volatile struct client_binding_result*r,ap_a64_syscall sc,int leaving,
    probe_i64 n,probe_i64 a,probe_i64 b,probe_i64 c,probe_i64 d){
    if(leaving)r->leave_calls++;else r->enter_calls++;
    r->last_result=sc(n,a,b,c,d,0,0);return r->last_result;
}
int precapture_client_bind_once(volatile struct client_binding_result*r,probe_u32 parent,
    probe_u32 CPU,ap_a64_syscall sc){
    if(!r||!sc||!parent||parent>0x7fffffff||CPU>=64)return -22;
    const volatile probe_u8*p=(const volatile probe_u8*)r;
    for(probe_u32 i=0;i<sizeof(*r);i++)if(p[i])return -16;
    r->magic=0x31424c43u;r->version=1;r->phase=CLIENT_INSPECT;
    r->expected_parent=parent;r->selected_CPU=CPU;r->enter_status=r->leave_status=-1;
    r->pid=call(r,sc,0,GETPID,0,0,0,0);
    r->parent=call(r,sc,0,GETPPID,0,0,0,0);
    if(r->pid<=0||r->pid>0x7fffffff||r->pid==parent||r->parent!=parent)goto rejected;
    r->policy_before=call(r,sc,0,GETPOLICY,0,0,0,0);
    probe_i32 priority=0;
    if(call(r,sc,0,GETPARAM,0,(probe_i64)&priority,0,0))goto rejected;
    r->priority_before=priority;
    if(r->policy_before||priority)goto rejected;
    if(call(r,sc,0,GETAFFINITY,0,8,(probe_i64)&r->affinity_before,0)!=8||
       !(r->affinity_before&(1ull<<CPU)))goto rejected;
    if(call(r,sc,0,SIGMASK,SIG_BLOCK,0,(probe_i64)&r->signals_before,8))goto rejected;
    probe_u64 mask=CATCHABLE;
    r->phase=CLIENT_BLOCK_SIGNALS;
    /* Ownership is conservative before each mutating syscall. No retry or
     * automatic inverse follows an unexpected result. All changes affect self.
     */
    r->ownership=CLIENT_SIGNALS_CHANGED;
    if(call(r,sc,0,SIGMASK,SIG_BLOCK,(probe_i64)&mask,0,8))return unknown(r);
    if(call(r,sc,0,SIGMASK,SIG_BLOCK,0,(probe_i64)&r->signals_after,8)||r->signals_after!=CATCHABLE)
        return unknown(r);
    mask=1ull<<CPU;r->phase=CLIENT_BIND_CPU;r->ownership|=CLIENT_CPU_CHANGED;
    if(call(r,sc,0,SETAFFINITY,0,8,(probe_i64)&mask,0))return unknown(r);
    if(call(r,sc,0,GETAFFINITY,0,8,(probe_i64)&r->affinity_after,0)!=8||r->affinity_after!=mask)
        return unknown(r);
    probe_u32 observed=~0u;
    if(call(r,sc,0,GETCPU,(probe_i64)&observed,0,0,0)||observed!=CPU)return unknown(r);
    r->observed_CPU=observed;
    r->policy_after=call(r,sc,0,GETPOLICY,0,0,0,0);priority=0;
    if(call(r,sc,0,GETPARAM,0,(probe_i64)&priority,0,0))return unknown(r);
    r->priority_after=priority;
    if(r->policy_after||priority)return unknown(r);
    r->phase=CLIENT_BOUND;r->enter_status=0;return 0;
rejected:r->phase=CLIENT_REJECTED;r->enter_status=-95;return -95;
}
int precapture_client_unbind_once(volatile struct client_binding_result*r,ap_a64_syscall sc){
    if(!r||!sc||r->magic!=0x31424c43u||r->version!=1||r->phase!=CLIENT_BOUND||
       r->ownership!=(CLIENT_SIGNALS_CHANGED|CLIENT_CPU_CHANGED)||r->enter_status||r->leave_calls||
       r->selected_CPU>=64||r->affinity_after!=(1ull<<r->selected_CPU)||
       !(r->affinity_before&r->affinity_after)||r->signals_after!=CATCHABLE)return -22;
    r->phase=CLIENT_RESTORE_CPU;
    if(call(r,sc,1,SETAFFINITY,0,8,(probe_i64)&r->affinity_before,0))return unknown(r);
    if(call(r,sc,1,GETAFFINITY,0,8,(probe_i64)&r->affinity_restored,0)!=8||
       r->affinity_restored!=r->affinity_before)return unknown(r);
    r->ownership=CLIENT_SIGNALS_CHANGED;r->phase=CLIENT_RESTORE_SIGNALS;
    if(call(r,sc,1,SIGMASK,SIG_SETMASK,(probe_i64)&r->signals_before,0,8))return unknown(r);
    if(call(r,sc,1,SIGMASK,SIG_BLOCK,0,(probe_i64)&r->signals_restored,8)||
       r->signals_restored!=r->signals_before)return unknown(r);
    r->ownership=CLIENT_NO_CHANGES;r->phase=CLIENT_RESTORED;r->leave_status=0;return 0;
}
