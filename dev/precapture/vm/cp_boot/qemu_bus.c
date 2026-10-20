/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Based on the a7c2-re QEMU sony_cxd_bus_stub.c experiment.
 * Private negative/control policies for the existing catch-all shim.
 * Outside the source-qualified PCIe resource window legacy behavior remains.
 * Neither zero nor fault is a hardware model or CP-ready implementation.
 */
#include "qemu/osdep.h"
#include "qemu/log.h"
#include "qapi/error.h"
#include "hw/core/sysbus.h"
#include "hw/core/boards.h"
#include "system/address-spaces.h"

#define TYPE_SONY_CXD_BUS_STUB "sony-cxd-bus-stub"
OBJECT_DECLARE_SIMPLE_TYPE(SonyCxdBusStub, SONY_CXD_BUS_STUB)
struct SonyCxdBusStub {
    SysBusDevice parent_obj;
    MemoryRegion mmio;
    const char *policy;
    unsigned boot_bank, strap, strap_bit;
    MemoryRegion boot_alias, loader_ram, backup_state, logging_state, boot_state, gpio18;

    uint64_t reads, writes;
};
static bool selected(SonyCxdBusStub *s, hwaddr offset)
{
    /* Five PHY resources from the pinned kernel, plus five 4MiB controller
     * banks described by the retained native DTB's endpoint resources.
     * The latter also cover all five DMA bases (bank+0x380000).
     */
    return s->boot_bank || (offset >= 0x01100000 && offset < 0x01240000) ||
           (offset >= 0x06400000 && offset < 0x07800000);
}
static void observe(SonyCxdBusStub *s, hwaddr offset, unsigned size, bool write)
{
    uint64_t n = write ? ++s->writes : ++s->reads;
    if (n <= 64 || !(n & (n - 1))) {
        qemu_log_mask(LOG_UNIMP,
            "PRECAPTURE_PCIE_MMIO policy=%s op=%s address=0x%llx size=%u count=%llu\n",
            s->policy, write ? "write" : "read",
            (unsigned long long)(0xf0000000ULL + offset), size, (unsigned long long)n);
    }
}
static MemTxResult cxd_read(void *opaque, hwaddr offset, uint64_t *value,
                          unsigned size, MemTxAttrs attrs)
{
    SonyCxdBusStub *s = opaque;
    (void)attrs;
    if (selected(s, offset)) {
        observe(s, offset, size, false);
        if (!strcmp(s->policy, "fault")) {
            *value = 0;
            return MEMTX_ERROR;
        }
        if (!strcmp(s->policy, "zero")) {
            *value = 0;
            return MEMTX_OK;
        }
    }
    *value = 0xffffffff;
    return MEMTX_OK;
}
static MemTxResult cxd_write(void *opaque, hwaddr offset, uint64_t value,
                           unsigned size, MemTxAttrs attrs)
{
    SonyCxdBusStub *s = opaque;
    (void)value;
    (void)attrs;
    if (selected(s, offset)) {
        observe(s, offset, size, true);
        if (!strcmp(s->policy, "fault")) {
            return MEMTX_ERROR;
        }
    }
    return MEMTX_OK;
}
static const MemoryRegionOps cxd_ops = {
    .read_with_attrs = cxd_read,
    .write_with_attrs = cxd_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
};

/* Explicit laboratory memory topology. These aliases are experimental model
 * inputs, NOT a claim about the physical A7C II interconnect. The GPIO actor
 * exposes a separately configured input; it never writes EXEC_MODE/ready.
 */
static MemTxResult strap_read(void *opaque, hwaddr offset, uint64_t *value,
                             unsigned size, MemTxAttrs attrs)
{
    SonyCxdBusStub *s = opaque;
    (void)attrs;
    if (size != 4 || offset != 0x10) { return MEMTX_ERROR; }
    *value = s->strap << s->strap_bit;
    qemu_log_mask(LOG_UNIMP, "CP_BOOT_STRAP read input=0x%llx\n", (unsigned long long)*value);
    return MEMTX_OK;
}
static MemTxResult strap_write(void *opaque, hwaddr offset, uint64_t value,
                              unsigned size, MemTxAttrs attrs)
{
    SonyCxdBusStub *s = opaque;
    (void)attrs;
    if (size != 4 || (offset != 8 && offset != 0x24) || value != (1u << s->strap_bit)) {
        return MEMTX_ERROR;
    }
    qemu_log_mask(LOG_UNIMP, "CP_BOOT_STRAP configure offset=0x%llx mask=0x%llx\n",
                 (unsigned long long)offset, (unsigned long long)value);
    return MEMTX_OK;
}
static const MemoryRegionOps strap_ops = {
    .read_with_attrs = strap_read, .write_with_attrs = strap_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
};
static void boot_lab(SonyCxdBusStub *s)
{
    MachineState *machine = MACHINE(qdev_get_machine());
    MemoryRegion *system = get_system_memory();
    g_assert(machine->ram && memory_region_size(machine->ram) == 0x10000000);
    memory_region_init_alias(&s->boot_alias, OBJECT(s), "cp-boot-experimental-alias",
                             machine->ram, 0, memory_region_size(machine->ram));
    memory_region_add_subregion(system, (uint64_t)s->boot_bank << 32, &s->boot_alias);
    memory_region_init_ram(&s->loader_ram, OBJECT(s), "cp-boot-loader", 0x20000, &error_fatal);
    memory_region_add_subregion(system, 0xfe049000, &s->loader_ram);
    memory_region_init_ram(&s->backup_state, OBJECT(s), "cp-boot-backup-state", 0x1000, &error_fatal);
    memory_region_add_subregion(system, 0xfe26c000, &s->backup_state);
    memory_region_init_ram(&s->logging_state, OBJECT(s), "cp-boot-logging-state", 0x1000, &error_fatal);
    memory_region_add_subregion(system, 0xfe20c000, &s->logging_state);
    memory_region_init_ram(&s->boot_state, OBJECT(s), "cp-boot-shared-state", 0x1000, &error_fatal);
    memory_region_add_subregion(system, 0xfe170000, &s->boot_state);
    memory_region_init_io(&s->gpio18, OBJECT(s), &strap_ops, s, "cp-boot-GPIO18-input", 0x1000);
    memory_region_add_subregion(system, 0xf102f000, &s->gpio18);
    memory_region_add_subregion_overlap(system, 0xf0000000, &s->mmio, -1000);
    g_printerr("CP_BOOT_EXPERIMENT bank=%u strap=%u bit=%u physical_alias_unqualified=1\n",
               s->boot_bank, s->strap, s->strap_bit);
}

static void realize(DeviceState *dev, Error **errp)
{
    SonyCxdBusStub *s = SONY_CXD_BUS_STUB(dev);
    const char *bank = g_getenv("QEMU_SONY_CP_BOOT_BANK");
    if (bank) {
        const char *strap = g_getenv("QEMU_SONY_CP_BOOT_STRAP");
        const char *bit = g_getenv("QEMU_SONY_CP_BOOT_STRAP_BIT");
        if ((strcmp(bank, "4") && strcmp(bank, "8")) || !strap ||
            (strcmp(strap, "0") && strcmp(strap, "1")) || !bit ||
            (strcmp(bit, "3") && strcmp(bit, "9"))) {
            error_setg(errp, "Invalid isolated CP boot model inputs"); return;
        }
        s->boot_bank = bank[0] - '0'; s->strap = strap[0] - '0';
        s->strap_bit = bit[0] - '0';
    }
    s->policy = g_getenv("QEMU_SONY_PCIE_MMIO_MODE");
    if (!s->policy) {
        s->policy = "legacy";
    }
    if (strcmp(s->policy, "legacy") && strcmp(s->policy, "zero") &&
        strcmp(s->policy, "fault")) {
        error_setg(errp, "Invalid private PCIe MMIO control policy");
        return;
    }
    g_printerr("PRECAPTURE_PCIE_MMIO_POLICY=%s ranges=f1100000..f123ffff,f6400000..f77fffff\n", s->policy);
    memory_region_init_io(&s->mmio, OBJECT(dev), &cxd_ops, s,
                          TYPE_SONY_CXD_BUS_STUB, 0x10000000);
    sysbus_init_mmio(SYS_BUS_DEVICE(s), &s->mmio);
    if (s->boot_bank) { boot_lab(s); }
}
static void class_init(ObjectClass *klass, const void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);
    (void)data;
    dc->realize = realize;
    dc->user_creatable = true;
}
static const TypeInfo info = {
    .name = TYPE_SONY_CXD_BUS_STUB,
    .parent = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(SonyCxdBusStub),
    .class_init = class_init,
};
static void register_types(void)
{
    type_register_static(&info);
}
type_init(register_types)
