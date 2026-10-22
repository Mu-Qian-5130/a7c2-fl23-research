/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Three write-first requested words. No timing units/edges or frame IRQ. */
#include "system/dma.h"
#include "../config_rmw/qemu_source_word.h"
static bool cp_mtg_period_source_matches(void)
{
    uint8_t raw[448];
    if(dma_memory_read(&address_space_memory,0xb9b672,raw,166,MEMTXATTRS_UNSPECIFIED)!=MEMTX_OK ||
       dma_memory_read(&address_space_memory,0xb977aa,raw+166,146,MEMTXATTRS_UNSPECIFIED)!=MEMTX_OK ||
       dma_memory_read(&address_space_memory,0xb8b0a6,raw+312,70,MEMTXATTRS_UNSPECIFIED)!=MEMTX_OK ||
       dma_memory_read(&address_space_memory,0xfe2a32,raw+382,66,MEMTXATTRS_UNSPECIFIED)!=MEMTX_OK) { return false; }
    g_autofree gchar *digest=g_compute_checksum_for_data(G_CHECKSUM_SHA256,raw,sizeof(raw));
    return !strcmp(digest,"90ae0aa67651f166a25406281cd7d0c0c879f4304bd5b1d76e1026391fdae459");
}
static void cp_lab_mtg_period_init(MachineState *machine)
{
    const char *profile=g_getenv("QEMU_SONY_CP_MTG_PERIOD_PROFILE");
    if(!profile) { return; }
    if(strcmp(profile,"write-first")) {
        error_report("MTG period fixture requires explicit write-first profile; no initial hardware word");exit(1);
    }
    static const char *const tags[]={"CP_MTG_PERIOD0","CP_MTG_PERIOD1","CP_MTG_PERIOD2"};
    static const char *const regions[]={"cp-mtg-period0","cp-mtg-period1","cp-mtg-period2"};
    for(unsigned i=0;i<3;i++) {
        cp_lab_source_word_init(machine,"QEMU_SONY_CP_MTG_PERIOD_PROFILE",0xf5411010ULL+i*4,
            UINT32_MAX,tags[i],regions[i],cp_mtg_period_source_matches);
    }
}
