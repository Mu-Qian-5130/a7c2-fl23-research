/* SPDX-License-Identifier: GPL-2.0-or-later */
/* MTG selector storage only. No timing edges, frame IRQ, sensor or reset. */
#include "system/dma.h"
#include "../config_rmw/qemu_source_word.h"
static bool cp_mtg_select_source_matches(void)
{
    uint8_t raw[112];
    if(dma_memory_read(&address_space_memory,0xb9b580,raw,68,MEMTXATTRS_UNSPECIFIED)!=MEMTX_OK ||
       dma_memory_read(&address_space_memory,0xb977c6,raw+68,6,MEMTXATTRS_UNSPECIFIED)!=MEMTX_OK ||
       dma_memory_read(&address_space_memory,0xfe2a05,raw+74,12,MEMTXATTRS_UNSPECIFIED)!=MEMTX_OK ||
       dma_memory_read(&address_space_memory,0xb8aed2,raw+86,26,MEMTXATTRS_UNSPECIFIED)!=MEMTX_OK) { return false; }
    g_autofree gchar *digest=g_compute_checksum_for_data(G_CHECKSUM_SHA256,raw,sizeof(raw));
    return !strcmp(digest,"c6d1305f81a638c2839311f4e5e9062bb766eafc5e8c2e4b4bb8e15096b940c9");
}
static void cp_lab_mtg_select_init(MachineState *machine)
{
    cp_lab_source_word_init(machine,"QEMU_SONY_CP_MTG_SELECT_INITIAL",0xf5411000ULL,
        3,"CP_MTG_SELECT","cp-mtg-select-fixture-word",cp_mtg_select_source_matches);
}
