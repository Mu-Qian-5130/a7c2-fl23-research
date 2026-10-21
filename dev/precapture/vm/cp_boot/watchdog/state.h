/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Offline reset-mode watchdog contract. Register/clock evidence: original
 * ILCE-7CM2 2.01 linux-kernel wdt.h/wdt.c and pinned CP register accesses.
 * Initial/reload TOP interpretation and sticky enable are model semantics;
 * physical reset routing/pulse timing are not qualified. Unsupported modes
 * fail; this state machine never changes a native service result or ready flag.
 */
#ifndef CP_LAB_WATCHDOG_H
#define CP_LAB_WATCHDOG_H
#include <stdint.h>
#include <stdbool.h>
#include <limits.h>

typedef struct {
    uint32_t cr, torr, misc, reset;
    uint64_t tick_ns, deadline;
    bool expired;
} CpLabWatchdog;

static inline uint64_t cp_wdt_period(const CpLabWatchdog *s, bool first)
{ return (UINT64_C(1) << (16 + ((s->torr >> (first ? 4 : 0)) & 15))) * s->tick_ns; }

static inline bool cp_wdt_enabled(const CpLabWatchdog *s)
{ return (s->cr & 1) && !s->reset; }

static inline void cp_wdt_advance(CpLabWatchdog *s, uint64_t now)
{ if (cp_wdt_enabled(s) && now >= s->deadline) { s->expired = true; } }

static inline uint64_t cp_wdt_deadline(const CpLabWatchdog *s)
{ return cp_wdt_enabled(s) && !s->expired ? s->deadline : UINT64_MAX; }

static inline bool cp_wdt_reset_write(CpLabWatchdog *s, uint32_t offset, uint32_t value)
{
    if ((value & ~UINT32_C(0x40000)) || (offset != 4 && offset != 8)) { return false; }
    if (offset == 4 && value) {
        s->reset = 0x40000;
        s->cr = s->torr = 0;
        s->deadline = 0;
        s->expired = false;
    } else if (offset == 8) { s->reset &= ~value; }
    return true;
}

static inline bool cp_wdt_write(CpLabWatchdog *s, uint32_t offset,
                                uint32_t value, uint64_t now)
{
    if (s->reset) { return false; }
    if (offset == 0) {
        if ((value & ~UINT32_C(0x1f)) || (value & 2) || ((value & 1) && !(s->misc & 1))) {
            return false; /* interrupt mode/unconnected reset route unsupported */
        }
    } else if (offset == 4) {
        if (value & ~UINT32_C(0xff)) { return false; }
    } else if (offset != 12) { return false; }
    cp_wdt_advance(s, now);
    if (offset == 0) {
        bool was_enabled = cp_wdt_enabled(s);
        s->cr = value | (s->cr & 1); /* disabling needs the reset controller */
        if (!was_enabled && cp_wdt_enabled(s)) {
            s->deadline = now + cp_wdt_period(s, true);
        }
    } else if (offset == 4) { s->torr = value; }
    else if ((value & 255) == 0x76 && !s->expired && cp_wdt_enabled(s)) {
        s->deadline = now + cp_wdt_period(s, false);
    }
    return true;
}

static inline bool cp_wdt_read(CpLabWatchdog *s, uint32_t offset,
                               uint64_t now, uint32_t *value)
{
    if (offset != 0 && offset != 4 && offset != 8 && offset != 16) { return false; }
    cp_wdt_advance(s, now);
    if (offset == 0) { *value = s->cr; }
    else if (offset == 4) { *value = s->torr; }
    else if (offset == 16) { *value = 0; } /* no interrupt mode admitted */
    else if (!cp_wdt_enabled(s)) { *value = UINT32_MAX; }
    else if (s->expired) { *value = 0; }
    else { *value = (uint32_t)((s->deadline-now+s->tick_ns-1)/s->tick_ns); }
    return true;
}
#endif
