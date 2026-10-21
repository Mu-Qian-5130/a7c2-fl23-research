/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Sparse inferred software-request words. No hardware confirmation/IRQ. */
#ifndef CP_LAB_REQUEST_WORDS_H
#define CP_LAB_REQUEST_WORDS_H
#include <stdint.h>
#include <stdbool.h>
typedef struct { uint32_t masks[256],requested[256],set_readback; } CpRequestWords;
static inline bool cp_request_word_add(CpRequestWords *s,unsigned offset,uint32_t mask)
{
    if (offset>=0x1000 || (offset&15) || !mask || s->masks[offset/16]) { return false; }
    s->masks[offset/16]=mask;return true;
}
static inline bool cp_request_word_read(const CpRequestWords *s,unsigned word,unsigned offset,uint32_t *value)
{
    if (word>=256 || !s->masks[word]) { return false; }
    if (offset==0) { *value=s->requested[word]; }
    else if (offset==4) { *value=s->set_readback; }
    else { return false; }
    return true;
}
static inline bool cp_request_word_write(CpRequestWords *s,unsigned word,unsigned offset,uint32_t value)
{
    if (word>=256 || !s->masks[word] || value&~s->masks[word]) { return false; }
    if (offset==0) { s->requested[word]&=~value; }
    else if (offset==4) { s->requested[word]|=value; }
    else { return false; }
    return true;
}
#endif
