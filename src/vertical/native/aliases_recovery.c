/* Disable/recovery only: inspect an already writable mount, or report fully
 * synced removal with EBUSY separately. Never permits adding aliases on RW. */
#define VERTICAL_RECOVERY 1
#include "aliases.c"
