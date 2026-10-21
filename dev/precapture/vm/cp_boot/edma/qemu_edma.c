/* SPDX-License-Identifier: GPL-2.0-or-later */
/* CP2.01-view non-LL eDMA laboratory. Peer fixture is a separate RAM actor,
 * not an AP Linux peer. Without it, transfers retain RUN and never complete.
 * Unsupported LL/STOP/link/ATU accesses fault instead of returning ready.
 */
#include "system/dma.h"
#include "system/runstate.h"
#include "state.h"

typedef struct CpEdmaDevice CpEdmaDevice;
typedef struct { MemoryRegion mmio;CpEdmaDevice *owner;bool side; } CpEdmaRegion;
struct CpEdmaDevice {
    CpEdma state;
    CpEdmaRegion region[2];
    MemoryRegion peer_ram;
    QEMUTimer *timer;
    qemu_irq irq;
    uint64_t local_size,reads;
    bool fixture,backend_unknown;
};
#define CP_EDMA_PEER_BASE UINT64_C(0x400000000)
#define CP_EDMA_PEER_ALIAS UINT64_C(0x40000000)
#define CP_EDMA_PEER_SIZE UINT64_C(0x100000)

static int cp_edma_copy_bytes(void *opaque,unsigned direction,uint64_t source,
                              uint64_t destination,uint32_t size,uint32_t *done)
{
    CpEdmaDevice *s=opaque;*done=0;
    if (!s->fixture || s->backend_unknown) { return CP_EDMA_WAIT; }
    uint64_t local=direction ? destination : source;
    uint64_t remote=direction ? source : destination;
    if (local>=s->local_size || remote<CP_EDMA_PEER_BASE || remote-CP_EDMA_PEER_BASE>=CP_EDMA_PEER_SIZE) {
        return CP_EDMA_ERROR;
    }
    remote-=CP_EDMA_PEER_BASE;
    uint32_t allowed=size;
    if (allowed>s->local_size-local) { allowed=s->local_size-local; }
    if (allowed>CP_EDMA_PEER_SIZE-remote) { allowed=CP_EDMA_PEER_SIZE-remote; }
    if (allowed>256) { return CP_EDMA_ERROR; }
    uint8_t bytes[256];
    uint64_t from=direction ? CP_EDMA_PEER_ALIAS+remote : local;
    uint64_t to=direction ? local : CP_EDMA_PEER_ALIAS+remote;
    /* Both admitted views are ordinary model RAM, never MMIO. Unexpected
     * backend errors retain the guest/active ownership, not a false byte count.
     */
    if (dma_memory_read(&address_space_memory,from,bytes,allowed,MEMTXATTRS_UNSPECIFIED)!=MEMTX_OK ||
        dma_memory_write(&address_space_memory,to,bytes,allowed,MEMTXATTRS_UNSPECIFIED)!=MEMTX_OK) {
        s->backend_unknown=true;
        qemu_log_mask(LOG_UNIMP,"CP_EDMA_BACKEND_UNKNOWN source=%"PRIx64" destination=%"PRIx64" size=%u\n",source,destination,allowed);
        qemu_system_vmstop_request(RUN_STATE_INTERNAL_ERROR);
        return CP_EDMA_WAIT;
    }
    *done=allowed;
    qemu_log_mask(LOG_UNIMP,"CP_EDMA_COPY direction=%u source=%"PRIx64" destination=%"PRIx64" bytes=%u\n",direction,source,destination,allowed);
    return allowed==size ? CP_EDMA_OK : CP_EDMA_ERROR;
}

static void cp_edma_schedule(CpEdmaDevice *s)
{
    qemu_set_irq(s->irq,cp_edma_irq(&s->state));
    if (cp_edma_active(&s->state) && s->fixture && !s->backend_unknown) {
        timer_mod_ns(s->timer,qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL)+1000);
    } else { timer_del(s->timer); }
}

static void cp_edma_tick(void *opaque)
{
    CpEdmaDevice *s=opaque;
    for (unsigned d=0;d<2;d++) for (unsigned c=0;c<8;c++) {
        cp_edma_progress(&s->state,d,c,256,cp_edma_copy_bytes,s);
    }
    cp_edma_schedule(s);
}

static MemTxResult cp_edma_mmio_read(void *opaque,hwaddr offset,uint64_t *value,
                                    unsigned size,MemTxAttrs attrs)
{
    CpEdmaRegion *r=opaque;CpEdmaDevice *s=r->owner;uint32_t word=0;bool ok=false;
    (void)attrs;
    if (size==4 && !(offset&3)) {
        if (r->side && offset==0) { word=s->state.side_enable;ok=true; }
        else if (!r->side && offset<0x2000) { ok=cp_edma_read(&s->state,offset,&word); }
    }
    if (!ok) {
        qemu_log_mask(LOG_UNIMP,"CP_EDMA_UNSUPPORTED read side=%u offset=%"HWADDR_PRIx" size=%u\n",r->side,offset,size);
        *value=0;return MEMTX_ERROR;
    }
    *value=word;s->reads++;
    if (s->reads<=24 || !(s->reads&(s->reads-1))) {
        qemu_log_mask(LOG_UNIMP,"CP_EDMA_READ side=%u offset=%"HWADDR_PRIx" value=%u count=%"PRIu64"\n",r->side,offset,word,s->reads);
    }
    return MEMTX_OK;
}

static MemTxResult cp_edma_mmio_write(void *opaque,hwaddr offset,uint64_t value,
                                     unsigned size,MemTxAttrs attrs)
{
    CpEdmaRegion *r=opaque;CpEdmaDevice *s=r->owner;bool ok=false;
    (void)attrs;
    if (size==4 && !(offset&3)) {
        if (r->side && offset==0) { s->state.side_enable=value;ok=true; }
        else if (!r->side && offset<0x2000) { ok=cp_edma_write(&s->state,offset,value); }
    }
    if (!ok) {
        qemu_log_mask(LOG_UNIMP,"CP_EDMA_UNSUPPORTED write side=%u offset=%"HWADDR_PRIx" value=%"PRIu64" size=%u\n",r->side,offset,value,size);
        return MEMTX_ERROR;
    }
    qemu_log_mask(LOG_UNIMP,"CP_EDMA_WRITE side=%u offset=%"HWADDR_PRIx" value=%"PRIu64"\n",r->side,offset,value);
    cp_edma_schedule(s);return MEMTX_OK;
}

static const MemoryRegionOps cp_edma_ops={
    .read_with_attrs=cp_edma_mmio_read,.write_with_attrs=cp_edma_mmio_write,
    .endianness=DEVICE_LITTLE_ENDIAN,
    .valid={.min_access_size=4,.max_access_size=4,.unaligned=false},
};

static void cp_lab_edma_init(MachineState *machine,DeviceState *gic)
{
    const char *profile=g_getenv("QEMU_SONY_CP_EDMA_PROFILE");
    if (!profile) { return; }
    if (strcmp(profile,"absent") && strcmp(profile,"fixture")) { error_report("Unsupported CP eDMA model profile");exit(1); }
    CpEdmaDevice *s=g_new0(CpEdmaDevice,1);
    s->local_size=memory_region_size(machine->ram);s->fixture=!strcmp(profile,"fixture");
    s->state.mask[0]=s->state.mask[1]=UINT32_MAX;
    s->irq=qdev_get_gpio_in(gic,403-32); /* original CP data descriptor, not AP header IRQ */
    s->timer=timer_new_ns(QEMU_CLOCK_VIRTUAL,cp_edma_tick,s);
    const uint64_t bases[2]={0xf6780000,0xf11e0274},sizes[2]={0x2000,4};
    const char *names[2]={"cp-lab-edma","cp-lab-edma-sideband-enable"};
    for (unsigned i=0;i<2;i++) {
        s->region[i].owner=s;s->region[i].side=i!=0;
        memory_region_init_io(&s->region[i].mmio,OBJECT(machine),&cp_edma_ops,&s->region[i],names[i],sizes[i]);
        memory_region_add_subregion(get_system_memory(),bases[i],&s->region[i].mmio);
    }
    if (s->fixture) {
        memory_region_init_ram_flags_nomigrate(&s->peer_ram,OBJECT(machine),"explicit-edma-peer-fixture",CP_EDMA_PEER_SIZE,0,&error_fatal);
        memory_region_add_subregion(get_system_memory(),CP_EDMA_PEER_ALIAS,&s->peer_ram);
    }
    g_printerr("CP_EDMA_MODEL profile=%s irq=403 side=F11E0274 dma=F6780000 peer-is-not-AP=1 physical-qualified=0\n",profile);
}
