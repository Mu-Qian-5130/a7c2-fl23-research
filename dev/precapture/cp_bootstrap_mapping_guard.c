/* Non-installable ARM32 placement primitive. Called only by a future checked
 * startup adapter after the extra page is known loaded and executable.
 * No constructor/state storage, boot readiness check or installation exists.
 * Unexpected arguments return without unmapping the currently executing page.
 */
typedef unsigned int u32;
typedef __UINTPTR_TYPE__ uptr;
_Static_assert(sizeof(void *) == 4, "Exact target CP ABI requires ARM32");

int precapture_target_low_unmap(const volatile u32 *manager, u32 address,
                              u32 bytes, u32 flags, int table) {
    int result;
    int (*original)(const volatile u32 *, u32, u32, u32, int) =
        (int (*)(const volatile u32 *, u32, u32, u32, int))(uptr)0x61a1f4u;
    if (!manager || ((uptr)manager & 3u) || address || bytes != 0x128000u || flags || table != -1)
        return -22;
    if (manager[0] != 0x1b88000u || manager[1] != 0x1b8c000u || manager[2] != 32u ||
        manager[0x20c / 4] != 0x1b88000u || manager[0x210 / 4] != 0x1b8c000u)
        return -95;
    result = original(manager, 0, 0x10a000u, 0, -1);
    if (result)
        return result;
    return original(manager, 0x10b000u, 0x128000u - 0x10b000u, 0, -1);
}
