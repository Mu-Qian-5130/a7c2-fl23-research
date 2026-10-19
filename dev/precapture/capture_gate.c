/* Donor-matched enable predicate. No globals, OS calls or device hooks.
 *
 * Original donor: ILCE-1M2 4.00 CP file 0xac4b0a.
 * Target ILCE-7CM2 2.01 file 0xa2f0fa has only the debug override;
 * its ordinary path returns zero. Target runtime state/placement is unbound.
 *
 * The integer mode values are recovered raw values, not named camera modes.
 * They must not be mapped to user-visible modes without further evidence.
 */
typedef unsigned int u32;

u32 precapture_enable_gate(u32 mode, u32 enabled,
                          u32 debug_flags, u32 debug_selection) {
    if ((debug_flags & 0x10u) == 0u)
        return enabled == 1u;
    return (mode == 1u || mode == 0x21u || mode == 0x1au) &&
           (debug_selection & 0xffu) != 0xffu;
}

/* Original donor frame-parameter producer calls the enable predicate only
 * when the word at its private context+0x10 is zero. Meaning of this word
 * remains unbound; preserve the condition, rather than guessing its name.
 */
u32 precapture_frame_gate(u32 context_word_10, u32 mode, u32 enabled,
                         u32 debug_flags, u32 debug_selection) {
    if (context_word_10 != 0u)
        return 0u;
    return precapture_enable_gate(mode, enabled, debug_flags, debug_selection);
}
