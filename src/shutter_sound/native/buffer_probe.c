/* Temporary AP/CP sound-buffer research. The default only allocates/releases.
 * BUFFER_TRANSFER adds owned-buffer mapping and a DMA byte round trip.
 * BUFFER_REGISTER then retains CP storage and temporarily registers kind3 LPCM.
 * No playback request, firmware, settings or retained-image writes.
 * The original allocator/release are synchronous and may wait indefinitely.
 * A lost outcome must never be retried; cold power-off clears these leases.
 */
#define _init buffer_base_init
#include "probe.c"
#undef _init
#include PATCH_MANIFEST

struct Allocation {u32 type,handle;u64 address;u32 size,offset,status,pad;};
struct BufferReport {
    u8 magic[8];u32 version,phase;i64 status;
    struct Allocation ap,cp;u32 ap_release,cp_release,ap_called,cp_called;
    u32 ap_release_called,cp_release_called;
#ifdef BUFFER_TRANSFER
    u32 forward_status,reverse_status,mapping_status,unmap_status;
    u32 compared,payload_length,transfer_called,retain_leases;
#endif
#ifdef BUFFER_REGISTER
    u8 original_entry[48];
    u32 unregister_status,register_status,restore_status,cp_retained;
#endif
};
static struct BufferReport result;
_Static_assert(sizeof(struct Allocation)==32,"Native DMM allocation ABI");
#ifdef BUFFER_REGISTER
_Static_assert(sizeof(struct BufferReport)==208,"Temporary registration report ABI");
#elif defined(BUFFER_TRANSFER)
_Static_assert(sizeof(struct BufferReport)==144,"DMA trial report ABI");
#else
_Static_assert(sizeof(struct BufferReport)==112,"Buffer trial report ABI");
#endif
static void flush(void) {
    i64 fd=op("/tmp/jiritsu/shutter.probe.result",0x241);
    if(fd>=0) {write_all(fd,&result,sizeof(result));sc(82,fd,0,0,0,0,0);cl(fd);}
}
static int check(i64 fd,u64 at,const u8 *expected,u32 size) {
    u8 code[64];
    if(size>sizeof(code)||sc(67,fd,(i64)code,size,report.base+at,0,0)!=(i64)size)return 0;
    for(u32 i=0;i<size;i++)if(code[i]!=expected[i])return 0;
    return 1;
}
static int valid(const struct Allocation*a,u32 remote) {
    return !a->status&&a->type==0x70817&&a->handle!=0xffffffffU&&
        !!(a->handle&0x8000)==!!remote&&a->address&&a->size>=64&&
        a->size<=51200&&!a->offset;
}
__attribute__((visibility("default"))) void _init(void) {
    buffer_base_init();
#ifdef BUFFER_REGISTER
    const u8 magic[]="A7PCM001";
    result.unregister_status=result.register_status=result.restore_status=0xffffffffU;
#elif defined(BUFFER_TRANSFER)
    const u8 magic[]="A7DMA001";
#else
    const u8 magic[]="A7BUF001";
#endif
#ifdef BUFFER_TRANSFER
    result.forward_status=result.reverse_status=result.mapping_status=result.unmap_status=0xffffffffU;
    result.payload_length=sizeof(payload);
#endif
    for(u32 i=0;i<8;i++)result.magic[i]=magic[i];
    result.version=1;result.status=report.status;
    result.ap.status=result.cp.status=0xffffffffU;
    result.ap_release=result.cp_release=0xffffffffU;
    if(!result.status&&(report.index!=16||report.euid))result.status=-22;
    i64 fd=-1;
    if(!result.status) {fd=op("/proc/self/mem",0);if(fd<0)result.status=fd;}
    if(!result.status&&(!check(fd,0x3552790,alloc_code,sizeof(alloc_code))||
                       !check(fd,0x3552978,release_code,sizeof(release_code))))result.status=-84;
#ifdef BUFFER_TRANSFER
    if(!result.status&&!check(fd,0x3514f54,transfer_code,sizeof(transfer_code)))result.status=-84;
#endif
#ifdef BUFFER_REGISTER
    u32 audio=~0U;
    if(!result.status&&(!check(fd,0x34ec05c,register_code,sizeof(register_code))||
        !check(fd,0x2885488,table_code,sizeof(table_code))))result.status=-84;
    if(!result.status&&sc(67,fd,(i64)&audio,4,report.base+0x7e735b8UL,0,0)!=4)result.status=-5;
    if(!result.status&&sc(67,fd,(i64)result.original_entry,48,report.base+0x7ed21f8UL,0,0)!=48)result.status=-5;
    if(!result.status&&(audio||result.original_entry[0]!=6||result.original_entry[1]!=3||
        !*(u64*)(result.original_entry+16)||!*(u64*)(result.original_entry+32)))result.status=-71;
    /* The marker can survive a cold power cycle. Only the host may retire an
     * exact known-attempt marker after owner-confirmed recovery; no blind reset. */
    if(!result.status) {
        i64 lease=op("/tmp/jiritsu/shutter.custom.lease",0xc1);
        if(lease<0)result.status=lease;
        else {
            if(write_all(lease,&result,sizeof(result)))result.status=-5;
            if(!result.status&&write_all(lease,lease_token,sizeof(lease_token)))result.status=-5;
            if(sc(82,lease,0,0,0,0,0)&&!result.status)result.status=-5;
            cl(lease);
        }
    }
#endif
    cl(fd);result.phase=1;flush();
    if(result.status)return;
    typedef void (*Allocate)(const u32*,struct Allocation*);
    typedef void (*Release)(const u32*,u32*);
    Allocate alloc=(Allocate)(report.base+0x3552790UL);
    Release release=(Release)(report.base+0x3552978UL);
    u32 request[2]={0x70817,0};
    result.phase=2;result.ap_called=1;flush();
    alloc(request,&result.ap);result.phase=3;flush();
    if(!valid(&result.ap,0))result.status=-71;
    if(!result.status) {
        request[1]=1;result.phase=4;result.cp_called=1;flush();
        alloc(request,&result.cp);result.phase=5;flush();
        if(!valid(&result.cp,1))result.status=-71;
    }
#ifdef BUFFER_TRANSFER
    if(!result.status&&(sizeof(payload)>result.ap.size||sizeof(payload)>result.cp.size))result.status=-75;
    if(!result.status) {
        /* Map only the physical AP allocation just granted to this trial.
         * Match the original sound loader's /dev/mem O_RDWR|O_SYNC mapping. */
        i64 mem=op("/dev/mem",0x101002);
        u64 offset=result.ap.address&4095UL;
        u64 bytes=(offset+sizeof(payload)+4095UL)&~4095UL;
        i64 mapping=mem<0?mem:sc(222,0,bytes,3,1,mem,result.ap.address-offset);
        cl(mem);
        result.mapping_status=(mapping<0&&(u64)mapping>=~4095UL)?1:0;
        if(result.mapping_status)result.status=-12;
        else {
            volatile u8 *data=(volatile u8*)((u64)mapping+offset);
            for(u32 i=0;i<sizeof(payload);i++)data[i]=payload[i];
            typedef void (*Transfer)(const u32*,u32*);
            Transfer transfer=(Transfer)(report.base+0x3514f54UL);
            u32 args[5]={result.ap.handle,0,result.cp.handle,0,sizeof(payload)};
            result.phase=11;result.transfer_called=1;result.retain_leases=1;flush();
            transfer(args,&result.forward_status);result.phase=12;flush();
            if(result.forward_status)result.status=-5;
            else {
                for(u32 i=0;i<sizeof(payload);i++)data[i]=0;
                args[0]=result.cp.handle;args[2]=result.ap.handle;
                result.phase=13;flush();
                transfer(args,&result.reverse_status);result.phase=14;flush();
                if(result.reverse_status)result.status=-5;
                else {
                    result.compared=1;
                    for(u32 i=0;i<sizeof(payload);i++)if(data[i]!=payload[i])result.compared=0;
                    if(!result.compared)result.status=-84;
                    /* Both original synchronous calls returned completion.
                     * No registration, playback or other consumer received
                     * these buffers. They can now be released even on a
                     * byte comparison failure. */
                    result.retain_leases=0;
                }
            }
            result.unmap_status=sc(215,mapping,bytes,0,0,0,0)?1:0;
            if(result.unmap_status&&!result.status)result.status=-5;
        }
    }
    if(result.retain_leases) {result.phase=15;flush();return;}
#endif
#ifdef BUFFER_REGISTER
    if(!result.status&&result.compared) {
        struct Registration {
            u32 enabled,kind;u64 address,length;
            u32 priority,format,continuous,loop,first,pad;
        } old={0},custom={0};
        _Static_assert(sizeof(struct Registration)==48,"Native registration source ABI");
        old.enabled=1;old.kind=3;old.priority=result.original_entry[0];
        old.address=*(u64*)(result.original_entry+32);
        old.length=*(u64*)(result.original_entry+16);
        old.loop=*(u32*)(result.original_entry+8);
        old.first=*(u32*)(result.original_entry+4);old.continuous=!!old.loop;
        custom.kind=3;
        typedef void (*Register)(const struct Registration*,u32*);
        Register reg=(Register)(report.base+0x34ec05cUL);
        result.phase=16;result.cp_retained=1;flush();
        reg(&custom,&result.unregister_status);result.phase=17;flush();
        if(result.unregister_status)result.status=-5;
        else {
            custom.enabled=1;custom.address=result.cp.address;
            custom.length=sizeof(payload);custom.priority=6;custom.format=REGISTER_WIRE_FORMAT;
            result.phase=18;flush();
            reg(&custom,&result.register_status);result.phase=19;flush();
            if(result.register_status) {
                result.status=-5;
                reg(&old,&result.restore_status);flush();
            }
        }
    }
#endif
    /* Only successful allocations no longer referenced by a consumer or
     * an unfinished transfer are eligible for one release call. */
    if(result.cp_called&&!result.cp.status&&result.cp.handle!=0xffffffffU
#ifdef BUFFER_REGISTER
        &&!result.cp_retained
#endif
    ) {
        result.phase=6;result.cp_release_called=1;flush();
        release(&result.cp.handle,&result.cp_release);result.phase=7;flush();
        if(result.cp_release&&!result.status)result.status=-5;
    }
    if(result.ap_called&&!result.ap.status&&result.ap.handle!=0xffffffffU) {
        result.phase=8;result.ap_release_called=1;flush();
        release(&result.ap.handle,&result.ap_release);result.phase=9;flush();
        if(result.ap_release&&!result.status)result.status=-5;
    }
    result.phase=10;flush();
}
