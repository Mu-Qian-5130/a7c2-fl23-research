#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "counter.h"
int main(void) {
    CpLabCounter s = {.base_tick_ns=250};
    uint32_t value;
    assert(cp_counter_write(&s,0,0,0));
    assert(cp_counter_write(&s,4,0x11,0));
    assert(cp_counter_write(&s,0,0x1022,0)); /* native CP mode2, /4 */
    assert(cp_counter_read(&s,12,999,&value) && value==0);
    assert(cp_counter_read(&s,12,1000,&value) && value==1);
    assert(cp_counter_read(&s,12,9999,&value) && value==9);
    assert(cp_counter_write(&s,0,0x22,10000)); /* stop at10 */
    assert(cp_counter_read(&s,12,90000,&value) && value==10);
    assert(cp_counter_write(&s,8,20,90000));
    assert(cp_counter_write(&s,0,0x1122,90000));
    assert(cp_counter_deadline(&s)==100000);
    cp_counter_advance(&s,99999); assert(!cp_counter_irq(&s));
    cp_counter_advance(&s,100000); assert(cp_counter_irq(&s));
    assert(s.count==20 && cp_counter_deadline(&s)==UINT64_MAX);
    assert(cp_counter_write(&s,4,1,100000)); assert(!cp_counter_irq(&s));
    assert(cp_counter_deadline(&s)==100000+UINT64_C(0x100000000)*1000);
    assert(cp_counter_write(&s,0,0x1022,100000));
    cp_counter_advance(&s,200000); assert(!cp_counter_irq(&s));
    assert(cp_counter_write(&s,4,0x11,200000)); assert(s.count==0);
    assert(cp_counter_write(&s,16,0xfffffff0,200000));
    assert(cp_counter_write(&s,8,0x10,200000));
    assert(cp_counter_write(&s,0,0x1122,200000));
    assert(cp_counter_deadline(&s)==232000);
    cp_counter_advance(&s,231999); assert(!cp_counter_irq(&s));
    cp_counter_advance(&s,232000); assert(cp_counter_irq(&s) && s.count==0x10);
    /* Changed divider affects actual elapsed count, not merely a register. */
    assert(cp_counter_write(&s,4,0x11,232000));
    assert(cp_counter_write(&s,0,0x1031,232000)); /* official AP mode3, /2 */
    assert(cp_counter_read(&s,12,242000,&value) && value==20);
    CpLabCounter before=s;
    assert(!cp_counter_write(&s,0,0x1000,242000)); /* unsupported periodic */
    assert(memcmp(&s,&before,sizeof(s))==0);
    assert(!cp_counter_write(&s,4,2,242000));
    assert(!cp_counter_write(&s,12,123,242000));
    assert(!cp_counter_read(&s,20,242000,&value));
    puts("Counter elapsed/stop/compare/clear/wrap/divider/rejection contracts passed");
}
