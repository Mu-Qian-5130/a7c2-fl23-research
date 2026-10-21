/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <assert.h>
#include <stdio.h>
#include "state.h"
int main(void)
{
    unsigned shifts[4]={16,8,4,0},widths[4]={3,7,7,7};uint32_t value;
    for (unsigned policy=0;policy<2;policy++) {
      for (unsigned field=0;field<4;field++) {
        uint32_t mask=widths[field]<<shifts[field];
        for (unsigned token=0;token<(field ? 7u : 4u);token++) {
            CpSpiSelect s={CP_SPI_SELECT_MASK,policy ? UINT32_MAX : 0};
            uint32_t bits=token<<shifts[field];
            assert(cp_spi_select_write(&s,4,bits));
            assert(cp_spi_select_write(&s,8,mask&~bits));
            assert(cp_spi_select_read(&s,0,&value));
            assert(value==((CP_SPI_SELECT_MASK&~mask)|bits));
            assert(cp_spi_select_read(&s,4,&value) && value==s.alias_readback);
            assert(cp_spi_select_read(&s,8,&value) && value==s.alias_readback);
            assert(cp_spi_select_write(&s,4,0));
            assert(s.selection==((CP_SPI_SELECT_MASK&~mask)|bits));
            assert(!cp_spi_select_write(&s,0,0));
            for (unsigned bit=0;bit<32;bit++) {
                if (!(CP_SPI_SELECT_MASK&(1u<<bit))) {
                    assert(!cp_spi_select_write(&s,4,1u<<bit));
                    assert(!cp_spi_select_write(&s,8,1u<<bit));
                }
            }
            assert(!cp_spi_select_read(&s,12,&value));
            assert(!cp_spi_select_write(&s,12,0));
        }
      }
    }
    puts("SPI selection SET/CLR, field isolation, independent alias words and rejection contracts passed");
    return 0;
}
