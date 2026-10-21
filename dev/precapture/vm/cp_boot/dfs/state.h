/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Inferred CP DFS protocol, NOT a clock tree or measured silicon model.
 * No backend => request stays pending. Completion requires an explicit actor.
 * Event/control roles are inferred from original clear/poll/request sequences.
 */
#ifndef CP_LAB_DFS_H
#define CP_LAB_DFS_H
#include <stdint.h>
#include <stdbool.h>
typedef struct {
    uint32_t events,control,command,result;
    bool command_written,active;
    uint64_t starts,completions;
} CpLabDfs;
static inline bool cp_dfs_read(const CpLabDfs *s,unsigned offset,uint32_t *value)
{
    if (offset==0) { *value=s->events; }
    else if (offset==0x10) { *value=s->result | (s->active ? 0x100u : 0u); }
    else { return false; }
    return true;
}
static inline bool cp_dfs_write(CpLabDfs *s,unsigned offset,uint32_t value)
{
    if (offset==0) {
        if (value&~0x101u) { return false; }
        s->events&=~value;return true;
    }
    if (offset==4) {
        if (value&~0x101u) { return false; }
        s->control=value;return true;
    }
    if (offset==0xc) {
        if (s->active || (value&~0x107u) || (value&255)>6) { return false; }
        s->command=value;s->command_written=true;return true;
    }
    if (offset==8) {
        if (value!=1 || s->active || !s->command_written) { return false; }
        s->active=true;s->command_written=false;s->starts++;return true;
    }
    return false;
}
static inline bool cp_dfs_actor_complete(CpLabDfs *s)
{
    if (!s->active) { return false; }
    s->active=false;s->result=s->command&255;s->events|=1;s->completions++;return true;
}
#endif
