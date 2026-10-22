/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Optional one-word conditional fixture. No physical/reset/ready semantics. */
#include "qemu/log.h"
#include "system/dma.h"
#include "state.h"

typedef struct { CpConfigWord state;MemoryRegion mmio;uint64_t reads; } CpConfigDevice;
static bool cp_config_source_matches(void)
{
    uint8_t raw[86];
    if(dma_memory_read(&address_space_memory,0xb7160a,raw,36,MEMTXATTRS_UNSPECIFIED)!=MEMTX_OK ||
       dma_memory_read(&address_space_memory,0xb74730,raw+36,40,MEMTXATTRS_UNSPECIFIED)!=MEMTX_OK ||
       dma_memory_read(&address_space_memory,0x68530a,raw+76,10,MEMTXATTRS_UNSPECIFIED)!=MEMTX_OK) { return false; }
    g_autofree gchar *digest=g_compute_checksum_for_data(G_CHECKSUM_SHA256,raw,sizeof(raw));
    return !strcmp(digest,"81c6b09c1f94a7e872e03547f48f36a0f63bfaaa03c3c7b550f333ba95aaba2a");
}
static MemTxResult cp_config_mmio_read(void *opaque,hwaddr offset,uint64_t *value,unsigned size,MemTxAttrs attrs)
{
    CpConfigDevice *s=opaque;uint32_t word=0;(void)attrs;
    if(size!=4 || !cp_config_source_matches() || !cp_config_read(&s->state,offset,&word)) { *value=0;return MEMTX_ERROR; }
    *value=word;uint64_t n=++s->reads;
    if(n<=16 || !(n&(n-1))) { qemu_log_mask(LOG_UNIMP,"CP_CONFIG_READ value=%08x count=%"PRIu64" fixture-only=1\n",word,n); }
    return MEMTX_OK;
}
static MemTxResult cp_config_mmio_write(void *opaque,hwaddr offset,uint64_t value,unsigned size,MemTxAttrs attrs)
{
    CpConfigDevice *s=opaque;(void)attrs;
    if(size!=4 || !cp_config_source_matches() || !cp_config_write(&s->state,offset,value)) {
        qemu_log_mask(LOG_UNIMP,"CP_CONFIG_UNSUPPORTED offset=%"HWADDR_PRIx" value=%"PRIu64" size=%u\n",offset,value,size);return MEMTX_ERROR;
    }
    qemu_log_mask(LOG_UNIMP,"CP_CONFIG_WRITE requested=%08x hardware-confirmed=0\n",s->state.value);
    return MEMTX_OK;
}
static const MemoryRegionOps cp_config_ops={
    .read_with_attrs=cp_config_mmio_read,.write_with_attrs=cp_config_mmio_write,
    .endianness=DEVICE_LITTLE_ENDIAN,
    .valid={.min_access_size=4,.max_access_size=4,.unaligned=false},
};
static void cp_lab_config_word_init(MachineState *machine)
{
    const char *initial=g_getenv("QEMU_SONY_CP_CONFIG_INITIAL");
    if(!initial) { return; }
    if(strcmp(initial,"zero") && strcmp(initial,"ones")) {
        error_report("Configuration word requires explicit zero/ones fixture; no hardware reset default");exit(1);
    }
    CpConfigDevice *s=g_new0(CpConfigDevice,1);s->state.value=!strcmp(initial,"ones")?UINT32_MAX:0;
    memory_region_init_io(&s->mmio,OBJECT(machine),&cp_config_ops,s,"cp-config-fixture-word",4);
    memory_region_add_subregion(get_system_memory(),0xf5408038ULL,&s->mmio);
    g_printerr("CP_CONFIG_FIXTURE word=f5408038 mask=4000 initial=%s physical-qualified=0 guest-code-pinned=1\n",initial);
}
