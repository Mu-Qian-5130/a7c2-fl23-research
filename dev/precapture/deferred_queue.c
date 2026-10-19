/* Target-matched S1 deferred-message ring, not an OS task scheduler.
 *
 * Native target enqueue0xa17eae / pop0xa17f02 / peek0xa17f60.
 *20 entries,28 bytes each; one position stays empty (capacity19).
 * The original S1 owner must serialize every operation. No locks, OS
 * callbacks, message delivery or firmware-global storage are supplied.
 */
typedef unsigned int u32;
struct deferred_message {u32 word[7];};
struct deferred_ring {
    u32 prefix;
    struct deferred_message messages[20];
    u32 read_index, write_index;
};

int precapture_defer(struct deferred_ring *q, const struct deferred_message *message) {
    u32 next, i;
    if (!q || !message || q->read_index >= 20 || q->write_index >= 20)
        return -22;
    next = (q->write_index + 1u) % 20u;
    if (next == q->read_index)
        return -1;
    for (i = 0; i < 7; ++i)
        q->messages[q->write_index].word[i] = message->word[i];
    q->write_index = next;
    return 0;
}

/* Return1/0 is this prototype's explicit valid/empty indicator, not the
 * native pop function's unspecified return register. Output bytes and
 * index changes match the original, including its empty-message sentinel.
 */
int precapture_deferred_pop(struct deferred_message *out, struct deferred_ring *q) {
    u32 i;
    if (!q || !out || q->read_index >= 20 || q->write_index >= 20)
        return -22;
    if (q->read_index == q->write_index) {
        out->word[0] = 0xf00;
        out->word[1] = 0xffffffffu;
        for (i = 2; i < 7; ++i)
            out->word[i] = 0;
        return 0;
    }
    for (i = 0; i < 7; ++i)
        out->word[i] = q->messages[q->read_index].word[i];
    q->read_index = (q->read_index + 1u) % 20u;
    return 1;
}

const struct deferred_message *precapture_deferred_peek(const struct deferred_ring *q) {
    if (!q || q->read_index >= 20 || q->write_index >= 20 || q->read_index == q->write_index)
        return (const struct deferred_message *)0;
    return &q->messages[q->read_index];
}
