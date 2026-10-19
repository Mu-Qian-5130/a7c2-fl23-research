#ifndef PRECAPTURE_CP_CONTROL_STATE_H
#define PRECAPTURE_CP_CONTROL_STATE_H
typedef unsigned int u32;
typedef unsigned char u8;
#ifndef PRECAPTURE_RELEASE_OBSERVER
#define PRECAPTURE_RELEASE_OBSERVER 0
#endif
enum precapture_stage {
    PRECAPTURE_IDLE = 0, PRECAPTURE_PREPARE = 1, PRECAPTURE_COMMITTED = 2,
    PRECAPTURE_FAULT = 3, PRECAPTURE_WAIT_IDLE = 4,
    PRECAPTURE_WAIT_OWNER = 5, PRECAPTURE_OWNER_READY = 6,
    PRECAPTURE_WAIT_RELEASE_OWNER = 7
};
struct precapture_control {
    u32 enabled, trigger, duration_ms, stage;
    u32 pending_enabled, pending_command, pending_context, pending_origin;
};
_Static_assert(sizeof(struct precapture_control) == 32, "CP control layout");
int precapture_cp_setting(struct precapture_control *, const u8 *, u32);
int precapture_cp_begin(struct precapture_control *, const u8 *, u32, u32);
int precapture_cp_apply_if_idle(struct precapture_control *, const volatile u32 *);
#endif
