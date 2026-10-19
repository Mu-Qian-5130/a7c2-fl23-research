/* Native donor S1/AF-ON predicate, independently owned state inputs.
 * No target master fields, button delivery, scheduler or camera I/O.
 *
 * Donor file0xaad012 calls gate0xac4b0a, then constructs a button mask.
 * raw_field_86c is donor SET_S1AF, command0x4064. Its proven target
 * counterpart is master+0x700, not target master+0x86c.
 */
typedef unsigned int u32;
extern u32 precapture_enable_gate(u32 mode, u32 enabled,
                                  u32 debug_flags, u32 debug_selection);

u32 precapture_s1_active(u32 enabled, u32 mode, u32 trigger,
                         u32 raw_field_86c, u32 buttons,
                         u32 debug_flags, u32 debug_selection) {
    u32 selected = 0x00c2000eu;
    if (!precapture_enable_gate(mode, enabled, debug_flags, debug_selection))
        return 0;
    if (debug_flags & 0x10u) {
        if (debug_selection & 0x10u)
            return (buttons & selected) != 0;
        if (debug_selection & 0x20u) {
            selected = 0;
            goto af_on;
        }
        if (debug_selection & 0x40u)
            trigger = 3;
    }
    if ((trigger & 1u) == 0)
        selected = 0;
    if (trigger & 2u) {
af_on:
        selected |= 0x01242010u;
        if (raw_field_86c == 0)
            selected = 0x01e6201eu;
    }
    return (buttons & selected) != 0;
}

static u32 little_word(const unsigned char *p) {
    return (u32)p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24;
}

/* Original target SET_CAP_MODE0x4014 stores mode at master+0x138.
 * Original target SET_S1AF0x4064 stores its byte input as word+0x700.
 * enabled/trigger come from independently owned pre-capture state.
 * The real S1 owner must serialize access; this leaf provides no task hook.
 */
u32 precapture_target_s1_active(u32 enabled, u32 trigger,
                                const unsigned char *target_master,
                                u32 buttons, u32 flags, u32 selection) {
    if (!target_master)
        return 0;
    return precapture_s1_active(enabled, little_word(target_master + 0x138),
                                trigger, little_word(target_master + 0x700),
                                buttons, flags, selection);
}
