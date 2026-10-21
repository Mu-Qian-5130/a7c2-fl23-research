// Firmware-free synthetic PLL request controls. Fixture LOCK is not hardware.
.text
.global _start
_start:
    adr x0, vectors
    msr vbar_el3, x0
    isb
    mov x6, #0x0f000000
    ldr w7, [x6, #128]
    ldr w8, [x6, #132]
    mov x10, #0x8100
    movk x10, #0xf138, lsl #16
    add x9, x10, x8, lsl #2
    mov x11, #0x8200
    movk x11, #0xf138, lsl #16
    cmp w7, #3
    b.eq reserved_write
    cmp w7, #5
    b.eq hole_read
    cmp w7, #6
    b.eq divider_reserved
    cmp w7, #7
    b.eq selector_unknown
    cmp w7, #9
    b.eq logic_unknown
    ldr w0, [x9]
    str w0, [x6, #8]
    mov w1, #0x2300
    movk w1, #1, lsl #16
    add w1, w1, w8
    orr w0, w1, #0x1000000
    str w0, [x9]
    ldr w0, [x9]
    str w0, [x6, #12]
    tbnz w0, #24, failed
    orr w2, w1, #0x18000000
    cmp w7, #8
    b.ne start
    orr w2, w1, #0x08000000
start:
    str w2, [x9]
    cmp w7, #4
    b.eq active_replacement
    cmp w7, #2
    b.ne choose_wait
    orr w0, w2, #0x1000000
    str w0, [x9]
choose_wait:
    cbnz w7, absent
    mov w3, #0
poll:
    ldr w0, [x9]
    tbnz w0, #24, completed
    add w3, w3, #1
    cmp w3, #0x100000
    b.lo poll
    b failed
completed:
    str w0, [x6, #16]
    str w1, [x9] // explicit model stop removes START/GATE and LOCK
    ldr w0, [x9]
    str w0, [x6, #20]
    mov w0, #0xfd13
    str w0, [x11, #4]
    mov w0, #0xfd03
    str w0, [x11, #8]
    ldr w0, [x11]
    str w0, [x6, #24]
    ldr w0, [x11, #4]
    str w0, [x6, #28]
    mov x12, #0x8070
    movk x12, #0xf138, lsl #16
    mov w0, #0x400000
    str w0, [x12, #4]
    ldr w0, [x12]
    str w0, [x6, #32]
    mov w0, #0x400000
    str w0, [x12, #8]
    ldr w0, [x12]
    str w0, [x6, #36]
    mov w0, #1
    str w0, [x6]
    b park
absent:
    mov w3, #64
absent_poll:
    ldr w0, [x9]
    tbnz w0, #24, failed
    tbz w0, #27, failed
    subs w3, w3, #1
    b.ne absent_poll
    str w0, [x6, #16]
    mov w0, #2
    str w0, [x6]
    b park
active_replacement:
    eor w0, w2, #0x100
    str w0, [x9]
    b failed
reserved_write:
    mov w0, #0x80000000
    str w0, [x9]
    b failed
hole_read:
    ldr w0, [x10, #0x14]
    b failed
divider_reserved:
    mov w0, #1
    str w0, [x10, #0x50]
    b failed
selector_unknown:
    mov w0, #4
    str w0, [x11, #4]
    b failed
logic_unknown:
    mov x12, #0x8070
    movk x12, #0xf138, lsl #16
    mov w0, #0x200
    str w0, [x12, #4]
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
