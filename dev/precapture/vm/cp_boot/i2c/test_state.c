/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <assert.h>
#include <stdio.h>
#include "state.h"
int main(void)
{
    CpI2cGate s;uint32_t value;
    cp_i2c_gate_init(&s);
    assert(!cp_i2c_active(&s,5));
    for (unsigned p=0;p<5;p++) {
        uint32_t c=1u<<(18+p),r=1u<<(24+p);
        assert(!cp_i2c_active(&s,p));
        assert(cp_i2c_gate_write(&s,false,4,c));
        assert(!cp_i2c_active(&s,p));
        assert(cp_i2c_gate_write(&s,true,8,r));
        assert(cp_i2c_active(&s,p));
        assert(cp_i2c_gate_write(&s,false,8,c));
        assert(!cp_i2c_active(&s,p));
        assert(cp_i2c_gate_write(&s,false,4,c));
        assert(cp_i2c_gate_write(&s,true,4,r));
        assert(!cp_i2c_active(&s,p));
        assert(cp_i2c_gate_write(&s,true,8,r));
        for (unsigned j=0;j<5;j++) { assert(cp_i2c_active(&s,j)==(j<=p)); }
    }
    assert(cp_i2c_gate_read(&s,false,0,&value) && value==CP_I2C_CLOCK_MASK);
    assert(cp_i2c_gate_read(&s,true,0,&value) && value==0);
    for (unsigned off=0;off<16;off++) {
        CpI2cGate before=s;
        if (off!=0 && off!=4 && off!=8) {
            assert(!cp_i2c_gate_write(&s,false,off,0));
            assert(s.clock==before.clock && s.reset==before.reset);
        }
        if (off) { assert(!cp_i2c_gate_read(&s,true,off,&value)); }
    }
    for (unsigned bit=0;bit<32;bit++) {
        if (!(CP_I2C_CLOCK_MASK&(1u<<bit))) { assert(!cp_i2c_gate_write(&s,false,4,1u<<bit)); }
        if (!(CP_I2C_RESET_MASK&(1u<<bit))) { assert(!cp_i2c_gate_write(&s,true,4,1u<<bit)); }
    }
    assert(cp_i2c_gate_write(&s,false,0,0));
    for (unsigned p=0;p<5;p++) { assert(!cp_i2c_active(&s,p)); }
    puts("I2C gate isolation, direct/set/clear and unsupported-bit contracts passed");
    return 0;
}
