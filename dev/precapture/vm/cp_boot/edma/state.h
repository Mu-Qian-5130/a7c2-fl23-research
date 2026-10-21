/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Offline non-LL eDMA contract. Layout: original2.01 pciedma/regs.h.
 * This is not a silicon/PCIe-link model. Completion requires the backend's
 * actual copied prefix. WAIT retains RUN ownership; errors never become DONE.
 */
#ifndef CP_LAB_EDMA_H
#define CP_LAB_EDMA_H
#include <stdint.h>
#include <stdbool.h>
#include <limits.h>

enum { CP_EDMA_OK=0, CP_EDMA_WAIT=1, CP_EDMA_ERROR=2 };
typedef int (*CpEdmaCopy)(void *,unsigned,uint64_t,uint64_t,uint32_t,uint32_t *);
typedef struct {
    uint32_t control,size,done,power,src[2],dst[2],llp[2],state;
    bool active;
} CpEdmaChannel;
typedef struct {
    uint32_t enable[2],status[2],mask[2],llerr[2],side_enable;
    CpEdmaChannel channel[2][8];
} CpEdma;

static inline uint64_t cp_edma_address(const uint32_t words[2])
{ return ((uint64_t)words[1]<<32)|words[0]; }

static inline uint32_t cp_edma_summary(const CpEdma *s,unsigned d)
{
    uint32_t status=s->status[d]&~s->mask[d],bits=0;
    for (unsigned c=0;c<8;c++) {
        if ((s->channel[d][c].control&8) && (status&((1u<<c)|(1u<<(16+c))))) { bits|=1u<<c; }
    }
    return bits;
}

static inline bool cp_edma_irq(const CpEdma *s)
{ return (cp_edma_summary(s,0)&s->side_enable&255) ||
         (cp_edma_summary(s,1)&(s->side_enable>>8)&255); }

static inline bool cp_edma_active(const CpEdma *s)
{
    for (unsigned d=0;d<2;d++) for (unsigned c=0;c<8;c++) if (s->channel[d][c].active) { return true; }
    return false;
}

static inline bool cp_edma_global(uint32_t offset,unsigned *direction,unsigned *kind)
{
    static const uint32_t registers[2][6]={{0x0c,0x10,0x4c,0x54,0x58,0x90},
                                         {0x2c,0x30,0xa0,0xa8,0xac,0xc4}};
    for (unsigned d=0;d<2;d++) for (unsigned k=0;k<6;k++) if (offset==registers[d][k]) {
        *direction=d;*kind=k;return true;
    }
    return false;
}

static inline bool cp_edma_channel_offset(uint32_t offset,unsigned *d,unsigned *c,unsigned *reg)
{
    if (offset<0x200 || offset>=0x1200 || (offset&3)) { return false; }
    offset-=0x200;*c=offset/0x200;*d=(offset%0x200)/0x100;*reg=offset%0x100;
    return *reg<=0x20;
}

static inline bool cp_edma_read(const CpEdma *s,uint32_t offset,uint32_t *value)
{
    unsigned d,c,k,r;
    if (offset==0x5c || offset==0xb4 || offset==0xb8) {
        d=offset==0x5c ? 0 : 1;
        if (s->status[d]&UINT32_C(0xffff0000)) { return false; } /* abort syndrome unimplemented */
        *value=0;return true;
    }
    if (cp_edma_global(offset,&d,&k)) {
        if (k==0) { *value=s->enable[d]; }
        else if (k==2) { *value=s->status[d]; }
        else if (k==3) { *value=s->mask[d]; }
        else if (k==5) { *value=s->llerr[d]; }
        else { return false; } /* doorbell/clear are not admitted reads */
        return true;
    }
    for (d=0;d<2;d++) {
        uint32_t base=d ? 0x168 : 0x128;
        if (offset>=base && offset<base+32 && !(offset&3)) { *value=s->channel[d][(offset-base)/4].power;return true; }
    }
    if (!cp_edma_channel_offset(offset,&d,&c,&r)) { return false; }
    const CpEdmaChannel *q=&s->channel[d][c];
    if (r==0) { *value=q->control|(q->active ? 0x20 : q->state ? q->state : 0x60); }
    else if (r==4) { *value=0; }
    else if (r==8) { *value=q->size-q->done; }
    else if (r<=0x10) { *value=q->src[(r-12)/4]; }
    else if (r<=0x18) { *value=q->dst[(r-20)/4]; }
    else { *value=q->llp[(r-28)/4]; }
    return true;
}

static inline bool cp_edma_write(CpEdma *s,uint32_t offset,uint32_t value)
{
    unsigned d,c,k,r;
    if (cp_edma_global(offset,&d,&k)) {
        if (k==0) {
            if (value>1) { return false; }
            if (!value) for (c=0;c<8;c++) if (s->channel[d][c].active) { return false; }
            s->enable[d]=value;
        } else if (k==1) {
            if (value>=8) { return false; } /* STOP/LL not implemented, never fake cancel */
            CpEdmaChannel *q=&s->channel[d][value];
            if (!s->enable[d] || !q->power || q->active || !q->size ||
                cp_edma_address(q->src)>UINT64_MAX-(q->size-1) ||
                cp_edma_address(q->dst)>UINT64_MAX-(q->size-1)) { return false; }
            q->done=0;q->active=true;q->state=0x20;
        } else if (k==3) { s->mask[d]=value; }
        else if (k==4) { s->status[d]&=~value; }
        else if (k==5) { s->llerr[d]=value; }
        else { return false; } /* status cannot be written into success */
        return true;
    }
    for (d=0;d<2;d++) {
        uint32_t base=d ? 0x168 : 0x128;
        if (offset>=base && offset<base+32 && !(offset&3)) {
            c=(offset-base)/4;
            if (value>1 || s->channel[d][c].active) { return false; }
            s->channel[d][c].power=value;return true;
        }
    }
    if (!cp_edma_channel_offset(offset,&d,&c,&r)) { return false; }
    CpEdmaChannel *q=&s->channel[d][c];
    if (q->active) { return false; }
    if (r==0) {
        if (value&~UINT32_C(0x68)) { return false; } /* non-LL LIE plus read-only CS */
        q->control=value&8;
    } else if (r==4) { if (value) { return false; } }
    else if (r==8) { q->size=value;q->done=0; }
    else if (r<=0x10) { q->src[(r-12)/4]=value; }
    else if (r<=0x18) { q->dst[(r-20)/4]=value; }
    else { q->llp[(r-28)/4]=value; }
    return true;
}

static inline void cp_edma_progress(CpEdma *s,unsigned d,unsigned c,uint32_t budget,
                                    CpEdmaCopy copy,void *context)
{
    CpEdmaChannel *q=&s->channel[d][c];
    if (!q->active || !budget) { return; }
    uint32_t size=q->size-q->done,done=0;
    if (size>budget) { size=budget; }
    int result=copy(context,d,cp_edma_address(q->src)+q->done,
                    cp_edma_address(q->dst)+q->done,size,&done);
    if (done>size || (result==CP_EDMA_WAIT && done) || result>CP_EDMA_ERROR || result<0) {
        result=CP_EDMA_ERROR;done=0;
    }
    q->done+=done;
    if (result==CP_EDMA_ERROR || (result==CP_EDMA_OK && !done)) {
        q->active=false;q->state=0x40;s->status[d]|=1u<<(16+c);
    } else if (result==CP_EDMA_OK && q->done==q->size) {
        q->active=false;q->state=0x60;s->status[d]|=1u<<c;
    }
}
#endif
