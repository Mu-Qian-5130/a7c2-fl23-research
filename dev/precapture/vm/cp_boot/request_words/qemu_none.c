/*
 * Empty machine
 *
 * Copyright IBM, Corp. 2012
 *
 * Authors:
 *  Anthony Liguori   <aliguori@us.ibm.com>
 *
 * This work is licensed under the terms of the GNU GPL, version 2 or later.
 * See the COPYING file in the top-level directory.
 *
 */

#include "qemu/osdep.h"
#include "qemu/error-report.h"
#include "hw/core/boards.h"
#include "system/address-spaces.h"
#include "qapi/error.h"
#include "hw/core/cpu.h"
#include "hw/core/sysbus.h"
#include "hw/core/qdev-properties.h"
#include "target/arm/cpu-qom.h"
#include "target/arm/gtimer.h"
#include "hw/arm/machines-qom.h"
#include "hw/riscv/machines-qom.h"

#include "../gptimer/qemu_counter.c"
#include "../watchdog/qemu_watchdog.c"
#include "../edma/qemu_edma.c"
#include "../i2c/qemu_i2c.c"
#include "../dfs/qemu_dfs.c"
#include "../spiclock/qemu_spiclock.c"
#include "../pll/qemu_pll.c"
#include "qemu_requests.c"
#ifdef CP_LAB_CONFIG_WORD
#include "../config_rmw/qemu_config.c"
#endif

static void machine_none_init(MachineState *mch)
{
    CPUState *cpu = NULL;

    /* Initialize CPU (if user asked for it) */
    if (mch->cpu_type) {
        for (unsigned i = 0; i < mch->smp.cpus; i++) {
            cpu = cpu_create(mch->cpu_type);
            if (!cpu) {
                error_report("Unable to initialize CPU");
                exit(1);
            }
        }
    }

    /* RAM at address zero */
    if (mch->ram) {
        memory_region_add_subregion(get_system_memory(), 0, mch->ram);
    }

    /* Explicit isolated CP laboratory board. GICv2 semantics are QEMU's
     * standard implementation. Addresses match the retained CXD source;
     * CPU/interrupt counts remain model inputs, not measured body values.
     */
    if (g_getenv("QEMU_SONY_CP_BOOT_BANK")) {
        DeviceState *gic = qdev_new("arm_gic");
        qdev_prop_set_uint32(gic, "revision", 2);
        qdev_prop_set_uint32(gic, "num-cpu", mch->smp.cpus);
        qdev_prop_set_uint32(gic, "num-irq", 512);
        qdev_prop_set_bit(gic, "has-security-extensions", true);
        qdev_prop_set_bit(gic, "has-virtualization-extensions", false);
        SysBusDevice *bus = SYS_BUS_DEVICE(gic);
        sysbus_realize_and_unref(bus, &error_fatal);
        sysbus_mmio_map(bus, 0, 0xf13a1000);
        sysbus_mmio_map(bus, 1, 0xf13a2000);
        const char *route = g_getenv("QEMU_SONY_CP_TIMER_ROUTE");
        if (!route) { route = "none"; }
        if (strcmp(route, "none") && strcmp(route, "standard") &&
            strcmp(route, "secure-only") && strcmp(route, "phys-only")) {
            error_report("Invalid explicit CP timer routing model"); exit(1);
        }
        cp_lab_gptimer_init(mch,gic);
        cp_lab_watchdog_init(mch);
        cp_lab_edma_init(mch,gic);
        cp_lab_i2c_init(mch,gic);
        cp_lab_dfs_init(mch);
        cp_lab_spi_select_init(mch);
        cp_lab_pll_init(mch);
        cp_lab_request_words_init(mch);
#ifdef CP_LAB_CONFIG_WORD
        cp_lab_config_word_init(mch);
#endif
        for (unsigned i = 0; i < mch->smp.cpus; i++) {
            DeviceState *core = DEVICE(qemu_get_cpu(i));
            sysbus_connect_irq(bus, i, qdev_get_gpio_in(core, ARM_CPU_IRQ));
            sysbus_connect_irq(bus, i + mch->smp.cpus, qdev_get_gpio_in(core, ARM_CPU_FIQ));
            sysbus_connect_irq(bus, i + 2*mch->smp.cpus, qdev_get_gpio_in(core, ARM_CPU_VIRQ));
            sysbus_connect_irq(bus, i + 3*mch->smp.cpus, qdev_get_gpio_in(core, ARM_CPU_VFIQ));
            unsigned ppi = 480 + i*32; /* num-irq512 minus32 internal */
            if (!strcmp(route, "standard")) {
                qdev_connect_gpio_out(core, GTIMER_PHYS, qdev_get_gpio_in(gic, ppi+30));
                qdev_connect_gpio_out(core, GTIMER_SEC, qdev_get_gpio_in(gic, ppi+29));
            } else if (!strcmp(route, "secure-only")) {
                /* Wrong-channel control for A32 under A64 EL3: secure
                 * execution alone does not select the secure CP register bank.
                 * QEMU access_secure_reg() also requires A32 EL3. Actual guest
                 * controls select GTIMER_PHYS in this explicit context.
                 * Physical Sony wiring remains unqualified.
                 */
                qdev_connect_gpio_out(core, GTIMER_SEC, qdev_get_gpio_in(gic, ppi+30));
            } else if (!strcmp(route, "phys-only")) {
                qdev_connect_gpio_out(core, GTIMER_PHYS, qdev_get_gpio_in(gic, ppi+30));
            }

        }
        g_printerr("CP_GIC_MODEL revision=2 cpus=%u num-irq=512 dist=f13a1000 cpuif=f13a2000 timer-route=%s physical-wiring-unqualified=1\n", mch->smp.cpus, route);
    }

    if (mch->kernel_filename) {
        error_report("The -kernel parameter is not supported "
                     "(use the generic 'loader' device instead).");
        exit(1);
    }
}

static void machine_none_machine_init(MachineClass *mc)
{
    mc->desc = "empty machine";
    mc->init = machine_none_init;
    mc->max_cpus = 4;
    mc->default_ram_size = 0;
    mc->default_ram_id = "ram";
    mc->no_serial = 1;
    mc->no_parallel = 1;
    mc->no_floppy = 1;
    mc->no_cdrom = 1;
    machine_class_allow_dynamic_sysbus_dev(mc, "sony-cxd-bus-stub");
}

DEFINE_MACHINE_WITH_INTERFACES("none", machine_none_machine_init,
                               { TYPE_TARGET_AARCH64_MACHINE },
                               { TYPE_TARGET_ARM_MACHINE },
                               { TYPE_TARGET_RISCV32_MACHINE },
                               { TYPE_TARGET_RISCV64_MACHINE },
                               { })
