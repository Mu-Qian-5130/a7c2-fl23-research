/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Source-bound SPI selector storage; alias words are explicit model inputs.
 * No clock frequency, hardware synchronization or device-ready state supplied.
 */
#include "qemu/log.h"
#include "state.h"
typedef struct { CpSpiSelect state;MemoryRegion mmio;uint64_t reads; } CpSpiSelectDevice;
static MemTxResult cp_spi_select_mmio_read(void *opaque,hwaddr offset,uint64_t *value,
                                         unsigned size,MemTxAttrs attrs)
{
    CpSpiSelectDevice *s=opaque;uint32_t word=0;(void)attrs;
    if (size!=4 || !cp_spi_select_read(&s->state,offset,&word)) { *value=0;return MEMTX_ERROR; }
    *value=word;s->reads++;
    if (s->reads<=24 || !(s->reads&(s->reads-1))) {
        qemu_log_mask(LOG_UNIMP,"CP_SPI_SELECT_READ offset=%"HWADDR_PRIx" value=%08x count=%"PRIu64"\n",offset,word,s->reads);
    }
    return MEMTX_OK;
}
static MemTxResult cp_spi_select_mmio_write(void *opaque,hwaddr offset,uint64_t value,
                                          unsigned size,MemTxAttrs attrs)
{
    CpSpiSelectDevice *s=opaque;(void)attrs;
    if (size!=4 || !cp_spi_select_write(&s->state,offset,value)) {
        qemu_log_mask(LOG_UNIMP,"CP_SPI_SELECT_UNSUPPORTED offset=%"HWADDR_PRIx" value=%"PRIu64" size=%u\n",offset,value,size);
        return MEMTX_ERROR;
    }
    qemu_log_mask(LOG_UNIMP,"CP_SPI_SELECT_WRITE offset=%"HWADDR_PRIx" value=%"PRIu64" selection=%08x\n",offset,value,s->state.selection);
    return MEMTX_OK;
}
static const MemoryRegionOps cp_spi_select_ops={
    .read_with_attrs=cp_spi_select_mmio_read,.write_with_attrs=cp_spi_select_mmio_write,
    .endianness=DEVICE_LITTLE_ENDIAN,
    .valid={.min_access_size=4,.max_access_size=4,.unaligned=false},
};
static void cp_lab_spi_select_init(MachineState *machine)
{
    const char *profile=g_getenv("QEMU_SONY_CP_SPI_SELECT_PROFILE");
    if (!profile) { return; }
    if (strcmp(profile,"zero") && strcmp(profile,"ones")) { error_report("Invalid SPI alias-readback fixture");exit(1); }
    CpSpiSelectDevice *s=g_new0(CpSpiSelectDevice,1);
    s->state.alias_readback=!strcmp(profile,"ones") ? UINT32_MAX : 0;
    memory_region_init_io(&s->mmio,OBJECT(machine),&cp_spi_select_ops,s,"cp-lab-SPI-select",12);
    memory_region_add_subregion(get_system_memory(),0xf1388230,&s->mmio);
    g_printerr("CP_SPI_SELECT_MODEL alias-word=%s initial-selection=0 mask=30777 no-clock-or-ready=1 physical-qualified=0\n",profile);
}
