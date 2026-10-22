/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Optional one-word conditional fixture. No physical/reset/ready semantics. */
#include "system/dma.h"
#include "qemu_source_word.h"

static bool cp_config_source_matches(void)
{
    uint8_t raw[86];
    if(dma_memory_read(&address_space_memory,0xb7160a,raw,36,MEMTXATTRS_UNSPECIFIED)!=MEMTX_OK ||
       dma_memory_read(&address_space_memory,0xb74730,raw+36,40,MEMTXATTRS_UNSPECIFIED)!=MEMTX_OK ||
       dma_memory_read(&address_space_memory,0x68530a,raw+76,10,MEMTXATTRS_UNSPECIFIED)!=MEMTX_OK) { return false; }
    g_autofree gchar *digest=g_compute_checksum_for_data(G_CHECKSUM_SHA256,raw,sizeof(raw));
    return !strcmp(digest,"81c6b09c1f94a7e872e03547f48f36a0f63bfaaa03c3c7b550f333ba95aaba2a");
}
static void cp_lab_config_word_init(MachineState *machine)
{
    cp_lab_source_word_init(machine,"QEMU_SONY_CP_CONFIG_INITIAL",0xf5408038ULL,
        CP_CONFIG_MASK,"CP_CONFIG","cp-config-fixture-word",cp_config_source_matches);
}
