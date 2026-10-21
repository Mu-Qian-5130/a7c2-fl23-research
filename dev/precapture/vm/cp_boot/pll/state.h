/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Inferred PLL configuration/request model, not an oscillator or clock tree.
 * A guest write cannot set LOCK. Only an explicit actor may respond.
 */
#ifndef CP_LAB_PLL_H
#define CP_LAB_PLL_H
#include <stdint.h>
#include <stdbool.h>
#define CP_PLL_COEFF UINT32_C(0x043fff1f)
#define CP_PLL_START UINT32_C(0x08000000)
#define CP_PLL_GATE UINT32_C(0x10000000)
#define CP_PLL_LOCK UINT32_C(0x01000000)
#define CP_PLL_WRITABLE (CP_PLL_COEFF|CP_PLL_START|CP_PLL_GATE)
typedef struct {
    uint32_t config,reserved;
    uint64_t generation;
    bool pending,locked;
} CpPllSlot;
typedef struct {
    CpPllSlot slot[5];
    uint32_t div[2],selection,logic_clock,alias_readback;
} CpLabPll;
typedef struct { uint32_t selection,coeff[5],div[2]; } CpPllSourceProgram;
static inline bool cp_pll_source_program_valid(const CpPllSourceProgram *p)
{
    if (p->selection&~0xfd13u) { return false; }
    for (unsigned i=0;i<5;i++) { if (p->coeff[i]&~CP_PLL_COEFF) { return false; } }
    return !(p->div[0]&~0x7feu) && !(p->div[1]&~0x7feu);
}
/* Source-tuple admission is a fixture constraint, not oscillator validity. */
static inline bool cp_pll_source_admitted(const CpLabPll *s,const CpPllSourceProgram *p,unsigned count,unsigned slot)
{
    if (slot>=5 || !p || count==0 || count>6) { return false; }
    for (unsigned row=0;row<count;row++) {
        if (!cp_pll_source_program_valid(&p[row]) || s->selection!=p[row].selection ||
            (s->slot[slot].config&CP_PLL_COEFF)!=p[row].coeff[slot]) { continue; }
        if (slot==1 && (s->div[0]&0x7feu)!=p[row].div[0]) { continue; }
        if (slot==3 && (s->div[1]&0x7feu)!=p[row].div[1]) { continue; }
        return true;
    }
    return false;
}
static inline uint32_t cp_pll_slot_read(const CpPllSlot *s)
{ return s->config|s->reserved|(s->locked ? CP_PLL_LOCK : 0); }
static inline bool cp_pll_slot_write(CpPllSlot *s,uint32_t value)
{
    uint32_t next=value&CP_PLL_WRITABLE;
    if ((value&~(CP_PLL_WRITABLE|CP_PLL_LOCK))!=s->reserved) { return false; }
    if ((s->config&CP_PLL_START) && (next&CP_PLL_START) && ((next^s->config)&CP_PLL_COEFF)) { return false; }
    if (next==s->config) { return true; } /* LOCK writes have no effect. */
    uint32_t before=s->config;s->config=next;s->generation++;
    if (!(next&CP_PLL_START) || !(next&CP_PLL_GATE)) {
        s->locked=false;s->pending=(next&CP_PLL_START)!=0;
    } else if (!(before&CP_PLL_START) || !(before&CP_PLL_GATE) || ((next^before)&CP_PLL_COEFF)) {
        s->locked=false;s->pending=true;
    }
    return true;
}
static inline bool cp_pll_actor_lock(CpPllSlot *s,uint64_t generation)
{
    if (!s->pending || s->generation!=generation ||
        (s->config&(CP_PLL_START|CP_PLL_GATE))!=(CP_PLL_START|CP_PLL_GATE)) { return false; }
    s->pending=false;s->locked=true;return true;
}
static inline bool cp_pll_read(const CpLabPll *s,unsigned offset,uint32_t *value)
{
    if (!(offset&3) && offset<=16) { *value=cp_pll_slot_read(&s->slot[offset/4]); }
    else if (offset==0x50 || offset==0x58) { *value=s->div[offset==0x58]; }
    else { return false; }
    return true;
}
static inline bool cp_pll_write(CpLabPll *s,unsigned offset,uint32_t value)
{
    if (!(offset&3) && offset<=16) { return cp_pll_slot_write(&s->slot[offset/4],value); }
    if (offset==0x50 || offset==0x58) {
        uint32_t *word=&s->div[offset==0x58];
        if ((value&~0x7feu)!=(*word&~0x7feu)) { return false; }
        *word=value;return true;
    }
    return false;
}
static inline bool cp_pll_select_read(const CpLabPll *s,unsigned offset,uint32_t *value)
{
    if (offset==0) { *value=s->selection; }
    else if (offset==4 || offset==8) { *value=s->alias_readback; }
    else { return false; }
    return true;
}
static inline bool cp_pll_select_write(CpLabPll *s,unsigned offset,uint32_t value)
{
    if (value&~0xfd13u) { return false; }
    if (offset==4) { s->selection|=value; }
    else if (offset==8) { s->selection&=~value; }
    else { return false; }
    return true;
}
static inline bool cp_pll_logic_read(const CpLabPll *s,unsigned offset,uint32_t *value)
{
    if (offset==0) { *value=s->logic_clock; }
    else if (offset==4 || offset==8) { *value=s->alias_readback; }
    else { return false; }
    return true;
}
static inline bool cp_pll_logic_write(CpLabPll *s,unsigned offset,uint32_t value)
{
    if (value&~0x400000u) { return false; }
    if (offset==4) { s->logic_clock|=value; }
    else if (offset==8) { s->logic_clock&=~value; }
    else { return false; }
    return true;
}
#endif
