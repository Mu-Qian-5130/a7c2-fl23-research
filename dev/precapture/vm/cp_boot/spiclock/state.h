/* SPDX-License-Identifier: GPL-2.0-or-later */
/* SPI selector bits only. No oscillator/rate, pad, IRQ or readiness model.
 * Alias readback is an explicit unknown-value fixture, not silicon readback.
 */
#ifndef CP_LAB_SPI_CLOCK_SELECT_H
#define CP_LAB_SPI_CLOCK_SELECT_H
#include <stdbool.h>
#include <stdint.h>
#define CP_SPI_SELECT_MASK UINT32_C(0x00030777)
typedef struct { uint32_t selection,alias_readback; } CpSpiSelect;
static inline bool cp_spi_select_read(const CpSpiSelect *s,unsigned offset,uint32_t *value)
{
    if (offset==0) { *value=s->selection; }
    else if (offset==4 || offset==8) { *value=s->alias_readback; }
    else { return false; }
    return true;
}
static inline bool cp_spi_select_write(CpSpiSelect *s,unsigned offset,uint32_t value)
{
    if (value&~CP_SPI_SELECT_MASK) { return false; }
    if (offset==4) { s->selection|=value; }
    else if (offset==8) { s->selection&=~value; }
    else { return false; }
    return true;
}
#endif
