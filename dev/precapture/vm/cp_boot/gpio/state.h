/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Offline GPIO register contract. Inputs are external actor state, never
 * overwritten by guest output/configuration writes. No loopback, IRQ, mux
 * electrical behavior or physical peer wiring is supplied by this model.
 */
#ifndef CP_LAB_GPIO_H
#define CP_LAB_GPIO_H
#include <stdint.h>
#include <stdbool.h>
typedef struct { uint32_t direction,input,inen,function,output;bool input_defined; } CpLabGpio;

static inline bool cp_gpio_read(const CpLabGpio *s,uint32_t offset,uint32_t *value)
{
    if (offset==0) { *value=s->direction; }
    else if (offset==0x10) { if (!s->input_defined) { return false; } *value=s->input; }
    else if (offset==0x20) { *value=s->inen; }
    else if (offset==0x30) { *value=s->function; }
    else if (offset==0x40) { *value=s->output; }
    else { return false; }
    return true;
}

static inline bool cp_gpio_write(CpLabGpio *s,uint32_t offset,uint32_t value)
{
    uint32_t *field;
    if (offset&3) { return false; }
    uint32_t group=offset&~15u,operation=offset&15;
    if (group==0) { field=&s->direction; }
    else if (group==0x20) { field=&s->inen; }
    else if (group==0x30) { field=&s->function; }
    else if (group==0x40) { field=&s->output; }
    else { return false; }
    if (operation==0) { *field=value; }
    else if (operation==4) { *field|=value; }
    else if (operation==8) { *field&=~value; }
    else { return false; }
    return true;
}
#endif
