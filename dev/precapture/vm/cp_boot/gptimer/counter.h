/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Offline CP laboratory counter/compare contract, not a Sony silicon model.
 * Offsets/bits: Sony ILCE-7CM2 Ver2.01 linux-kernel include/linux/cxd_timer.h.
 * CP mode2 and the supplied clock/IRQ route remain explicit model assumptions.
 * Only free-running modes2/3 are supported; other running modes fault.
 */
#ifndef CP_LAB_COUNTER_H
#define CP_LAB_COUNTER_H
#include <stdint.h>
#include <stdbool.h>
#include <limits.h>

typedef struct {
    uint32_t control, compare, count;
    uint64_t anchor_ns, base_tick_ns;
    bool pending, compare_valid;
} CpLabCounter;

static inline bool cp_counter_running(const CpLabCounter *s)
{ return (s->control & 0x1000) != 0; }

static inline uint64_t cp_counter_tick(const CpLabCounter *s)
{ return s->base_tick_ns << (s->control & 7); }

static inline uint64_t cp_counter_distance(const CpLabCounter *s)
{
    uint32_t delta = s->compare - s->count;
    return delta ? delta : UINT64_C(0x100000000);
}

static inline void cp_counter_advance(CpLabCounter *s, uint64_t now)
{
    if (!cp_counter_running(s)) { s->anchor_ns = now; return; }
    uint64_t tick = cp_counter_tick(s);
    uint64_t steps = (now - s->anchor_ns) / tick;
    if (s->compare_valid && (s->control & 0x100) &&
        steps >= cp_counter_distance(s)) { s->pending = true; }
    s->count += (uint32_t)steps;
    s->anchor_ns += steps * tick;
}

static inline bool cp_counter_irq(const CpLabCounter *s)
{ return s->pending && (s->control & 0x100); }

static inline uint64_t cp_counter_deadline(const CpLabCounter *s)
{
    if (!cp_counter_running(s) || !(s->control & 0x100) ||
        !s->compare_valid || s->pending) { return UINT64_MAX; }
    return s->anchor_ns + cp_counter_distance(s) * cp_counter_tick(s);
}

static inline bool cp_counter_write(CpLabCounter *s, uint32_t offset,
                                    uint32_t value, uint64_t now)
{
    /* Validate before changing state. Unsupported registers/modes never return
     * an invented success to the original firmware.
     */
    if (offset == 0) {
        uint32_t mode = (value >> 4) & 3;
        if ((value & ~UINT32_C(0x1137)) ||
            ((value & 0x1000) && mode != 2 && mode != 3)) { return false; }
    } else if (offset == 4) {
        if (value & ~UINT32_C(0x11)) { return false; }
    } else if (offset != 8 && offset != 16) { return false; }
    cp_counter_advance(s, now);
    switch (offset) {
    case 0:
        s->control = value;
        s->anchor_ns = now;
        break;
    case 4:
        if (value & 0x10) { s->count = 0; s->anchor_ns = now; }
        if (value & 1) { s->pending = false; }
        break;
    case 8:
        s->compare = value; s->compare_valid = true;
        break;
    case 16:
        s->count = value; s->anchor_ns = now;
        break;
    }
    return true;
}

static inline bool cp_counter_read(CpLabCounter *s, uint32_t offset,
                                   uint64_t now, uint32_t *value)
{
    if (offset != 0 && offset != 8 && offset != 12) { return false; }
    cp_counter_advance(s, now);
    *value = offset == 0 ? s->control : offset == 8 ? s->compare : s->count;
    return true;
}
#endif
