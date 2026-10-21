/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Included in the separate offline none-machine object. No physical I/O.
 * Register layout is independently sourced; mode2, input4MHz and CP SPI413
 * are declared laboratory assumptions, not a qualified Sony hardware model.
 */
#include "qemu/timer.h"
#include "qemu/log.h"
#include "hw/core/irq.h"
#include "counter.h"

typedef struct {
    CpLabCounter state;
    MemoryRegion mmio;
    QEMUTimer *timer;
    qemu_irq irq;
    unsigned bank;
    uint64_t reads;
} CpLabGpt;

static void cp_gpt_schedule(CpLabGpt *s)
{
    uint64_t at = cp_counter_deadline(&s->state);
    qemu_set_irq(s->irq, cp_counter_irq(&s->state));
    if (at == UINT64_MAX) { timer_del(s->timer); }
    else { timer_mod_ns(s->timer, at); }
}

static void cp_gpt_expire(void *opaque)
{
    CpLabGpt *s = opaque;
    cp_counter_advance(&s->state, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL));
    qemu_log_mask(LOG_UNIMP,
                  "CP_GPT_EXPIRE bank=%u count=%u compare=%u pending=%u\n",
                  s->bank,s->state.count,s->state.compare,s->state.pending);
    cp_gpt_schedule(s);
}

static MemTxResult cp_gpt_read(void *opaque, hwaddr offset, uint64_t *value,
                              unsigned size, MemTxAttrs attrs)
{
    CpLabGpt *s=opaque;
    uint32_t word;
    (void)attrs;
    if (size != 4 || (offset & 3) || offset > 16 ||
        !cp_counter_read(&s->state,offset,qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL),&word)) {
        qemu_log_mask(LOG_UNIMP,"CP_GPT_UNSUPPORTED read bank=%u offset=%"HWADDR_PRIx" size=%u\n",s->bank,offset,size);
        *value=0; return MEMTX_ERROR;
    }
    *value=word;
    s->reads++;
    if (s->reads<=16 || !(s->reads & (s->reads-1))) {
        qemu_log_mask(LOG_UNIMP,"CP_GPT_READ bank=%u offset=%"HWADDR_PRIx" value=%u count=%"PRIu64"\n",s->bank,offset,word,s->reads);
    }
    cp_gpt_schedule(s);
    return MEMTX_OK;
}

static MemTxResult cp_gpt_write(void *opaque, hwaddr offset, uint64_t value,
                               unsigned size, MemTxAttrs attrs)
{
    CpLabGpt *s=opaque;
    (void)attrs;
    if (size != 4 || (offset & 3) || offset > 16 ||
        !cp_counter_write(&s->state,offset,value,qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL))) {
        qemu_log_mask(LOG_UNIMP,"CP_GPT_UNSUPPORTED write bank=%u offset=%"HWADDR_PRIx" value=%"PRIu64" size=%u\n",s->bank,offset,value,size);
        return MEMTX_ERROR;
    }
    qemu_log_mask(LOG_UNIMP,"CP_GPT_WRITE bank=%u offset=%"HWADDR_PRIx" value=%"PRIu64"\n",s->bank,offset,value);
    cp_gpt_schedule(s);
    return MEMTX_OK;
}

static const MemoryRegionOps cp_gpt_ops = {
    .read_with_attrs=cp_gpt_read, .write_with_attrs=cp_gpt_write,
    .endianness=DEVICE_LITTLE_ENDIAN,
    .valid={.min_access_size=4,.max_access_size=4,.unaligned=false},
};

static void cp_lab_gptimer_init(MachineState *machine, DeviceState *gic)
{
    const char *profile=g_getenv("QEMU_SONY_CP_GPTIMER_PROFILE");
    if (!profile) { return; }
    if (strcmp(profile,"cp-inferred") && strcmp(profile,"wrong-route")) {
        error_report("Unsupported explicit GPT laboratory profile"); exit(1);
    }
    for (unsigned i=0;i<4;i++) {
        CpLabGpt *s=g_new0(CpLabGpt,1);
        s->bank=i;
        s->state.base_tick_ns=250; /* explicit input4MHz, divider2 ->1MHz */
        s->state.anchor_ns=qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
        unsigned id=(!strcmp(profile,"wrong-route") ? 417 : 413)+i;
        s->irq=qdev_get_gpio_in(gic,id-32);
        s->timer=timer_new_ns(QEMU_CLOCK_VIRTUAL,cp_gpt_expire,s);
        char *name=g_strdup_printf("cp-lab-gpt-%u",i);
        memory_region_init_io(&s->mmio,OBJECT(machine),&cp_gpt_ops,s,name,0x1000);
        g_free(name);
        memory_region_add_subregion(get_system_memory(),0xf1042000+i*0x1000,&s->mmio);
    }
    g_printerr("CP_GPT_MODEL profile=%s banks=4 input-hz=4000000 mode2-inferred=1 physical-qualification=0\n",profile);
}
