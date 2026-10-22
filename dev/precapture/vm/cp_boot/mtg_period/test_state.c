/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <assert.h>
#include <stdio.h>
#include "../config_rmw/state.h"
int main(void)
{
    const uint32_t values[]={0,0x1b7e47,0x225dd9,UINT32_MAX};unsigned checks=0;
    for(unsigned sample=0;sample<4;sample++) {
        CpSourceWordState words[3]={{{0xdeadbeef},false},{{0x13579bdf},false},{{0x2468ace0},false}};
        uint32_t out=0xa5a5a5a5;
        for(unsigned i=0;i<3;i++) {
            assert(!cp_source_read(&words[i],0,&out)&&out==0xa5a5a5a5);checks++;
            assert(!cp_source_write(&words[i],0,0,3)&&!words[i].defined);checks++;
            assert(cp_source_write(&words[i],0,values[sample]+i,UINT32_MAX));checks++;
            assert(cp_source_read(&words[i],0,&out)&&out==values[sample]+i);checks++;
            for(unsigned other=i+1;other<3;other++) {
                out=0xa5a5a5a5;assert(!cp_source_read(&words[other],0,&out)&&out==0xa5a5a5a5);checks++;
            }
            assert(cp_source_write(&words[i],0,values[sample]^0x55555555,UINT32_MAX));checks++;
            assert(cp_source_read(&words[i],0,&out)&&out==(values[sample]^0x55555555));checks++;
            for(unsigned offset=1;offset<=8;offset++) {
                uint32_t saved=words[i].word.value;
                assert(!cp_source_write(&words[i],offset,0,UINT32_MAX)&&words[i].word.value==saved);checks++;
            }
            out=0xa5a5a5a5;
        }
    }
    printf("%u write-first period-word contracts; no initial timing value supplied\n",checks);
    return 0;
}
