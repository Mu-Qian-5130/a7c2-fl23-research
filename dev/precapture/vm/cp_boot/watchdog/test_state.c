#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "state.h"
int main(void) {
    CpLabWatchdog s={.tick_ns=250};
    uint32_t value;
    assert(cp_wdt_reset_write(&s,4,0x40000));
    assert(s.reset && !cp_wdt_write(&s,0,1,0));
    assert(cp_wdt_reset_write(&s,8,0x40000));
    assert(!cp_wdt_write(&s,0,1,0)); /* route must be explicitly connected */
    s.misc=1;
    assert(cp_wdt_write(&s,4,0x17,0)); /* first TOP1; reload TOP7 */
    assert(cp_wdt_write(&s,0,1,0));
    assert(cp_wdt_deadline(&s)==32768000);
    assert(cp_wdt_read(&s,8,250,&value) && value==131071);
    assert(cp_wdt_write(&s,12,0x76,1000000));
    assert(cp_wdt_deadline(&s)==2098152000);
    uint64_t deadline=s.deadline;
    assert(cp_wdt_write(&s,12,0x75,2000000) && s.deadline==deadline);
    assert(cp_wdt_write(&s,0,0,2000000) && cp_wdt_enabled(&s));
    assert(s.deadline==deadline);
    cp_wdt_advance(&s,deadline-1);assert(!s.expired);
    assert(cp_wdt_read(&s,8,deadline-1,&value) && value==1);
    cp_wdt_advance(&s,deadline);assert(s.expired);
    assert(cp_wdt_deadline(&s)==UINT64_MAX);
    assert(cp_wdt_write(&s,12,0x76,deadline+1) && s.expired); /* cannot revive expired */
    assert(cp_wdt_reset_write(&s,4,0x40000));
    assert(!s.expired && s.cr==0 && s.torr==0 && s.misc==1);
    assert(cp_wdt_reset_write(&s,8,0x40000));
    assert(cp_wdt_write(&s,4,0,0));assert(cp_wdt_write(&s,0,1,0));
    assert(cp_wdt_deadline(&s)==16384000);
    CpLabWatchdog before=s;
    assert(!cp_wdt_write(&s,0,3,0));assert(!cp_wdt_write(&s,8,1,0));
    assert(!cp_wdt_write(&s,4,0x100,0));assert(!cp_wdt_reset_write(&s,4,1));
    assert(!cp_wdt_read(&s,20,0,&value));
    assert(memcmp(&s,&before,sizeof(s))==0);
    puts("Watchdog reset/release/count/first-TOP/reload/bad-feed/expiry/sticky-enable/rejection contracts passed");
}
