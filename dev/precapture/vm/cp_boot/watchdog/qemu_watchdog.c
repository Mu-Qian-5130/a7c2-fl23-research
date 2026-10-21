/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Separate offline board inclusion. Reset-mode DW-style watchdog contract;
 * no USB/camera I/O. IRQ mode, unconnected active output and other SCU bits
 * deliberately fault. Configure -watchdog-action pause to retain expiration.
 */
#include "system/watchdog.h"
#include "state.h"

typedef struct CpWdtDevice CpWdtDevice;
typedef struct { MemoryRegion mmio; CpWdtDevice *owner; unsigned kind; } CpWdtRegion;
struct CpWdtDevice {
    CpLabWatchdog state;
    CpWdtRegion region[3];
    QEMUTimer *timer;
    bool reported;
    uint64_t reads;
};

static void cp_wdt_schedule(CpWdtDevice *s)
{
    uint64_t deadline=cp_wdt_deadline(&s->state);
    if (deadline==UINT64_MAX) { timer_del(s->timer); }
    else { timer_mod_ns(s->timer,deadline); }
    if (s->state.expired && !s->reported) {
        s->reported=true;
        qemu_log_mask(LOG_UNIMP,"CP_WDT_RESET_REQUEST deadline=%"PRIu64" now=%"PRIu64"\n",
                      s->state.deadline,(uint64_t)qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL));
        watchdog_perform_action();
    }
}

static void cp_wdt_expire(void *opaque)
{
    CpWdtDevice *s=opaque;
    cp_wdt_advance(&s->state,qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL));
    cp_wdt_schedule(s);
}

static MemTxResult cp_wdt_mmio_read(void *opaque,hwaddr offset,uint64_t *value,
                                   unsigned size,MemTxAttrs attrs)
{
    CpWdtRegion *r=opaque;CpWdtDevice *s=r->owner;uint32_t word=0;bool ok=false;
    (void)attrs;
    if (size==4 && !(offset&3)) {
        if (r->kind==0 && offset<=16) {
            ok=cp_wdt_read(&s->state,offset,qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL),&word);
        } else if (r->kind==1 && offset==0) { word=s->state.reset;ok=true; }
        else if (r->kind==2 && offset==0) { word=s->state.misc;ok=true; }
    }
    if (!ok) {
        qemu_log_mask(LOG_UNIMP,"CP_WDT_UNSUPPORTED read region=%u offset=%"HWADDR_PRIx" size=%u\n",r->kind,offset,size);
        *value=0;return MEMTX_ERROR;
    }
    *value=word;s->reads++;
    if (s->reads<=16 || !(s->reads&(s->reads-1))) {
        qemu_log_mask(LOG_UNIMP,"CP_WDT_READ region=%u offset=%"HWADDR_PRIx" value=%u count=%"PRIu64"\n",r->kind,offset,word,s->reads);
    }
    cp_wdt_schedule(s);return MEMTX_OK;
}

static MemTxResult cp_wdt_mmio_write(void *opaque,hwaddr offset,uint64_t value,
                                    unsigned size,MemTxAttrs attrs)
{
    CpWdtRegion *r=opaque;CpWdtDevice *s=r->owner;bool ok=false;
    (void)attrs;
    if (size==4 && !(offset&3)) {
        if (r->kind==0 && offset<=16) {
            ok=cp_wdt_write(&s->state,offset,value,qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL));
        } else if (r->kind==1 && offset<=8) {
            ok=cp_wdt_reset_write(&s->state,offset,value);
            if (ok && s->state.reset) { s->reported=false; }
        } else if (r->kind==2 && offset==0 && !(value&~UINT64_C(1)) &&
                   (!cp_wdt_enabled(&s->state) || value==1)) {
            s->state.misc=value;ok=true;
        }
    }
    if (!ok) {
        qemu_log_mask(LOG_UNIMP,"CP_WDT_UNSUPPORTED write region=%u offset=%"HWADDR_PRIx" value=%"PRIu64" size=%u\n",r->kind,offset,value,size);
        return MEMTX_ERROR;
    }
    qemu_log_mask(LOG_UNIMP,"CP_WDT_WRITE region=%u offset=%"HWADDR_PRIx" value=%"PRIu64"\n",r->kind,offset,value);
    cp_wdt_schedule(s);return MEMTX_OK;
}

static const MemoryRegionOps cp_wdt_ops={
    .read_with_attrs=cp_wdt_mmio_read,.write_with_attrs=cp_wdt_mmio_write,
    .endianness=DEVICE_LITTLE_ENDIAN,
    .valid={.min_access_size=4,.max_access_size=4,.unaligned=false},
};

static void cp_lab_watchdog_init(MachineState *machine)
{
    const char *profile=g_getenv("QEMU_SONY_CP_WATCHDOG_PROFILE");
    if (!profile) { return; }
    if (strcmp(profile,"reset-mode")) { error_report("Unsupported watchdog lab profile");exit(1); }
    CpWdtDevice *s=g_new0(CpWdtDevice,1);s->state.tick_ns=250;
    s->timer=timer_new_ns(QEMU_CLOCK_VIRTUAL,cp_wdt_expire,s);
    const uint64_t bases[3]={0xf1052000,0xf1388340,0xf13883a0};
    const uint64_t sizes[3]={0x1000,12,4};
    const char *names[3]={"cp-lab-watchdog","cp-lab-watchdog-reset","cp-lab-watchdog-route"};
    for (unsigned i=0;i<3;i++) {
        s->region[i].owner=s;s->region[i].kind=i;
        memory_region_init_io(&s->region[i].mmio,OBJECT(machine),&cp_wdt_ops,&s->region[i],names[i],sizes[i]);
        memory_region_add_subregion(get_system_memory(),bases[i],&s->region[i].mmio);
    }
    g_printerr("CP_WDT_MODEL input-hz=4000000 mode=reset physical-routing-unqualified=1\n");
}
