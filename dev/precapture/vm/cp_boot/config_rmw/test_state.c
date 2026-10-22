/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <assert.h>
#include <stdio.h>
#include "state.h"
int main(void)
{
    const uint32_t words[]={0,UINT32_MAX,0x55555555,0xaaaaaaaa};
    unsigned checks=0;
    for(unsigned i=0;i<4;i++) {
        CpConfigWord s={words[i]};uint32_t v;
        assert(cp_config_read(&s,0,&v)&&v==words[i]);checks++;
        assert(cp_config_write(&s,0,words[i]|CP_CONFIG_MASK));checks++;
        assert(cp_config_read(&s,0,&v)&&v==(words[i]|CP_CONFIG_MASK));checks++;
        assert(cp_config_write(&s,0,words[i]&~CP_CONFIG_MASK));checks++;
        uint32_t saved=s.value;
        for(unsigned bit=0;bit<32;bit++)if(bit!=14) {
            assert(!cp_config_write(&s,0,saved^(UINT32_C(1)<<bit))&&s.value==saved);checks++;
        }
        for(unsigned offset=1;offset<=8;offset++) {
            v=0x13579bdf;
            assert(!cp_config_read(&s,offset,&v)&&v==0x13579bdf);checks++;
            assert(!cp_config_write(&s,offset,0)&&s.value==saved);checks++;
        }
    }
    printf("%u isolated configuration-word contracts; no hardware value inferred\n",checks);
    return 0;
}
