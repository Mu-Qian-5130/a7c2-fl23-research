/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <assert.h>
#include <stdio.h>
#include "state.h"
int main(void)
{
    for (unsigned alias=0;alias<2;alias++) {
        CpRequestWords s={0};uint32_t value;s.set_readback=alias ? UINT32_MAX : 0;
        assert(cp_request_word_add(&s,0x5d0,0x5515));
        assert(cp_request_word_add(&s,0x5e0,0x55));
        assert(cp_request_word_add(&s,0xdd0,0x11));
        assert(!cp_request_word_add(&s,0x5d0,1));
        assert(!cp_request_word_add(&s,0x1000,1));
        assert(!cp_request_word_add(&s,0x5d4,1));
        assert(!cp_request_word_add(&s,0x100,0));
        for (unsigned i=0;i<256;i++) {
            if (!s.masks[i]) {
                assert(!cp_request_word_read(&s,i,0,&value));
                assert(!cp_request_word_write(&s,i,4,0));continue;
            }
            assert(cp_request_word_write(&s,i,4,s.masks[i]));
            assert(cp_request_word_read(&s,i,0,&value) && value==s.masks[i]);
            assert(cp_request_word_read(&s,i,4,&value) && value==s.set_readback);
            for (unsigned bit=0;bit<32;bit++) {
                uint32_t word=1u<<bit;
                if (word&s.masks[i]) { assert(cp_request_word_write(&s,i,0,word)); }
                else { assert(!cp_request_word_write(&s,i,0,word));assert(!cp_request_word_write(&s,i,4,word)); }
            }
            assert(cp_request_word_read(&s,i,0,&value) && value==0);
            assert(!cp_request_word_write(&s,i,8,1));
            assert(!cp_request_word_read(&s,i,8,&value));
        }
        assert(!cp_request_word_read(&s,256,0,&value));
    }
    puts("Sparse request words: bank/bit bounds, paired commands, independent readback and rejection passed");
    return 0;
}
