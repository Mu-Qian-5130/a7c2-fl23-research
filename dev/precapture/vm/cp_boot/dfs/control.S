// Firmware-free protocol controls. Completion actor is never native hardware.
.text
.global _start
_start:
    adr x0, vectors
    msr vbar_el3, x0
    isb
    mov x6, #0x0f000000
    ldr w7, [x6, #128]
    mov x9, #0x8f48
    movk x9, #0xf138, lsl #16
    cmp w7, #2
    b.eq invalid_control
    mov w0, #0x101
    str w0, [x9, #4]
    cmp w7, #7
    b.eq undefined_read
    cmp w7, #6
    b.eq init_only
    str w0, [x9]
    cmp w7, #3
    b.eq invalid_command
    str wzr, [x9, #4]
    mov w0, #0x104
    str w0, [x9, #12]
    mov w0, #1
    str w0, [x9, #8]
    cmp w7, #4
    b.eq duplicate_start
    cmp w7, #5
    b.eq busy_command
    cmp w7, #1
    b.eq absent
    mov w8, #0
poll:
    ldr w0, [x9]
    mov w1, #0x101
    and w0, w0, w1
    cmp w0, #1
    b.eq complete
    add w8, w8, #1
    cmp w8, #0x100000
    b.lo poll
    b failed
complete:
    str w0, [x6, #8]
    ldr w0, [x9, #16]
    str w0, [x6, #12]
    mov w0, #0x101
    str w0, [x9, #4]
    ldr w0, [x9]
    str w0, [x6, #16]
    mov w0, #0x101
    str w0, [x9]
    ldr w0, [x9]
    str w0, [x6, #20]
    ldr w0, [x9, #16]
    str w0, [x6, #24]
    mov w0, #1
    str w0, [x6]
    b park
absent:
    mov w8, #64
absent_poll:
    ldr w0, [x9]
    cbnz w0, failed
    ldr w0, [x9, #16]
    tbz w0, #8, failed
    subs w8, w8, #1
    b.ne absent_poll
    str w0, [x6, #12]
    ldr w0, [x9]
    str w0, [x6, #8]
    mov w0, #2
    str w0, [x6]
    b park
init_only:
    ldr w0, [x9]
    str w0, [x6, #8]
    ldr w0, [x9, #16]
    str w0, [x6, #12]
    mov w0, #1
    str w0, [x6]
    b park
invalid_control:
    mov w0, #2
    str w0, [x9, #4]
    b failed
invalid_command:
    mov w0, #0x107
    str w0, [x9, #12]
    b failed
duplicate_start:
    str w0, [x9, #8]
    b failed
busy_command:
    str wzr, [x9, #12]
    b failed
undefined_read:
    ldr w0, [x9, #4]
failed:
    mov w0, #0xbad
    str w0, [x6]
park:
    wfi
    b park
fault:
    mrs x0, esr_el3
    str x0, [x6, #80]
    mrs x0, far_el3
    str x0, [x6, #88]
    mov w0, #3
    str w0, [x6]
    b park
.balign 2048
vectors:
.rept 16
    b fault
    .space 124
.endr
