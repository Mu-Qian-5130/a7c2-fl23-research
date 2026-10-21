#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "state.h"
typedef struct { unsigned char local[128],peer[128];bool present;unsigned fail_after; } Memory;
static int move(void *opaque,unsigned direction,uint64_t src,uint64_t dst,uint32_t size,uint32_t *done) {
    Memory *m=opaque;*done=0;
    if (!m->present) { return CP_EDMA_WAIT; }
    const uint64_t remote=UINT64_C(0x400000000);
    unsigned char *source=direction ? m->peer : m->local;
    unsigned char *target=direction ? m->local : m->peer;
    if (direction) { if (src<remote) { return CP_EDMA_ERROR; } src-=remote; }
    else { if (dst<remote) { return CP_EDMA_ERROR; } dst-=remote; }
    if (src>=128 || dst>=128) { return CP_EDMA_ERROR; }
    uint32_t allowed=size;
    if (allowed>128-src) { allowed=128-src; }
    if (allowed>128-dst) { allowed=128-dst; }
    if (m->fail_after && dst+allowed>m->fail_after) { allowed=dst<m->fail_after ? m->fail_after-dst : 0; }
    memcpy(target+dst,source+src,allowed);*done=allowed;
    return allowed==size ? CP_EDMA_OK : CP_EDMA_ERROR;
}
static void program(CpEdma *s,unsigned d,unsigned c,uint32_t length,uint32_t local,uint32_t remote) {
    uint32_t base=0x200+c*0x200+d*0x100;
    assert(cp_edma_write(s,d?0x2c:0x0c,1));
    assert(cp_edma_write(s,(d?0x168:0x128)+c*4,1));
    assert(cp_edma_write(s,base,8));assert(cp_edma_write(s,base+8,length));
    assert(cp_edma_write(s,base+12,d?remote:local));assert(cp_edma_write(s,base+16,d?4:0));
    assert(cp_edma_write(s,base+20,d?local:remote));assert(cp_edma_write(s,base+24,d?0:4));
    assert(cp_edma_write(s,d?0x30:0x10,c));
}
int main(void) {
    CpEdma s={0};Memory m={0};uint32_t value;
    for (unsigned i=0;i<128;i++) { m.local[i]=i^0x5a;m.peer[i]=0xa5; }
    assert(cp_edma_write(&s,0x54,0xffffffff));assert(cp_edma_write(&s,0xa8,0xffffffff));
    s.side_enable=0xffff;program(&s,0,0,32,8,16);
    cp_edma_progress(&s,0,0,8,move,&m);
    assert(s.channel[0][0].active && s.channel[0][0].done==0 && s.status[0]==0 && !cp_edma_irq(&s));
    assert(m.peer[16]==0xa5);assert(!cp_edma_write(&s,0x0c,0));
    assert(!cp_edma_write(&s,0x10,0x80000000)); /* no fabricated cancellation */
    assert(!cp_edma_write(&s,0x20c,99));
    m.present=true;cp_edma_progress(&s,0,0,8,move,&m);
    assert(s.channel[0][0].done==8 && s.status[0]==0 && !cp_edma_irq(&s));
    assert(memcmp(m.peer+16,m.local+8,8)==0 && m.peer[24]==0xa5);
    cp_edma_progress(&s,0,0,24,move,&m);
    assert(!s.channel[0][0].active && s.status[0]==1 && !cp_edma_irq(&s));
    assert(memcmp(m.peer+16,m.local+8,32)==0 && m.peer[15]==0xa5 && m.peer[48]==0xa5);
    assert(cp_edma_read(&s,0x5c,&value) && value==0);
    assert(cp_edma_write(&s,0x54,0));assert(cp_edma_irq(&s));
    assert(cp_edma_write(&s,0x200,0x60));assert(!cp_edma_irq(&s)); /* LIE clear, status retained */
    assert(s.status[0]==1);assert(cp_edma_write(&s,0x58,1));assert(s.status[0]==0);
    assert(cp_edma_write(&s,0xa8,0));program(&s,1,1,12,64,20);
    cp_edma_progress(&s,1,1,12,move,&m);
    assert(memcmp(m.local+64,m.peer+20,12)==0 && s.status[1]==2 && cp_edma_irq(&s));
    assert(cp_edma_write(&s,0xac,2));assert(!cp_edma_irq(&s));
    m.fail_after=4;program(&s,0,2,16,0,0);
    cp_edma_progress(&s,0,2,16,move,&m);
    assert(s.channel[0][2].done==4 && !s.channel[0][2].active && s.channel[0][2].state==0x40);
    assert(s.status[0]==(1u<<18) && !(s.status[0]&4));assert(memcmp(m.peer,m.local,4)==0);
    assert(!cp_edma_read(&s,0x5c,&value)); /* never hide unmodeled abort syndrome with zero */
    assert(cp_edma_read(&s,0x608,&value) && value==12);
    assert(!cp_edma_write(&s,0x4c,4));assert(!cp_edma_write(&s,0x600,0x300));
    assert(!cp_edma_write(&s,0x0c,2));assert(!cp_edma_read(&s,0x10000,&value));
    puts("eDMA copied-bytes/read-write namespaces/absent-peer/prefix-error/IRQ-mask/clear/rejection contracts passed");
}
