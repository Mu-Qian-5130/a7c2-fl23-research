/* Native target Timeshift dequeue metadata and route decisions only.
 *
 * Does not remove queue nodes, free RAW IDs, allocate, save images or send
 * continuation callbacks. Those operations remain native-owner duties.
 */
typedef unsigned int u32;
typedef unsigned char u8;
static u32 word(const u8 *p) {
    return (u32)p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24;
}
static void store(u8 *p, u32 value) {
    p[0] = value; p[1] = value >> 8; p[2] = value >> 16; p[3] = value >> 24;
}

/* Original target0x372486..0x3724ac and0x3724c2..0x3724ca.
 * Caller must hold native ownership and provide a valid reference state.
 */
int precapture_dequeue_metadata(u8 *queue, u8 *frame, u32 discard) {
    if (!queue || !frame || discard > 1)
        return -22;
    if (discard) {
        frame[0x6710] = 0;
        return 0;
    }
    if (!queue[0x2d]) {
        store(queue + 0x28, word(frame + 0x208));
        queue[0x2d] = 1;
    }
    frame[0x6710] = 1;
    store(frame + 0x6718, word(queue + 0x28));
    store(frame + 0x6714, word(queue + 0x24));
    return 1;
}

/* Original0x37e046..0x37e072 calls actual error leaf0xa11b90.
 * Only its class1 (low3 bits set) overrides the retention route. Error
 * class2 is not equivalent to class1: preserve this native distinction.
 * This helper is deliberately restricted to Timeshift marker2 frames.
 */
int precapture_timeshift_route(const u8 *frame) {
    if (!frame || word(frame + 0x66e8) != 2)
        return -22;
    if (word(frame + 0x617c) & 7u)
        return 7;
    if (!frame[0x6710])
        return 6;
    return word(frame + 0x6718) == word(frame + 0x208) ? 4 : 5;
}
