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
    assert(!cp_pll_logic_write(&s,4,0x200));
    assert(!cp_pll_logic_write(&s,0,0));
    assert(!cp_pll_logic_read(&s,12,&value));
    for (unsigned bit=0;bit<32;bit++) {
        uint32_t word=1u<<bit;
        assert(cp_pll_logic_write(&s,4,word)==((word&CP_PLL_LOGIC_MASK)!=0));
        if (word&CP_PLL_LOGIC_MASK) { assert(cp_pll_logic_write(&s,8,word)); }
    }
    assert(cp_pll_media_write(&s,4,0x100));
    assert(cp_pll_media_read(&s,0,&value) && value==0x100);
    assert(cp_pll_media_write(&s,8,0x100));
    assert(cp_pll_media_read(&s,0,&value) && value==0);
    assert(!cp_pll_media_write(&s,4,0x200));
    assert(!cp_pll_media_write(&s,0,0));
    assert(!cp_pll_media_read(&s,12,&value));
    CpLabPll a={0};CpPllSourceProgram program={0};program.selection=0x10;
    for (unsigned i=0;i<5;i++) { program.coeff[i]=0x12000+i; }
    program.div[0]=0x200;program.div[1]=0x400;
    a.selection=program.selection;a.div[0]=program.div[0];a.div[1]=program.div[1];
    for (unsigned i=0;i<5;i++) {
        a.slot[i].config=program.coeff[i]|CP_PLL_GATE|CP_PLL_START;
        assert(cp_pll_source_admitted(&a,&program,1,i));
        a.slot[i].config^=0x100;
        assert(!cp_pll_source_admitted(&a,&program,1,i));
        a.slot[i].config^=0x100;
    }
    a.div[0]^=2;assert(!cp_pll_source_admitted(&a,&program,1,1));a.div[0]^=2;
    a.div[1]^=2;assert(!cp_pll_source_admitted(&a,&program,1,3));a.div[1]^=2;
    a.selection^=1;assert(!cp_pll_source_admitted(&a,&program,1,0));a.selection^=1;
    program.coeff[0]|=CP_PLL_LOCK;assert(!cp_pll_source_admitted(&a,&program,1,0));
    assert(!cp_pll_source_admitted(&a,&program,0,0));
    assert(!cp_pll_source_admitted(&a,&program,7,0));
    assert(!cp_pll_source_admitted(&a,&program,1,5));
    puts("PLL pending/LOCK ownership, ignored guest LOCK, stale-response rejection and field guards passed");
    return 0;
}
