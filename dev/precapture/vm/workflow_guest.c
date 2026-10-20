/* File-only virtual-device integration test, NOT a camera adapter/installer.
 * Run in a disposable Linux guest. No firmware RPCs, devices, IPC or RAW IDs.
 * The production controller is compiled unchanged beside these explicit actors.
 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include "../capture_workflow.h"

#define CHECK(x) do { if (!(x)) { fprintf(stderr,"WF_GUEST_FAIL line=%d errno=%d\n",__LINE__,errno); exit(1); } } while (0)
#define PIXELS 1024u
struct image { u32 lease,handle; unsigned char pixels[PIXELS]; };
struct actor {
    struct wf_state state;
    struct image *images[WF_CAPACITY];
    u32 serial,policy,limit,epoch,flag,active,stopped,queued,saves,frees,rejects;
    u32 last_ticket,scenario,started;
    FILE *journal,*results;
    const char *folder;
};
static unsigned char profile[0x6800];
static const char header[]="P5\n32 16\n65535\n";

static void word(unsigned char *p,u32 n) {
    for (u32 i=0;i<4;i++) p[i]=(unsigned char)(n>>(8*i));
}
static void path(char *out,size_t length,const struct actor *d,u32 lease) {
    int n=snprintf(out,length,"%s/g%u-f%u.pgm",d->folder,d->state.generation,lease);
    CHECK(n>0 && (size_t)n<length);
}
static void log_event(struct actor *d,const char *name,u32 kind,u32 ticket,u32 lease) {
    CHECK(fprintf(d->journal,"%s %u %u %u %u\n",name,d->state.generation,ticket,kind,lease)>0);
}
static struct image *find(struct actor *d,u32 handle) {
    for (u32 i=0;i<WF_CAPACITY;i++) if (d->images[i] && d->images[i]->handle==handle) return d->images[i];
    CHECK(0); return NULL;
}
static void release(struct actor *d,struct image *image) {
    for (u32 i=0;i<WF_CAPACITY;i++) if (d->images[i]==image) {
        free(image);d->images[i]=NULL;d->frees++;return;
    }
    CHECK(0);
}
static void ledger(struct actor *d) {
    u32 held=0,slots=0;
    for (u32 i=0;i<WF_CAPACITY;i++) {
        if (d->images[i]) held++;
        if (d->state.frames[i].lease) {
            struct image *f=find(d,d->state.frames[i].handle);
            CHECK(f->lease==d->state.frames[i].lease);slots++;
        }
    }
    CHECK(held==slots && held==d->state.count);
}
static int offer(struct actor *d,u32 lease,wf_tick end,int eligible) {
    CHECK(d->active || (d->stopped && d->state.phase==WF_FENCE));
    struct image *image=malloc(sizeof(*image));CHECK(image);
    image->lease=lease;image->handle=0x1000+lease;
    for (u32 i=0;i<512;i++) {
        u32 pixel=(d->state.generation*1237u+lease*9001u+i*257u)&65535u;
        image->pixels[2*i]=(unsigned char)(pixel>>8);
        image->pixels[2*i+1]=(unsigned char)pixel;
    }
    memset(profile,0,sizeof(profile));word(profile+0x66e8,2);word(profile+0xbb4,eligible?4:0);
    struct wf_frame f={lease,image->handle,end-100,end};
    int result=precapture_workflow_frame(&d->state,d->state.generation,++d->serial,&f,profile);
    log_event(d,result==1?"offer":"reject",0,0,lease);
    if (result==1) {
        u32 at=0;while (at<WF_CAPACITY && d->images[at]) at++;
        CHECK(at<WF_CAPACITY);d->images[at]=image;
    } else {
        /* This reference never transferred; only its caller releases it. */
        free(image);d->rejects++;CHECK(result==-28 || result==-84);
    }
    ledger(d);return result;
}
static void save_image(struct actor *d,struct image *image) {
    char name[1024];path(name,sizeof(name),d,image->lease);
    int fd=open(name,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);CHECK(fd>=0);
    CHECK(write(fd,header,sizeof(header)-1)==(ssize_t)(sizeof(header)-1));
    CHECK(write(fd,image->pixels,PIXELS)==PIXELS);
    CHECK(fsync(fd)==0);CHECK(close(fd)==0);
    fd=open(name,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);CHECK(fd>=0);
    unsigned char data[sizeof(header)-1+PIXELS+1];ssize_t size=read(fd,data,sizeof(data));
    CHECK(size==(ssize_t)(sizeof(header)-1+PIXELS));CHECK(close(fd)==0);
    CHECK(!memcmp(data,header,sizeof(header)-1));
    CHECK(!memcmp(data+sizeof(header)-1,image->pixels,PIXELS));d->saves++;
}
static int next(struct actor *d,struct wf_action *a) {
    int result=precapture_workflow_next(&d->state,a);
    if (result==1) {
        CHECK(a->ticket>d->last_ticket);d->last_ticket=a->ticket;
        struct wf_state frozen=d->state;struct wf_action duplicate;
        CHECK(precapture_workflow_next(&d->state,&duplicate)==0);
        CHECK(!memcmp(&frozen,&d->state,sizeof(frozen)));
        log_event(d,"request",a->kind,a->ticket,a->lease);
    }
    return result;
}
static struct wf_completion apply(struct actor *d,const struct wf_action *a) {
    struct wf_completion c={a->kind,a->generation,a->ticket,WF_APPLIED,a->lease,0,0,d->serial};
    CHECK(a->generation==d->state.generation);
    switch (a->kind) {
    case WF_SET_POLICY:
        CHECK(!d->active && !d->state.count);d->policy=0;d->limit=a->value;
        c.auxiliary=d->limit;break;
    case WF_REFRESH_ON:
        CHECK(!d->policy);d->epoch=a->auxiliary+1;d->flag=1;
        c.value=d->epoch;c.auxiliary=d->flag;break;
    case WF_START_READOUT:
        CHECK(d->epoch==a->auxiliary+1 && d->flag==1 && !d->active);
        d->active=1;d->stopped=0;d->started++;c.value=d->epoch;break;
    case WF_STOP_READOUT:
        CHECK(d->active);d->active=0;d->stopped=1;break;
    case WF_TERMINAL_FENCE:
        CHECK(d->stopped && !d->active);
        if (d->queued) {
            CHECK(offer(d,5,10000000,1)==1);CHECK(offer(d,6,10100000,1)==1);d->queued=0;
        }
        c.serial=d->serial;c.value=d->state.generation;break;
    case WF_SAVE: {
        CHECK(d->stopped && !d->queued);struct image *f=find(d,a->handle);
        CHECK(f->lease==a->lease);save_image(d,f);
        /* Explicit virtual-writer contract: even leases consume; odd retain. */
        if (!(a->lease&1)) { release(d,f);c.value=WF_REFERENCE_CONSUMED; }
        break;
    }
    case WF_RELEASE: {
        struct image *f=find(d,a->handle);CHECK(f->lease==a->lease);release(d,f);break;
    }
    case WF_RESTORE_POLICY:
        CHECK(!d->active && d->stopped && !d->queued && !d->state.count);
        d->policy=a->value;d->limit=a->auxiliary;c.value=d->policy;c.auxiliary=d->limit;break;
    case WF_REFRESH_BASELINE:
        CHECK(d->policy==1 && d->limit==9);d->epoch=a->auxiliary+2;d->flag=0;
        c.value=d->epoch;c.auxiliary=d->flag;break;
    default: CHECK(0);
    }
    log_event(d,"applied",a->kind,a->ticket,a->lease);return c;
}
static void deliver(struct actor *d,const struct wf_completion *c) {
    CHECK(precapture_workflow_complete(&d->state,c)==1);
    log_event(d,"completed",c->kind,c->ticket,c->lease);ledger(d);
}
static void pump(struct actor *d) {
    for (u32 i=0;i<300;i++) {
        struct wf_action a;int result=next(d,&a);
        if (!result) return;
        CHECK(result==1);struct wf_completion c=apply(d,&a);deliver(d,&c);
    }
    CHECK(0);
}
static void begin(struct actor *d,u32 generation,u32 capacity) {
    CHECK(!d->state.magic);d->policy=1;d->limit=9;d->epoch=20;d->flag=0;d->stopped=1;
    CHECK(precapture_workflow_begin(&d->state,generation,500,capacity,1,9,20,0)==1);
}
static void finished(struct actor *d,u32 result,u32 saves,u32 frees,u32 rejects) {
    CHECK(d->state.phase==WF_DONE && d->state.result==result);
    CHECK(!d->state.count && !d->state.issued && !d->active && d->stopped && !d->queued);
    CHECK(d->policy==1 && d->limit==9 && d->flag==0 && d->epoch==d->state.parameter_epoch+2);
    CHECK(d->saves==saves && d->frees==frees && d->rejects==rejects);ledger(d);
    CHECK(fprintf(d->results,"%u %u %u %u %u %u\n",d->state.generation,result,saves,frees,rejects,d->started)>0);
    d->scenario++;
}
static void rearm(struct actor *d,u32 generation) {
    CHECK(precapture_workflow_rearm(&d->state,generation)==1);
    d->serial=d->saves=d->frees=d->rejects=d->started=0;
}
static void fresh(struct actor *d,u32 generation,u32 capacity) {
    ledger(d);CHECK(d->state.phase==WF_DONE);memset(&d->state,0,sizeof(d->state));
    d->serial=d->saves=d->frees=d->rejects=d->last_ticket=d->started=0;begin(d,generation,capacity);
}
int main(int argc,char **argv) {
    if (argc!=3 || strcmp(argv[1],"--virtual-only")) {
        fprintf(stderr,"File-only virtual test: workflow-guest --virtual-only NEW_DIRECTORY\n");return 2;
    }
    CHECK(mkdir(argv[2],0700)==0);
    struct actor d={0};d.folder=argv[2];char name[1024];
    CHECK(snprintf(name,sizeof(name),"%s/events.txt",d.folder)<(int)sizeof(name));
    d.journal=fopen(name,"wx");CHECK(d.journal);
    CHECK(snprintf(name,sizeof(name),"%s/results.txt",d.folder)<(int)sizeof(name));
    d.results=fopen(name,"wx");CHECK(d.results);
    begin(&d,7,8);pump(&d);CHECK(d.state.phase==WF_BUFFERING);
    const wf_tick ticks[]={8800000,9001000,9500000,9999999};
    for (u32 i=0;i<4;i++) { CHECK(offer(&d,i+1,ticks[i],1)==1);pump(&d); }
    CHECK(precapture_workflow_trigger(&d.state,10000000)==1);
    log_event(&d,"S2",0,0,0);d.queued=1;
    CHECK(precapture_workflow_cancel(&d.state)==0);pump(&d);finished(&d,WF_SAVED,3,6,0);

    rearm(&d,8);pump(&d);CHECK(offer(&d,1,9800000,1)==1);CHECK(offer(&d,2,9900000,1)==1);
    CHECK(precapture_workflow_cancel(&d.state)==1);pump(&d);finished(&d,WF_CANCELLED,0,2,0);

    rearm(&d,9);pump(&d);CHECK(offer(&d,1,9200000,1)==1);CHECK(offer(&d,2,9800000,1)==1);
    CHECK(precapture_workflow_trigger(&d.state,10000000)==1);pump(&d);finished(&d,WF_SAVED,2,2,0);

    fresh(&d,10,2);pump(&d);CHECK(offer(&d,1,9800000,1)==1);CHECK(offer(&d,2,9900000,1)==1);
    CHECK(offer(&d,3,9950000,1)==-28);CHECK(precapture_workflow_trigger(&d.state,10000000)==1);
    pump(&d);finished(&d,WF_SAVED,2,2,1);

    fresh(&d,11,8);
    for (u32 i=0;i<2;i++) { struct wf_action a;CHECK(next(&d,&a)==1);struct wf_completion c=apply(&d,&a);deliver(&d,&c); }
    CHECK(precapture_workflow_cancel(&d.state)==1);pump(&d);finished(&d,WF_CANCELLED,0,0,0);CHECK(!d.started);

    fresh(&d,12,8);pump(&d);CHECK(precapture_workflow_trigger(&d.state,10000000)==1);
    pump(&d);finished(&d,WF_NO_PRETRIGGER,0,0,0);

    fresh(&d,13,8);pump(&d);CHECK(offer(&d,1,9900000,0)==-84);
    CHECK(precapture_workflow_cancel(&d.state)==1);pump(&d);finished(&d,WF_CANCELLED,0,0,1);

    fresh(&d,14,8);
    for (u32 i=0;i<2;i++) { struct wf_action a;CHECK(next(&d,&a)==1);struct wf_completion c=apply(&d,&a);deliver(&d,&c); }
    struct wf_action a;CHECK(next(&d,&a)==1 && a.kind==WF_START_READOUT);
    struct wf_completion c=apply(&d,&a);CHECK(offer(&d,1,9900000,1)==1);
    CHECK(precapture_workflow_trigger(&d.state,10000000)==1);deliver(&d,&c);
    pump(&d);finished(&d,WF_SAVED,1,1,0);

    CHECK(fflush(d.journal)==0);CHECK(fsync(fileno(d.journal))==0);CHECK(fclose(d.journal)==0);
    CHECK(fflush(d.results)==0);CHECK(fsync(fileno(d.results))==0);CHECK(fclose(d.results)==0);
    printf("WF_GUEST_PASS scenarios=%u virtual_pixels=1 native_camera_bindings=0\n",d.scenario);
    return 0;
}
