/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Inferred PLL request model. No real oscillator/rates/IRQ or native LOCK.
 * Only fixture mode schedules a separate response, never silicon evidence.
 */
#include "qemu/timer.h"
#include "qemu/log.h"
#include "state.h"
typedef struct CpPllDevice CpPllDevice;
typedef struct { CpPllDevice *owner;unsigned slot;uint64_t generation;QEMUTimer *timer; } CpPllActor;
typedef struct { CpPllDevice *owner;bool select,logic;MemoryRegion mmio; } CpPllRegion;
struct CpPllDevice {
    CpLabPll state;bool fixture;uint64_t reads;
    CpPllActor actor[5];CpPllRegion region[3];
};
static void cp_pll_fixture_response(void *opaque)
{
    CpPllActor *a=opaque;
    if (cp_pll_actor_lock(&a->owner->state.slot[a->slot],a->generation)) {
        qemu_log_mask(LOG_UNIMP,"CP_PLL_FIXTURE_LOCK slot=%u generation=%"PRIu64" physical-qualified=0\n",a->slot,a->generation);
    }
}
static MemTxResult cp_pll_mmio_read(void *opaque,hwaddr offset,uint64_t *value,unsigned size,MemTxAttrs attrs)
{
    CpPllRegion *r=opaque;CpPllDevice *s=r->owner;uint32_t word=0;(void)attrs;
    bool ok=size==4 && (r->logic ? cp_pll_logic_read(&s->state,offset,&word) :
        r->select ? cp_pll_select_read(&s->state,offset,&word) : cp_pll_read(&s->state,offset,&word));
    *value=word;if (!ok) { return MEMTX_ERROR; }
    s->reads++;
    if (s->reads<=24 || !(s->reads&(s->reads-1))) {
        qemu_log_mask(LOG_UNIMP,"CP_PLL_READ select=%u offset=%"HWADDR_PRIx" value=%08x count=%"PRIu64" logic=%u\n",r->select,offset,word,s->reads,r->logic);
    }
    return MEMTX_OK;
}
static MemTxResult cp_pll_mmio_write(void *opaque,hwaddr offset,uint64_t value,unsigned size,MemTxAttrs attrs)
{
    CpPllRegion *r=opaque;CpPllDevice *s=r->owner;(void)attrs;
    bool ok=size==4 && (r->logic ? cp_pll_logic_write(&s->state,offset,value) :
        r->select ? cp_pll_select_write(&s->state,offset,value) : cp_pll_write(&s->state,offset,value));
    if (!ok) {
        qemu_log_mask(LOG_UNIMP,"CP_PLL_UNSUPPORTED select=%u offset=%"HWADDR_PRIx" value=%"PRIu64" size=%u logic=%u\n",r->select,offset,value,size,r->logic);
        return MEMTX_ERROR;
    }
    qemu_log_mask(LOG_UNIMP,"CP_PLL_WRITE select=%u offset=%"HWADDR_PRIx" value=%"PRIu64" logic=%u\n",r->select,offset,value,r->logic);
    if (!r->select && !r->logic && offset<=16) {
        unsigned slot=offset/4;CpPllSlot *p=&s->state.slot[slot];CpPllActor *a=&s->actor[slot];
        if (s->fixture && p->pending && (p->config&(CP_PLL_GATE|CP_PLL_START))==(CP_PLL_GATE|CP_PLL_START)) {
            a->generation=p->generation;timer_mod_ns(a->timer,qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL)+1000);
        } else { timer_del(a->timer); }
    }
    return MEMTX_OK;
}
static const MemoryRegionOps cp_pll_ops={
    .read_with_attrs=cp_pll_mmio_read,.write_with_attrs=cp_pll_mmio_write,
    .endianness=DEVICE_LITTLE_ENDIAN,
    .valid={.min_access_size=4,.max_access_size=4,.unaligned=false},
};
static void cp_lab_pll_init(MachineState *machine)
{
    const char *profile=g_getenv("QEMU_SONY_CP_PLL_PROFILE"),*alias=g_getenv("QEMU_SONY_CP_PLL_ALIAS");
    if (!profile) { return; }
    if (!alias || (strcmp(alias,"zero") && strcmp(alias,"ones")) ||
        (strcmp(profile,"absent") && strcmp(profile,"fixture"))) { error_report("Invalid PLL model profile");exit(1); }
    CpPllDevice *s=g_new0(CpPllDevice,1);s->fixture=!strcmp(profile,"fixture");
    s->state.alias_readback=!strcmp(alias,"ones") ? UINT32_MAX : 0;
    for (unsigned i=0;i<5;i++) {
        s->actor[i].owner=s;s->actor[i].slot=i;s->actor[i].timer=timer_new_ns(QEMU_CLOCK_VIRTUAL,cp_pll_fixture_response,&s->actor[i]);
    }
    const uint64_t bases[3]={0xf1388100,0xf1388200,0xf1388070},sizes[3]={0x5c,12,12};
    const char *names[3]={"cp-PLL-config","cp-PLL-select","cp-PLL-logic-bit22"};
    for (unsigned i=0;i<3;i++) {
        s->region[i].owner=s;s->region[i].select=i==1;s->region[i].logic=i==2;
        memory_region_init_io(&s->region[i].mmio,OBJECT(machine),&cp_pll_ops,&s->region[i],names[i],sizes[i]);
        memory_region_add_subregion(get_system_memory(),bases[i],&s->region[i].mmio);
    }
    g_printerr("CP_PLL_MODEL backend=%s alias=%s initial-config=0 inferred-response=1 no-rates-or-IRQ=1 physical-qualified=0\n",profile,alias);
}
