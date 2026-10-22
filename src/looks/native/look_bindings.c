/* Synchronize selected Creative Look bases with the native AP model.
 * The sequence below is the slot-indexed form of the original 2.01 menu
 * setter at 0x2614bcc: same locks, backing pointer, change log and notices.
 * It never changes the current selection, programs, mount or power state.
 */
#define _init bindings_probe_init
#include "probe.c"
#undef _init
#include PATCH_MANIFEST

struct BindingReport {
    u8 magic[8];u32 version,count;i64 status;u32 model,reserved;
    u32 current_before,current_after,changed,reserved2;
    u32 before[18],after[18];
};
static struct BindingReport result;
_Static_assert(sizeof(struct BindingReport)==192,"Binding report ABI");
static i64 get(i64 fd,u64 offset,void *out,u32 size) {
    i64 n=sc(67,fd,(i64)out,size,report.base+offset,0,0);
    return n==size?0:(n<0?n:-5);
}
static void set_base(u32 index,u32 value) {
    u64 context[2],lock;
    ((void(*)(void*))(report.base+0x178f950))(context);
    ((void(*)(void*))(report.base+0x2e06cc0))(&lock);
    u32 *values=((u32*(*)(void))(report.base+0x287ee10))();
    u8 *info=((u8*(*)(void))(report.base+0x287ee24))();
    u32 *backing=*(u32**)(info+40UL*index+8);
    u32 attribute=0x14e9+index;
    ((void(*)(u64,u32,void*,const void*,u64))(report.base+0x36830a8))(
        context[1],attribute,backing?backing:values+index,&value,4);
    if(backing)*backing=value;
    values[index]=value;
    ((void(*)(u32))(report.base+0x2506ff0))(attribute);
    ((void(*)(void*))(report.base+0x2e068cc))(&lock);
    ((void(*)(void*))(report.base+0x178f974))(context);
    ((void(*)(u32))(report.base+0x2506218))(0x14e9);
}
__attribute__((visibility("default"))) void _init(void) {
    bindings_probe_init();const u8 magic[]="A7LBS001";
    for(u32 i=0;i<8;i++)result.magic[i]=magic[i];
    result.version=1;result.count=target_count;result.model=report.index;result.status=report.status;
    if(!result.status&&(report.index!=16||report.euid))result.status=-22;
    i64 mem=-1;
    if(!result.status) {mem=op("/proc/self/mem",0);if(mem<0)result.status=mem;}
    for(u32 i=0;i<guard_count&&!result.status;i++) {
        u8 code[128];
        if(guards[i].length>sizeof(code)) {result.status=-22;break;}
        result.status=get(mem,guards[i].offset,code,guards[i].length);
        for(u32 j=0;j<guards[i].length&&!result.status;j++)if(code[j]!=guards[i].code[j])result.status=-84;
    }
    if(!result.status)result.status=get(mem,0x7e70598,&result.current_before,4);
    if(!result.status)result.status=get(mem,0x7eac508,result.before,72);
    u32 selected=0;
    for(u32 i=0;i<target_count&&!result.status;i++) {
        u32 index=targets[i].index;
        if(index<10||index>=18||targets[i].value>11||(selected&(1U<<index))) {result.status=-22;break;}
        selected|=1U<<index;
    }
    for(u32 i=0;i<target_count&&!result.status;i++) {
        u32 index=targets[i].index,value=targets[i].value;
        if(result.before[index]!=value) {set_base(index,value);result.changed|=1U<<index;}
    }
    if(!result.status)result.status=get(mem,0x7eac508,result.after,72);
    if(!result.status)result.status=get(mem,0x7e70598,&result.current_after,4);
    if(!result.status&&result.current_after!=result.current_before)result.status=-84;
    for(u32 i=0;i<18&&!result.status;i++)
        if(!(selected&(1U<<i))&&result.after[i]!=result.before[i])result.status=-84;
    for(u32 i=0;i<target_count&&!result.status;i++)
        if(result.after[targets[i].index]!=targets[i].value)result.status=-5;
    cl(mem);i64 fd=op("/tmp/jiritsu/a7c2.runtime.result",0x241);
    if(fd>=0) {write_all(fd,&result,sizeof(result));sc(82,fd,0,0,0,0,0);cl(fd);}
}
