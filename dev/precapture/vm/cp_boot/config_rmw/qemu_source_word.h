/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Shared explicit-input word fixture. No default reset state or ready/IRQ. */
#ifndef CP_LAB_QEMU_SOURCE_WORD_H
#define CP_LAB_QEMU_SOURCE_WORD_H
#include "qemu/log.h"
#include "state.h"

typedef struct {
    CpConfigWord state;
    MemoryRegion mmio;
    uint64_t reads;
    uint32_t mask;
    const char *tag;
    bool (*source_matches)(void);
} CpSourceWord;
static MemTxResult cp_source_word_read(void *opaque,hwaddr offset,uint64_t *value,unsigned size,MemTxAttrs attrs)
{
    CpSourceWord *s=opaque;uint32_t word=0;(void)attrs;
    if(size!=4 || !s->source_matches() || !cp_config_read(&s->state,offset,&word)) { *value=0;return MEMTX_ERROR; }
    *value=word;uint64_t n=++s->reads;
    if(n<=16 || !(n&(n-1))) { qemu_log_mask(LOG_UNIMP,"%s_READ value=%08x count=%"PRIu64" fixture-only=1\n",s->tag,word,n); }
    return MEMTX_OK;
}
static MemTxResult cp_source_word_write(void *opaque,hwaddr offset,uint64_t value,unsigned size,MemTxAttrs attrs)
{
    CpSourceWord *s=opaque;(void)attrs;
    if(size!=4 || !s->source_matches() || !cp_config_write_masked(&s->state,offset,value,s->mask)) {
        qemu_log_mask(LOG_UNIMP,"%s_UNSUPPORTED offset=%"HWADDR_PRIx" value=%"PRIu64" size=%u\n",s->tag,offset,value,size);return MEMTX_ERROR;
    }
    qemu_log_mask(LOG_UNIMP,"%s_WRITE requested=%08x hardware-confirmed=0\n",s->tag,s->state.value);
    return MEMTX_OK;
}
static const MemoryRegionOps cp_source_word_ops={
    .read_with_attrs=cp_source_word_read,.write_with_attrs=cp_source_word_write,
    .endianness=DEVICE_LITTLE_ENDIAN,
    .valid={.min_access_size=4,.max_access_size=4,.unaligned=false},
};
static void cp_lab_source_word_init(MachineState *machine,const char *environment,
    hwaddr address,uint32_t mask,const char *tag,const char *region,bool (*source_matches)(void))
{
    const char *initial=g_getenv(environment);
    if(!initial) { return; }
    if(strcmp(initial,"zero") && strcmp(initial,"ones")) {
        error_report("Configuration word requires explicit zero/ones fixture; no hardware reset default");exit(1);
    }
    if(!mask || !source_matches) { error_report("Unqualified configuration field");exit(1); }
    CpSourceWord *s=g_new0(CpSourceWord,1);
    s->state.value=!strcmp(initial,"ones")?UINT32_MAX:0;
    s->mask=mask;s->tag=tag;s->source_matches=source_matches;
    memory_region_init_io(&s->mmio,OBJECT(machine),&cp_source_word_ops,s,region,4);
    memory_region_add_subregion(get_system_memory(),address,&s->mmio);
    g_printerr("%s_FIXTURE word=%"HWADDR_PRIx" mask=%x initial=%s physical-qualified=0 guest-code-pinned=1\n",tag,address,mask,initial);
}
#endif
