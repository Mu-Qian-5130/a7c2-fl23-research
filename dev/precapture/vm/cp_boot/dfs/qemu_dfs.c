/* SPDX-License-Identifier: GPL-2.0-or-later */
/* CP-view inferred register protocol. No IRQ wiring or clock-rate changes.
 * Fixture completion is a separate model actor, never native hardware proof.
 */
#include "qemu/timer.h"
#include "qemu/log.h"
#include "state.h"
typedef struct {
    CpLabDfs state;
    MemoryRegion mmio;
    QEMUTimer *timer;
    bool fixture;
    uint64_t reads;
} CpDfsDevice;
static void cp_dfs_fixture_complete(void *opaque)
{
    CpDfsDevice *s=opaque;
    if (!cp_dfs_actor_complete(&s->state)) { return; }
    qemu_log_mask(LOG_UNIMP,"CP_DFS_FIXTURE_COMPLETE command=%x result=%x physical-clock-unqualified=1\n",s->state.command,s->state.result);
}
static MemTxResult cp_dfs_mmio_read(void *opaque,hwaddr offset,uint64_t *value,
                                  unsigned size,MemTxAttrs attrs)
{
    CpDfsDevice *s=opaque;uint32_t word=0;(void)attrs;
    if (size!=4 || !cp_dfs_read(&s->state,offset,&word)) { *value=0;return MEMTX_ERROR; }
    *value=word;s->reads++;
    if (s->reads<=24 || !(s->reads&(s->reads-1))) {
        qemu_log_mask(LOG_UNIMP,"CP_DFS_READ offset=%"HWADDR_PRIx" value=%x active=%u count=%"PRIu64"\n",offset,word,s->state.active,s->reads);
    }
    return MEMTX_OK;
}
static MemTxResult cp_dfs_mmio_write(void *opaque,hwaddr offset,uint64_t value,
                                   unsigned size,MemTxAttrs attrs)
{
    CpDfsDevice *s=opaque;(void)attrs;
    if (size!=4 || !cp_dfs_write(&s->state,offset,value)) {
        qemu_log_mask(LOG_UNIMP,"CP_DFS_UNSUPPORTED offset=%"HWADDR_PRIx" value=%"PRIu64" size=%u\n",offset,value,size);
        return MEMTX_ERROR;
    }
    qemu_log_mask(LOG_UNIMP,"CP_DFS_WRITE offset=%"HWADDR_PRIx" value=%"PRIu64" active=%u starts=%"PRIu64"\n",offset,value,s->state.active,s->state.starts);
    if (offset==8 && s->fixture) {
        timer_mod_ns(s->timer,qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL)+1000);
    }
    return MEMTX_OK;
}
static const MemoryRegionOps cp_dfs_ops={
    .read_with_attrs=cp_dfs_mmio_read,.write_with_attrs=cp_dfs_mmio_write,
    .endianness=DEVICE_LITTLE_ENDIAN,
    .valid={.min_access_size=4,.max_access_size=4,.unaligned=false},
};
static void cp_lab_dfs_init(MachineState *machine)
{
    const char *profile=g_getenv("QEMU_SONY_CP_DFS_PROFILE");
    if (!profile) { return; }
    if (strcmp(profile,"absent") && strcmp(profile,"fixture")) { error_report("Invalid CP DFS protocol profile");exit(1); }
    CpDfsDevice *s=g_new0(CpDfsDevice,1);s->fixture=!strcmp(profile,"fixture");
    s->timer=timer_new_ns(QEMU_CLOCK_VIRTUAL,cp_dfs_fixture_complete,s);
    memory_region_init_io(&s->mmio,OBJECT(machine),&cp_dfs_ops,s,"cp-lab-dfs-protocol",20);
    memory_region_add_subregion(get_system_memory(),0xf1388f48,&s->mmio);
    g_printerr("CP_DFS_MODEL profile=%s base=F1388F48 inferred-protocol=1 no-clock-change=1 no-IRQ-route=1 physical-qualified=0\n",profile);
}
