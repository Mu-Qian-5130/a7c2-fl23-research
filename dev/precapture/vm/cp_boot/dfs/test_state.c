/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <assert.h>
#include <stdio.h>
#include "state.h"
int main(void)
{
    CpLabDfs s={0};uint32_t value;
    assert(!cp_dfs_actor_complete(&s));
    assert(!cp_dfs_write(&s,8,1));
    assert(cp_dfs_write(&s,4,0x101));
    assert(cp_dfs_read(&s,0,&value) && value==0);
    for (unsigned freq=0;freq<7;freq++) {
        assert(cp_dfs_write(&s,0,0x101));
        assert(cp_dfs_write(&s,0xc,0x100|freq));
        assert(cp_dfs_write(&s,8,1));
        assert(!cp_dfs_write(&s,8,1));
        assert(!cp_dfs_write(&s,0xc,0));
        for (unsigned n=0;n<100;n++) {
            assert(cp_dfs_read(&s,0,&value) && value==0);
            assert(cp_dfs_read(&s,0x10,&value) && (value&0x100));
            assert(s.active && s.completions==freq);
        }
        assert(cp_dfs_write(&s,4,0));
        assert(s.active && s.events==0);
        assert(cp_dfs_actor_complete(&s));
        assert(!cp_dfs_actor_complete(&s));
        assert(cp_dfs_read(&s,0,&value) && value==1);
        assert(cp_dfs_read(&s,0x10,&value) && value==freq);
        assert(cp_dfs_write(&s,0,1));
        assert(s.events==0 && s.starts==freq+1 && s.completions==freq+1);
    }
    assert(!cp_dfs_write(&s,0xc,7));
    assert(!cp_dfs_write(&s,0xc,0x200));
    assert(!cp_dfs_write(&s,0,2));
    assert(!cp_dfs_write(&s,4,2));
    for (unsigned off=0;off<24;off++) {
        if (off!=0 && off!=16) { assert(!cp_dfs_read(&s,off,&value)); }
        if (off!=0 && off!=4 && off!=8 && off!=12) { assert(!cp_dfs_write(&s,off,0)); }
    }
    puts("DFS protocol: absent actor retains pending; explicit completion, ack and unknown-access rejection passed");
    return 0;
}
