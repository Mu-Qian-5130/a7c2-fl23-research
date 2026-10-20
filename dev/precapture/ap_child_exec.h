/* Offline child-only execution component. No fork, loader/init, camera,
 * device, UIPC, CP or result-file entrypoint is supplied. The caller must
 * already be the isolated child, with a byte-verified pinned executable FD.
 * The static selftest executable needs no interpreter or inherited FDs.
 */
#ifndef PRECAPTURE_AP_CHILD_EXEC_H
#define PRECAPTURE_AP_CHILD_EXEC_H

typedef unsigned int child_u32;
typedef unsigned long child_u64;
typedef long child_i64;
typedef child_i64 (*child_syscall)(child_i64,child_i64,child_i64,child_i64,
                                   child_i64,child_i64,child_i64);

enum child_exec_step {
    CHILD_OPEN_DIRECTORY=1, CHILD_READ_DIRECTORY, CHILD_VALIDATE_DIRECTORY,
    CHILD_CLOSE_DESCRIPTOR, CHILD_CLOSE_DIRECTORY, CHILD_EXECVEAT, CHILD_EXECVE_FALLBACK
};

struct child_exec_result {
    child_u32 magic,version,step,consumed;
    child_u32 nonce,closed_fds,directory_reads,exec_attempts;
    child_i64 directory_descriptor,directory_close_status,failed_descriptor;
    child_i64 enumeration_status,execveat_status,execve_status,return_status;
};

struct child_exec_workspace { unsigned char directory[4096]; };

/* Consumes a zeroed result once. Must never run in the parent/AP service.
 * Returns only on failure. Successful exec replaces the process image.
 * Caller-owned workspace must be disjoint from the result. This avoids a
 * new4KiB allocation on the AP thread's inherited stack before exec.
 * The supplied path is argv[0] only; execution uses the SAME pinned FD.
 * Only ENOSYS permits one /proc/self/fd/N execve fallback; never EINVAL.
 * A bounded number of calls does not bound native syscall wall time.
 */
child_i64 precapture_child_exec_once(child_i64 executable_fd,child_u32 nonce,
    const char *image_name,volatile struct child_exec_result *,struct child_exec_workspace *,child_syscall);

#endif
