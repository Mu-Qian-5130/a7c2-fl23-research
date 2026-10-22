/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <assert.h>
#include <stdio.h>
#include "../config_rmw/state.h"
int main(void)
{
    const uint32_t initial[]={0,UINT32_MAX,0x55555555,0xaaaaaaaa};unsigned checks=0;
    for(unsigned i=0;i<4;i++)for(uint32_t selected=0;selected<4;selected++) {
        CpConfigWord s={initial[i]};uint32_t expected=(initial[i]&~UINT32_C(3))|selected,v;
        assert(cp_config_write_masked(&s,0,expected,3));checks++;
        assert(cp_config_read(&s,0,&v)&&v==expected);checks++;
        for(unsigned bit=2;bit<32;bit++) {
            assert(!cp_config_write_masked(&s,0,expected^(UINT32_C(1)<<bit),3)&&s.value==expected);checks++;
        }
        for(unsigned offset=1;offset<=8;offset++) {
            v=0x13579bdf;assert(!cp_config_read(&s,offset,&v)&&v==0x13579bdf);checks++;
            assert(!cp_config_write_masked(&s,offset,expected,3)&&s.value==expected);checks++;
        }
    }
    printf("%u MTG selector storage contracts; no timing or pixels supplied\n",checks);
    return 0;
}
