/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Source-derived sparse request latches; no hardware clock/reset/ready/IRQ. */
#include "qemu/log.h"
#include "qemu/bswap.h"
#include "system/dma.h"
#include "state.h"
typedef struct CpRequestDevice CpRequestDevice;
typedef struct { CpRequestDevice *owner;unsigned word;MemoryRegion mmio; } CpRequestRegion;
struct CpRequestDevice { CpRequestWords state;CpRequestRegion region[256];uint64_t reads; };
static const char cp_request_policy_sha[]="d21de1bb82d737746d793326bb68155084cd72392ad5ad417b283a8b9244b3c9";
static const char cp_request_code_sha[]="e47c57b883e283db9109e3ba501ed4d9cf00e30549a0b5f9368a8d9584ac87a5";
static bool cp_request_code_matches(void)
{
    g_autofree uint8_t *bytes=g_malloc(0x6000);
    if (dma_memory_read(&address_space_memory,0x52b000,bytes,0x5000,MEMTXATTRS_UNSPECIFIED)!=MEMTX_OK ||
        dma_memory_read(&address_space_memory,0xb71000,bytes+0x5000,0x1000,MEMTXATTRS_UNSPECIFIED)!=MEMTX_OK) { return false; }
    g_autofree gchar *digest=g_compute_checksum_for_data(G_CHECKSUM_SHA256,bytes,0x6000);
    return !strcmp(digest,cp_request_code_sha);
}
static MemTxResult cp_request_mmio_read(void *opaque,hwaddr offset,uint64_t *value,unsigned size,MemTxAttrs attrs)
{
    CpRequestRegion *r=opaque;uint32_t word=0;(void)attrs;
    if (size!=4 || !cp_request_code_matches() || !cp_request_word_read(&r->owner->state,r->word,offset,&word)) { *value=0;return MEMTX_ERROR; }
    *value=word;uint64_t n=++r->owner->reads;
    if (n<=32 || !(n&(n-1))) { qemu_log_mask(LOG_UNIMP,"CP_REQUEST_READ word=%x offset=%"HWADDR_PRIx" value=%08x count=%"PRIu64"\n",r->word*16,offset,word,n); }
    return MEMTX_OK;
}
static MemTxResult cp_request_mmio_write(void *opaque,hwaddr offset,uint64_t value,unsigned size,MemTxAttrs attrs)
{
    CpRequestRegion *r=opaque;(void)attrs;
    if (size!=4 || !cp_request_code_matches() || !cp_request_word_write(&r->owner->state,r->word,offset,value)) {
        qemu_log_mask(LOG_UNIMP,"CP_REQUEST_UNSUPPORTED word=%x offset=%"HWADDR_PRIx" value=%"PRIu64" size=%u\n",r->word*16,offset,value,size);return MEMTX_ERROR;
    }
    qemu_log_mask(LOG_UNIMP,"CP_REQUEST_WRITE word=%x offset=%"HWADDR_PRIx" value=%"PRIu64" requested=%08x hardware-confirmed=0\n",r->word*16,offset,value,r->owner->state.requested[r->word]);
    return MEMTX_OK;
}
static const MemoryRegionOps cp_request_ops={
    .read_with_attrs=cp_request_mmio_read,.write_with_attrs=cp_request_mmio_write,
    .endianness=DEVICE_LITTLE_ENDIAN,
    .valid={.min_access_size=4,.max_access_size=4,.unaligned=false},
};
static void cp_lab_request_words_init(MachineState *machine)
{
    const char *path=g_getenv("QEMU_SONY_CP_REQUEST_POLICY_FILE"),*expected=g_getenv("QEMU_SONY_CP_REQUEST_POLICY_SHA256"),*alias=g_getenv("QEMU_SONY_CP_REQUEST_ALIAS");
    if (!path) { return; }
    gchar *raw=NULL;gsize size=0;GError *error=NULL;
    static const char source_sha[]="f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428";
    if (!expected || strcmp(expected,cp_request_policy_sha) || !alias || (strcmp(alias,"zero") && strcmp(alias,"ones")) || !g_file_get_contents(path,&raw,&size,&error)) {
        error_report("Sparse request policy requires exact pinned input/hash and explicit alias");exit(1);
    }
    g_autofree gchar *digest=g_compute_checksum_for_data(G_CHECKSUM_SHA256,(const guchar *)raw,size);
    if (strcmp(digest,cp_request_policy_sha) || size!=1596 || memcmp(raw,"CPREQ73\0",8) || memcmp(raw+8,source_sha,64) ||
        ldl_le_p(raw+72)!=182 || memcmp(raw+76,cp_request_code_sha,64)) {
        error_report("Sparse request policy fingerprint/header mismatch");g_free(raw);exit(1);
    }
    CpRequestDevice *s=g_new0(CpRequestDevice,1);s->state.set_readback=!strcmp(alias,"ones") ? UINT32_MAX : 0;
    for (unsigned i=0;i<182;i++) {
        const uint8_t *record=(const uint8_t *)raw+140+i*8;uint32_t offset=ldl_le_p(record),mask=ldl_le_p(record+4);
        if (!cp_request_word_add(&s->state,offset,mask)) { error_report("Invalid sparse request policy word");g_free(raw);exit(1); }
        unsigned word=offset/16;CpRequestRegion *r=&s->region[word];r->owner=s;r->word=word;
        g_autofree gchar *name=g_strdup_printf("cp-source-request-%03x",offset);
        memory_region_init_io(&r->mmio,OBJECT(machine),&cp_request_ops,r,name,8);
        memory_region_add_subregion(get_system_memory(),0xf5400000ULL+offset,&r->mmio);
    }
    g_free(raw);g_printerr("CP_REQUEST_POLICY words=182 paired-source-only=1 alias=%s guest-code-pinned=1 software-request-only=1 physical-qualified=0\n",alias);
}
