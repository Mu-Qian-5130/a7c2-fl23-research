#include "capture_workflow.h"
extern int precapture_retention_entry_eligible(const u8 *);
typedef __UINTPTR_TYPE__ wf_uptr;
static int disjoint(const void *a,u32 an,const void *b,u32 bn) {
    wf_uptr aa=(wf_uptr)a,bb=(wf_uptr)b;
    return a&&b&&aa+an>aa&&bb+bn>bb&&!(aa<bb+bn&&bb<aa+an);
}

static int valid(const struct wf_state *s) {
    return s && s->magic==WF_MAGIC && s->capacity && s->capacity<=WF_CAPACITY;
}
static int fault(struct wf_state *s) {
    if(s->phase!=WF_UNCERTAIN)s->last_phase=s->phase;
    s->phase=WF_UNCERTAIN;
    return -5;
}
static int expired(const struct wf_state *s,const struct wf_frame *f) {
    wf_tick reference=s->triggered?s->trigger:s->latest;
    wf_tick window=(wf_tick)(s->duration_ms*2000u);
    return reference>=window && f->end<reference-window;
}
static int keep(const struct wf_state *s,const struct wf_frame *f) {
    /* Exposure must have FINISHED strictly before the actual S2 reference. */
    return s->triggered && !s->cancelled && f->end<s->trigger && !expired(s,f);
}
static void resolved_slot(struct wf_state *s,u32 slot) {
    /* Metadata only; the matching service completed release. Never invoke a
     * native destructor or touch the possibly already destroyed image here.
     */
    volatile struct wf_frame *f=&s->frames[slot];
    f->lease=0;f->handle=0;f->begin=0;f->end=0;
    s->saved_mask&=~(1u<<slot);--s->count;++s->released;
}
int precapture_workflow_begin(struct wf_state *s,u32 generation,u32 duration,
    u32 capacity,u32 policy,u32 limit,u32 epoch,u32 original_flag) {
    if(!s||!generation||generation==0xffffffffu||duration<5||duration>1000||
       !capacity||capacity>WF_CAPACITY||policy>1||!epoch||epoch>0xfffffffdu||original_flag>1)return -22;
    const u8 *bytes=(const u8 *)s;
    for(u32 i=0;i<sizeof(*s);i++)if(bytes[i])return -16;
    s->magic=WF_MAGIC;s->generation=generation;s->phase=WF_CONFIGURE;
    s->duration_ms=duration;s->capacity=capacity;s->original_policy=policy;
    s->original_limit=limit;s->parameter_epoch=epoch;
    s->original_flag=original_flag;
    s->pending_slot=WF_CAPACITY;
    return 1;
}
int precapture_workflow_frame(struct wf_state *s,u32 generation,u32 serial,
    const struct wf_frame *f,const u8 *native_frame) {
    if(!valid(s)||!serial||!disjoint(s,sizeof(*s),f,sizeof(*f))||
       !disjoint(s,sizeof(*s),native_frame,0x6800)||
       !f->lease||!f->handle||f->begin>f->end)return -22;
    if(generation!=s->generation)return -116;
    if(s->phase==WF_UNCERTAIN)return -5;
    if(s->phase>=WF_DRAIN)return fault(s); /* Late same-generation ingress. */
    if(s->phase<WF_START)return -16;
    if(s->phase==WF_START&&(!s->issued||s->pending.kind!=WF_START_READOUT))return -16;
    if(serial!=s->ingress_serial+1u||s->ingress_serial==0xffffffffu||
       f->lease<=s->last_lease||f->end<s->latest)return fault(s);
    /* Every ingress is observed, even if it cannot transfer its reference. */
    s->ingress_serial=serial;s->last_lease=f->lease;s->latest=f->end;
    if(precapture_retention_entry_eligible(native_frame)!=1)return -84;
    for(u32 i=0;i<s->capacity;i++)
        if(s->frames[i].lease&&s->frames[i].handle==f->handle)return fault(s);
    for(u32 i=0;i<s->capacity;i++)if(!s->frames[i].lease) {
        s->frames[i]=*f;++s->count;return 1;
    }
    ++s->rejected; /* Reference stays with caller, never silently overwritten. */
    return -28;
}
int precapture_workflow_trigger(struct wf_state *s,wf_tick reference) {
    if(!valid(s)||!reference)return -22;
    if(s->phase==WF_UNCERTAIN)return -5;
    if(s->triggered)return s->trigger==reference?0:-116;
    if(s->cancelled||s->phase<WF_START||s->phase>WF_FENCE)return -16;
    if(reference<s->latest)return fault(s); /* S2 must precede post-edge ingress. */
    s->triggered=1;s->trigger=reference;
    if(!s->issued) {
        if(s->phase==WF_BUFFERING)s->phase=WF_STOP;
        else if(s->phase==WF_START)s->phase=WF_FENCE; /* Never start after S2. */
    }
    return 1;
}
int precapture_workflow_cancel(struct wf_state *s) {
    if(!valid(s))return -22;
    if(s->phase==WF_UNCERTAIN)return -5;
    if(s->phase==WF_DONE)return 0;
    if(s->triggered)return 0; /* S1 release must not abort a full-press save. */
    s->cancelled=1;
    if(!s->issued) {
        if(s->phase==WF_BUFFERING)s->phase=WF_STOP;
        else if(s->phase==WF_START)s->phase=WF_FENCE;
    }
    return 1;
}
int precapture_workflow_rearm(struct wf_state *s,u32 generation) {
    if(!valid(s)||generation<=s->generation||generation==0xffffffffu)return -22;
    if(s->phase!=WF_DONE||s->issued||s->count)return -16;
    if(s->parameter_epoch>0xfffffffbu||s->ticket==0xffffffffu)return -75;
    for(u32 i=0;i<WF_CAPACITY;i++)if(s->frames[i].lease)return -16;
    u32 duration=s->duration_ms,capacity=s->capacity,policy=s->original_policy;
    u32 limit=s->original_limit,epoch=s->parameter_epoch+2u;
    u32 original_flag=s->original_flag,ticket=s->ticket;
    /* All references are released and restoration is known in this supplied
     * contract. Volatile stores keep this free of implicit runtime helpers.
     */
    volatile u8 *bytes=(volatile u8 *)s;
    for(u32 i=0;i<sizeof(*s);i++)bytes[i]=0;
    int result=precapture_workflow_begin(s,generation,duration,capacity,policy,limit,epoch,original_flag);
    s->ticket=ticket;
    return result;
}
int precapture_workflow_next(struct wf_state *s,struct wf_action *out) {
    if(!valid(s)||!disjoint(s,sizeof(*s),out,sizeof(*out)))return -22;
    if(s->phase==WF_UNCERTAIN)return -5;
    if(s->issued||s->phase==WF_DONE)return 0;
    struct wf_action a={0};a.generation=s->generation;
    s->pending_slot=WF_CAPACITY;
    if(s->phase==WF_CONFIGURE)a.kind=WF_SET_POLICY;
    else if(s->phase==WF_REFRESH)a.kind=WF_REFRESH_ON;
    else if(s->phase==WF_START)a.kind=WF_START_READOUT;
    else if(s->phase==WF_STOP)a.kind=WF_STOP_READOUT;
    else if(s->phase==WF_FENCE)a.kind=WF_TERMINAL_FENCE;
    else if(s->phase==WF_RESTORE)a.kind=WF_RESTORE_POLICY;
    else if(s->phase==WF_REFRESH_RESTORE)a.kind=WF_REFRESH_BASELINE;
    else if(s->phase==WF_BUFFERING||s->phase==WF_DRAIN) {
        u32 oldest=WF_CAPACITY;
        for(u32 i=0;i<s->capacity;i++)if(s->frames[i].lease&&
            (oldest==WF_CAPACITY||s->frames[i].lease<s->frames[oldest].lease))oldest=i;
        if(oldest==WF_CAPACITY) {
            if(s->phase==WF_BUFFERING)return 0;
            s->phase=WF_RESTORE;a.kind=WF_RESTORE_POLICY;
        } else {
            const struct wf_frame *f=&s->frames[oldest];
            if(s->phase==WF_BUFFERING&&!expired(s,f))return 0;
            a.kind=s->phase==WF_DRAIN&&keep(s,f)&&!(s->saved_mask&(1u<<oldest))?WF_SAVE:WF_RELEASE;
            a.lease=f->lease;a.handle=f->handle;s->pending_slot=oldest;
        }
    } else return fault(s);
    if(s->ticket==0xffffffffu)return fault(s);
    a.ticket=++s->ticket;a.trigger=s->trigger;
    a.value=a.kind==WF_RESTORE_POLICY?s->original_policy:s->duration_ms;
    a.auxiliary=a.kind==WF_RESTORE_POLICY?s->original_limit:s->parameter_epoch;
    a.serial=s->ingress_serial;
    s->pending=a;s->issued=1;*out=a;return 1;
}
int precapture_workflow_complete(struct wf_state *s,const struct wf_completion *c) {
    if(!valid(s)||!disjoint(s,sizeof(*s),c,sizeof(*c)))return -22;
    if(s->phase==WF_UNCERTAIN)return -5;
    if(!s->issued||c->generation!=s->generation||c->ticket!=s->pending.ticket||
       c->kind!=s->pending.kind)return -116;
    if(c->outcome!=WF_APPLIED)return fault(s); /* Never retry ambiguous service. */
    u32 kind=c->kind;
    if(c->lease!=s->pending.lease)return fault(s);
    if(kind==WF_SET_POLICY&&(c->value!=0||c->auxiliary!=s->duration_ms))return fault(s);
    if(kind==WF_REFRESH_ON&&(c->value!=s->parameter_epoch+1u||c->auxiliary!=1))return fault(s);
    if(kind==WF_START_READOUT&&c->value!=s->parameter_epoch+1u)return fault(s);
    if(kind==WF_TERMINAL_FENCE&&(c->serial!=s->ingress_serial||c->value!=s->generation))return fault(s);
    if(kind==WF_RESTORE_POLICY&&(c->value!=s->original_policy||c->auxiliary!=s->original_limit))return fault(s);
    if(kind==WF_REFRESH_BASELINE&&(c->value!=s->parameter_epoch+2u||c->auxiliary!=s->original_flag))return fault(s);
    if(kind==WF_SAVE||kind==WF_RELEASE) {
        u32 slot=s->pending_slot;
        if(slot>=s->capacity||s->frames[slot].lease!=c->lease||
           s->frames[slot].handle!=s->pending.handle||!s->count)return fault(s);
        if(kind==WF_SAVE) {
            if(c->value>WF_REFERENCE_CONSUMED)return fault(s);
            ++s->saved;s->issued=0;
            if(c->value==WF_REFERENCE_CONSUMED)resolved_slot(s,slot);
            else s->saved_mask|=1u<<slot;
        } else {
            resolved_slot(s,slot);s->issued=0;
        }
        if(s->phase==WF_BUFFERING&&(s->triggered||s->cancelled))s->phase=WF_STOP;
        return 1;
    }
    s->issued=0;
    if(kind==WF_SET_POLICY)s->phase=WF_REFRESH;
    else if(kind==WF_REFRESH_ON)s->phase=s->cancelled?WF_FENCE:WF_START;
    else if(kind==WF_START_READOUT)s->phase=s->triggered||s->cancelled?WF_STOP:WF_BUFFERING;
    else if(kind==WF_STOP_READOUT)s->phase=WF_FENCE;
    else if(kind==WF_TERMINAL_FENCE){s->terminal_serial=c->serial;s->phase=WF_DRAIN;}
    else if(kind==WF_RESTORE_POLICY)s->phase=WF_REFRESH_RESTORE;
    else if(kind==WF_REFRESH_BASELINE) {
        if(s->count)return fault(s);
        s->result=s->cancelled?WF_CANCELLED:s->saved?WF_SAVED:WF_NO_PRETRIGGER;
        s->phase=WF_DONE;
    } else return fault(s);
    return 1;
}
