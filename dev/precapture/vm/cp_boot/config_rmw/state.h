/* SPDX-License-Identifier: GPL-2.0-or-later */
/* One explicitly initialized software configuration word, no device ACK. */
#ifndef CP_LAB_CONFIG_WORD_H
#define CP_LAB_CONFIG_WORD_H
#include <stdint.h>
#include <stdbool.h>

#define CP_CONFIG_MASK UINT32_C(0x4000)
typedef struct { uint32_t value; } CpConfigWord;
static inline bool cp_config_read(const CpConfigWord *s,unsigned offset,uint32_t *value)
{
    if (offset) { return false; }
    *value=s->value;return true;
}
static inline bool cp_config_write_masked(CpConfigWord *s,unsigned offset,uint32_t value,uint32_t mask)
{
    if (offset || ((s->value^value)&~mask)) { return false; }
    s->value=value;return true;
}
static inline bool cp_config_write(CpConfigWord *s,unsigned offset,uint32_t value)
{
    return cp_config_write_masked(s,offset,value,CP_CONFIG_MASK);
}
#endif
