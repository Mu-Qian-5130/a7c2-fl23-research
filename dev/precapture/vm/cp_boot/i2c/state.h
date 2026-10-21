/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Explicit laboratory gate policy; initial reset-held is not measured silicon. */
#ifndef CP_LAB_I2C_GATE_H
#define CP_LAB_I2C_GATE_H
#include <stdint.h>
#include <stdbool.h>
#define CP_I2C_CLOCK_MASK UINT32_C(0x007c0000)
#define CP_I2C_RESET_MASK UINT32_C(0x1f000000)
typedef struct { uint32_t clock, reset; } CpI2cGate;
static inline void cp_i2c_gate_init(CpI2cGate *s)
{ s->clock=0; s->reset=CP_I2C_RESET_MASK; }
static inline bool cp_i2c_active(const CpI2cGate *s,unsigned port)
{ return port<5 && (s->clock & (1u<<(18+port))) && !(s->reset & (1u<<(24+port))); }
static inline bool cp_i2c_gate_read(const CpI2cGate *s,bool reset,unsigned offset,uint32_t *value)
{ if (offset) { return false; } *value=reset ? s->reset : s->clock; return true; }
static inline bool cp_i2c_gate_write(CpI2cGate *s,bool reset,unsigned offset,uint32_t value)
{
    uint32_t mask=reset ? CP_I2C_RESET_MASK : CP_I2C_CLOCK_MASK;
    uint32_t *field=reset ? &s->reset : &s->clock;
    if (value & ~mask) { return false; }
    if (offset==0) { *field=value; }
    else if (offset==4) { *field|=value; }
    else if (offset==8) { *field&=~value; }
    else { return false; }
    return true;
}
#endif
