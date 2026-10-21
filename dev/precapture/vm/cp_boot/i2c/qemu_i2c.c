/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Glue only: the I2C core is unchanged upstream QEMU DesignWare.
 * Strict gate faults are laboratory policy, not a measured clock-off response.
 * No native sensor/EEPROM slave is supplied; optional EEPROM is a test actor.
 */
#include "hw/i2c/designware_i2c.h"
#include "hw/i2c/i2c.h"
#include "hw/core/irq.h"
#include "qemu/log.h"
#include "state.h"

typedef struct CpI2cDevice CpI2cDevice;
typedef struct { CpI2cDevice *owner;bool reset;MemoryRegion mmio; } CpI2cScu;
typedef struct { CpI2cDevice *owner;unsigned port; } CpI2cIrq;
struct CpI2cDevice {
    CpI2cGate gate;
    DeviceState *core[5];
    qemu_irq output[5];
    int level[5];
    CpI2cIrq input[5];
    CpI2cScu scu[2];
};
static void cp_i2c_irq(void *opaque,int n,int level)
{
    CpI2cIrq *in=opaque;CpI2cDevice *s=in->owner;
    (void)n;s->level[in->port]=level;
    qemu_set_irq(s->output[in->port],cp_i2c_active(&s->gate,in->port) ? level : 0);
}
static MemTxResult cp_i2c_scu_read(void *opaque,hwaddr offset,uint64_t *value,
                                  unsigned size,MemTxAttrs attrs)
{
    CpI2cScu *r=opaque;uint32_t word=0;(void)attrs;
    bool ok=size==4 && cp_i2c_gate_read(&r->owner->gate,r->reset,offset,&word);
    *value=word;return ok ? MEMTX_OK : MEMTX_ERROR;
}
static MemTxResult cp_i2c_scu_write(void *opaque,hwaddr offset,uint64_t value,
                                   unsigned size,MemTxAttrs attrs)
{
    CpI2cScu *r=opaque;CpI2cDevice *s=r->owner;CpI2cGate before=s->gate;(void)attrs;
    if (size!=4 || !cp_i2c_gate_write(&s->gate,r->reset,offset,value)) {
        qemu_log_mask(LOG_UNIMP,"CP_I2C_SCU_UNSUPPORTED reset=%u offset=%"HWADDR_PRIx" value=%"PRIu64" size=%u\n",r->reset,offset,value,size);
        return MEMTX_ERROR;
    }
    for (unsigned p=0;p<5;p++) {
        uint32_t bit=1u<<(24+p);
        if (!(before.reset&bit) && (s->gate.reset&bit)) {
            /* The upstream core reset clears registers/FIFO/IRQ but does not
             * end its bus transaction. Release that ownership explicitly.
             * Clock gating alone preserves it; this is a reset-only action.
             */
            i2c_end_transfer(DESIGNWARE_I2C(s->core[p])->bus);
            device_cold_reset(s->core[p]);
        }
        memory_region_set_enabled(sysbus_mmio_get_region(SYS_BUS_DEVICE(s->core[p]),0),cp_i2c_active(&s->gate,p));
        qemu_set_irq(s->output[p],cp_i2c_active(&s->gate,p) ? s->level[p] : 0);
    }
    qemu_log_mask(LOG_UNIMP,"CP_I2C_SCU reset=%u offset=%"HWADDR_PRIx" value=%"PRIu64" clock=%08x reset_state=%08x\n",r->reset,offset,value,s->gate.clock,s->gate.reset);
    return MEMTX_OK;
}
static const MemoryRegionOps cp_i2c_scu_ops={
    .read_with_attrs=cp_i2c_scu_read,.write_with_attrs=cp_i2c_scu_write,
    .endianness=DEVICE_LITTLE_ENDIAN,
    .valid={.min_access_size=4,.max_access_size=4,.unaligned=false},
};
static void cp_lab_i2c_init(MachineState *machine,DeviceState *gic)
{
    const char *profile=g_getenv("QEMU_SONY_CP_I2C_PROFILE");
    if (!profile) { return; }
    if (strcmp(profile,"absent") && strcmp(profile,"fixture")) { error_report("Invalid CP I2C profile");exit(1); }
    CpI2cDevice *s=g_new0(CpI2cDevice,1);cp_i2c_gate_init(&s->gate);
    for (unsigned p=0;p<5;p++) {
        s->core[p]=qdev_new(TYPE_DESIGNWARE_I2C);
        SysBusDevice *bus=SYS_BUS_DEVICE(s->core[p]);
        s->output[p]=qdev_get_gpio_in(gic,429+p-32);
        s->input[p].owner=s;s->input[p].port=p;
        sysbus_realize_and_unref(bus,&error_fatal);
        sysbus_connect_irq(bus,0,qemu_allocate_irq(cp_i2c_irq,&s->input[p],0));
        sysbus_mmio_map(bus,0,0xf1012000+p*0x1000);
        memory_region_set_enabled(sysbus_mmio_get_region(bus,0),false);
    }
    for (unsigned r=0;r<2;r++) {
        s->scu[r].owner=s;s->scu[r].reset=r!=0;
        memory_region_init_io(&s->scu[r].mmio,OBJECT(machine),&cp_i2c_scu_ops,&s->scu[r],r ? "cp-i2c-reset" : "cp-i2c-clock",12);
        memory_region_add_subregion(get_system_memory(),r ? 0xf1388350 : 0xf1388050,&s->scu[r].mmio);
    }
    if (!strcmp(profile,"fixture")) {
        I2CSlave *slave=i2c_slave_new("at24c-eeprom",0x50);
        qdev_prop_set_uint32(DEVICE(slave),"rom-size",256);
        qdev_prop_set_uint8(DEVICE(slave),"address-size",1);
        i2c_slave_realize_and_unref(slave,DESIGNWARE_I2C(s->core[0])->bus,&error_fatal);
    }
    g_printerr("CP_I2C_MODEL profile=%s upstream=DesignWare ports=5 irq=429..433 command-timed=1 physical-qualified=0\n",profile);
}
