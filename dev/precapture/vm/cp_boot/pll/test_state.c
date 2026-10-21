/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <assert.h>
#include <stdio.h>
#include "state.h"
int main(void)
{
    CpLabPll s={0};uint32_t value;
    for (unsigned i=0;i<5;i++) {
        CpPllSlot *p=&s.slot[i];uint32_t coeff=0x12300+i;
        assert(cp_pll_write(&s,i*4,coeff|CP_PLL_LOCK));
        assert(cp_pll_read(&s,i*4,&value) && !(value&CP_PLL_LOCK));
        assert(cp_pll_write(&s,i*4,coeff|CP_PLL_GATE|CP_PLL_START));
        uint64_t first=p->generation;
        for (unsigned n=0;n<128;n++) {
            assert(cp_pll_read(&s,i*4,&value) && !(value&CP_PLL_LOCK));
            assert(p->pending && !p->locked);
        }
        assert(cp_pll_write(&s,i*4,p->config|CP_PLL_LOCK));
        assert(!p->locked && p->generation==first);
        assert(!cp_pll_write(&s,i*4,(p->config^0x100)|CP_PLL_LOCK));
        assert(cp_pll_write(&s,i*4,coeff|CP_PLL_GATE));
        assert(!cp_pll_actor_lock(p,first));
        assert(!p->pending && !p->locked);
        assert(cp_pll_write(&s,i*4,coeff|CP_PLL_GATE|CP_PLL_START));
        assert(!cp_pll_actor_lock(p,first));
        assert(cp_pll_actor_lock(p,p->generation));
        assert(cp_pll_read(&s,i*4,&value) && (value&CP_PLL_LOCK));
        assert(!cp_pll_actor_lock(p,p->generation));
        assert(cp_pll_write(&s,i*4,coeff));
        assert(!p->locked && !p->pending);
    }
    s.slot[0].reserved=~(CP_PLL_WRITABLE|CP_PLL_LOCK);
    assert(cp_pll_write(&s,0,s.slot[0].reserved|0x100));
    assert(!cp_pll_write(&s,0,0));
    assert(cp_pll_write(&s,0x50,0x200));
    assert(cp_pll_write(&s,0x58,0x400));
    assert(!cp_pll_write(&s,0x50,1));
    assert(!cp_pll_read(&s,0x14,&value));
    assert(!cp_pll_write(&s,0x14,0));
    assert(cp_pll_select_write(&s,4,0xfd13));
    assert(cp_pll_select_write(&s,8,0x3103));
    assert(cp_pll_select_read(&s,0,&value) && value==0xcc10);
    assert(!cp_pll_select_write(&s,4,4));
    assert(!cp_pll_select_write(&s,0,0));
    assert(cp_pll_logic_write(&s,4,0x400000));
    assert(cp_pll_logic_read(&s,0,&value) && value==0x400000);
    assert(cp_pll_logic_write(&s,8,0x400000));
    assert(cp_pll_logic_read(&s,0,&value) && value==0);
    assert(!cp_pll_logic_write(&s,4,0x200000));
    assert(!cp_pll_logic_write(&s,0,0));
    assert(!cp_pll_logic_read(&s,12,&value));
    puts("PLL pending/LOCK ownership, ignored guest LOCK, stale-response rejection and field guards passed");
    return 0;
}
