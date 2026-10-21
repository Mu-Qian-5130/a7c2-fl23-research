/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Inferred PLL request model. No real oscillator/rates/IRQ or native LOCK.
 * Only fixture mode schedules a separate response, never silicon evidence.
 */
#include "qemu/timer.h"
#include "qemu/log.h"
#include "qemu/bswap.h"
#include "system/dma.h"
#include "state.h"
typedef struct CpPllDevice CpPllDevice;
typedef struct { CpPllDevice *owner;unsigned slot;uint64_t generation;QEMUTimer *timer; } CpPllActor;
typedef struct { CpPllDevice *owner;bool select,logic;MemoryRegion mmio; } CpPllRegion;
struct CpPllDevice {
    CpLabPll state;bool fixture,source_fixture;uint64_t reads;
    CpPllSourceProgram source[6];unsigned source_count;
    CpPllActor actor[5];CpPllRegion region[3];
};
static bool cp_pll_source_tables_match(CpPllDevice *s)
{
    for (unsigned row=0;row<s->source_count;row++) {
        unsigned preset=row/2,mode=row%2;uint8_t bytes[4];
        if (dma_memory_read(&address_space_memory,0xe949dc+preset*4,bytes,4,MEMTXATTRS_UNSPECIFIED)!=MEMTX_OK ||
            ldl_le_p(bytes)!=s->source[row].selection) { return false; }
        for (unsigned i=0;i<5;i++) {
            if (dma_memory_read(&address_space_memory,0xe948ec+i*0x18+preset*8+mode*4,bytes,4,MEMTXATTRS_UNSPECIFIED)!=MEMTX_OK ||
                (ldl_le_p(bytes)&CP_PLL_COEFF)!=s->source[row].coeff[i]) { return false; }
        }
        const unsigned offsets[2]={0x18,0x48};
        for (unsigned i=0;i<2;i++) {
            if (dma_memory_read(&address_space_memory,0xe94964+offsets[i]+preset*8+mode*4,bytes,4,MEMTXATTRS_UNSPECIFIED)!=MEMTX_OK ||
                (ldl_le_p(bytes)&0x7fe)!=s->source[row].div[i]) { return false; }
        }
    }
    return true;
}
static bool cp_pll_source_response_admitted(CpPllDevice *s,unsigned slot)
{
    return cp_pll_source_tables_match(s) && cp_pll_source_admitted(&s->state,s->source,s->source_count,slot);
}
static void cp_pll_fixture_response(void *opaque)
{
    CpPllActor *a=opaque;
    if (a->owner->source_fixture && !cp_pll_source_response_admitted(a->owner,a->slot)) {
        qemu_log_mask(LOG_UNIMP,"CP_PLL_SOURCE_FIXTURE_REJECT slot=%u phase=response pending-retained=1\n",a->slot);return;
    }
    if (cp_pll_actor_lock(&a->owner->state.slot[a->slot],a->generation)) {
        qemu_log_mask(LOG_UNIMP,"%s slot=%u generation=%"PRIu64" physical-qualified=0\n",a->owner->source_fixture ? "CP_PLL_SOURCE_FIXTURE_LOCK" : "CP_PLL_FIXTURE_LOCK",a->slot,a->generation);
    }
}
static MemTxResult cp_pll_mmio_read(void *opaque,hwaddr offset,uint64_t *value,unsigned size,MemTxAttrs attrs)
{
    CpPllRegion *r=opaque;CpPllDevice *s=r->owner;uint32_t word=0;(void)attrs;
    bool ok=size==4 && (r->logic ? cp_pll_logic_read(&s->state,offset,&word) :
        r->select ? cp_pll_select_read(&s->state,offset,&word) : cp_pll_read(&s->state,offset,&word));
    *value=word;if (!ok) { return MEMTX_ERROR; }
    s->reads++;
    if (s->reads<=24 || !(s->reads&(s->reads-1))) {
        qemu_log_mask(LOG_UNIMP,"CP_PLL_READ select=%u offset=%"HWADDR_PRIx" value=%08x count=%"PRIu64" logic=%u\n",r->select,offset,word,s->reads,r->logic);
    }
    return MEMTX_OK;
}
static MemTxResult cp_pll_mmio_write(void *opaque,hwaddr offset,uint64_t value,unsigned size,MemTxAttrs attrs)
{
    CpPllRegion *r=opaque;CpPllDevice *s=r->owner;(void)attrs;
    bool ok=size==4 && (r->logic ? cp_pll_logic_write(&s->state,offset,value) :
        r->select ? cp_pll_select_write(&s->state,offset,value) : cp_pll_write(&s->state,offset,value));
    if (!ok) {
        qemu_log_mask(LOG_UNIMP,"CP_PLL_UNSUPPORTED select=%u offset=%"HWADDR_PRIx" value=%"PRIu64" size=%u logic=%u\n",r->select,offset,value,size,r->logic);
        return MEMTX_ERROR;
    }
    qemu_log_mask(LOG_UNIMP,"CP_PLL_WRITE select=%u offset=%"HWADDR_PRIx" value=%"PRIu64" logic=%u\n",r->select,offset,value,r->logic);
    if (!r->select && !r->logic && offset<=16) {
        unsigned slot=offset/4;CpPllSlot *p=&s->state.slot[slot];CpPllActor *a=&s->actor[slot];
        if (s->fixture && p->pending && (p->config&(CP_PLL_GATE|CP_PLL_START))==(CP_PLL_GATE|CP_PLL_START)) {
            if (s->source_fixture && !cp_pll_source_response_admitted(s,slot)) {
                timer_del(a->timer);qemu_log_mask(LOG_UNIMP,"CP_PLL_SOURCE_FIXTURE_REJECT slot=%u phase=start pending-retained=1\n",slot);
            } else { a->generation=p->generation;timer_mod_ns(a->timer,qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL)+1000); }
        } else { timer_del(a->timer); }
    }
    return MEMTX_OK;
}
static const MemoryRegionOps cp_pll_ops={
    .read_with_attrs=cp_pll_mmio_read,.write_with_attrs=cp_pll_mmio_write,
    .endianness=DEVICE_LITTLE_ENDIAN,
    .valid={.min_access_size=4,.max_access_size=4,.unaligned=false},
};
static void cp_pll_load_source_fixture(CpPllDevice *s)
{
    const char *path=g_getenv("QEMU_SONY_CP_PLL_SOURCE_FILE"),*expected=g_getenv("QEMU_SONY_CP_PLL_SOURCE_SHA256");
    static const char cp_sha[]="f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428";
    gchar *raw=NULL;gsize size=0;GError *error=NULL;
    if (!path || !expected || strlen(expected)!=64 || !g_file_get_contents(path,&raw,&size,&error)) {
        error_report("PLL source fixture requires an explicit readable file and SHA256");exit(1);
    }
    g_autofree gchar *digest=g_compute_checksum_for_data(G_CHECKSUM_SHA256,(const guchar *)raw,size);
    if (strcmp(digest,expected) || size!=268 || memcmp(raw,"CPLLSRC1",8) || memcmp(raw+8,cp_sha,64) || ldl_le_p(raw+72)!=6) {
        error_report("PLL source fixture fingerprint/header mismatch");g_free(raw);exit(1);
    }
    s->source_count=6;
    for (unsigned row=0;row<6;row++) {
        const uint8_t *record=(const uint8_t *)raw+76+row*32;
        s->source[row].selection=ldl_le_p(record);
        for (unsigned i=0;i<5;i++) { s->source[row].coeff[i]=ldl_le_p(record+4+i*4); }
        for (unsigned i=0;i<2;i++) { s->source[row].div[i]=ldl_le_p(record+24+i*4); }
        if (!cp_pll_source_program_valid(&s->source[row])) { error_report("PLL source fixture contains unknown field bits");g_free(raw);exit(1); }
    }
    g_free(raw);
    g_printerr("CP_PLL_SOURCE_FIXTURE admitted-sha256=%s header-source-pinned=1 guest-ROM-checked-at-request=1 hardware-validity-unqualified=1\n",digest);
}
static void cp_lab_pll_init(MachineState *machine)
{
    const char *profile=g_getenv("QEMU_SONY_CP_PLL_PROFILE"),*alias=g_getenv("QEMU_SONY_CP_PLL_ALIAS");
    if (!profile) { return; }
    if (!alias || (strcmp(alias,"zero") && strcmp(alias,"ones")) ||
        (strcmp(profile,"absent") && strcmp(profile,"fixture") && strcmp(profile,"source-fixture"))) { error_report("Invalid PLL model profile");exit(1); }
    CpPllDevice *s=g_new0(CpPllDevice,1);s->source_fixture=!strcmp(profile,"source-fixture");s->fixture=strcmp(profile,"absent")!=0;
    if (s->source_fixture) { cp_pll_load_source_fixture(s); }
    s->state.alias_readback=!strcmp(alias,"ones") ? UINT32_MAX : 0;
    for (unsigned i=0;i<5;i++) {
        s->actor[i].owner=s;s->actor[i].slot=i;s->actor[i].timer=timer_new_ns(QEMU_CLOCK_VIRTUAL,cp_pll_fixture_response,&s->actor[i]);
    }
    const uint64_t bases[3]={0xf1388100,0xf1388200,0xf1388070},sizes[3]={0x5c,12,12};
    const char *names[3]={"cp-PLL-config","cp-PLL-select","cp-PLL-logic-bit22"};
    for (unsigned i=0;i<3;i++) {
        s->region[i].owner=s;s->region[i].select=i==1;s->region[i].logic=i==2;
        memory_region_init_io(&s->region[i].mmio,OBJECT(machine),&cp_pll_ops,&s->region[i],names[i],sizes[i]);
        memory_region_add_subregion(get_system_memory(),bases[i],&s->region[i].mmio);
    }
    g_printerr("CP_PLL_MODEL backend=%s alias=%s initial-config=0 inferred-response=1 no-rates-or-IRQ=1 physical-qualified=0\n",profile,alias);
}
