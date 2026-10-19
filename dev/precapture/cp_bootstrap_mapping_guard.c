/* Non-installable ARM32 placement primitive. Called only by a future checked
 * startup adapter after the extra page is known loaded and executable.
 * No constructor/state storage, boot readiness check or installation exists.
 * Unexpected arguments return without unmapping the currently executing page.
 */
typedef unsigned int u32;
typedef __UINTPTR_TYPE__ uptr;
_Static_assert(sizeof(void *) == 4, "Exact target CP ABI requires ARM32");
#ifndef PRECAPTURE_CODE_PAGES
#define PRECAPTURE_CODE_PAGES 1
#endif
#ifndef PRECAPTURE_KEEP_LOOK_PREFIX
#define PRECAPTURE_KEEP_LOOK_PREFIX 0
#endif
_Static_assert(PRECAPTURE_CODE_PAGES == 1 || PRECAPTURE_CODE_PAGES == 2, "Bounded code span");
_Static_assert(PRECAPTURE_KEEP_LOOK_PREFIX == 0 || PRECAPTURE_KEEP_LOOK_PREFIX == 1, "Pinned source look layout");

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
    /* Preserve all code pages, not merely the entrypoint's page. The known
     * six-look source also owns110000..112000 as data: retain its existing
     * descriptors without granting execute permission or touching contents.
     */
    const u32 end = 0x10a000u + PRECAPTURE_CODE_PAGES * 4096u;
#if PRECAPTURE_KEEP_LOOK_PREFIX
    result = original(manager, end, 0x110000u - end, 0, -1);
    if (result)
        return result;
    return original(manager, 0x112000u, 0x128000u - 0x112000u, 0, -1);
#else
    return original(manager, end, 0x128000u - end, 0, -1);
#endif
}
