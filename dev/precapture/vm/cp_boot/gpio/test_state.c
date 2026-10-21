#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "state.h"
int main(void) {
    CpLabGpio s={.input=8,.input_defined=true};uint32_t value;
    assert(cp_gpio_write(&s,8,8));assert(cp_gpio_write(&s,0x24,8));
    assert(cp_gpio_read(&s,0,&value) && value==0);
    assert(cp_gpio_read(&s,0x10,&value) && value==8); /* high strap survives setup */
    assert(cp_gpio_write(&s,4,0x18));assert(s.direction==0x18);
    assert(cp_gpio_write(&s,8,8));assert(s.direction==0x10);
    assert(cp_gpio_write(&s,0,0x12345678));assert(s.direction==0x12345678);
    assert(cp_gpio_write(&s,0x44,0x18));assert(s.output==0x18 && s.input==8);
    assert(cp_gpio_write(&s,0x48,0x10));assert(s.output==8 && s.input==8);
    assert(cp_gpio_write(&s,0x40,0));assert(s.output==0 && s.input==8);
    assert(cp_gpio_write(&s,0x28,8));assert(s.inen==0 && s.input==8);
    assert(cp_gpio_write(&s,0x34,0x20));assert(s.function==0x20);
    assert(cp_gpio_write(&s,0x38,0x20));assert(s.function==0);
    CpLabGpio before;memcpy(&before,&s,sizeof(s));
    for (unsigned at=0x10;at<=0x18;at+=4) { assert(!cp_gpio_write(&s,at,0xffffffff)); }
    assert(!cp_gpio_write(&s,0xc,0));assert(!cp_gpio_write(&s,0x50,1));
    assert(!cp_gpio_read(&s,4,&value));assert(!cp_gpio_read(&s,1,&value));
    assert(memcmp(&s,&before,sizeof(s))==0);
    CpLabGpio low={.input_defined=true};assert(cp_gpio_write(&low,0x44,8));
    assert(cp_gpio_read(&low,0x10,&value) && value==0); /* output never manufactures ready input */
    CpLabGpio unknown={0};assert(!cp_gpio_read(&unknown,0x10,&value));
    puts("GPIO direct/set/clear/strap-preservation/input-output-isolation/rejection contracts passed");
}
