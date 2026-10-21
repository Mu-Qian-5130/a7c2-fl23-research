// Firmware-free A64 controls. RAM EEPROM exists only in the fixture profile.
.text
.global _start
_start:
    adr x0, vectors
    msr vbar_el3, x0
    isb
    mov x6, #0x0f000000
    ldr w7, [x6, #128] // mode: 0=EEPROM, 1=NACK, 2=gated fault, 3=reset-held fault
    ldr w8, [x6, #132] // port
    mov x9, #0x2000
    movk x9, #0xf101, lsl #16
    add x9, x9, x8, lsl #12
    mov x10, #0x8050
    movk x10, #0xf138, lsl #16
    mov x11, #0x8350
    movk x11, #0xf138, lsl #16
    mov w12, #0x40000
    lsl w12, w12, w8
    mov w13, #0x1000000
    lsl w13, w13, w8
    cmp w7, #2
    b.eq gated_read
    str w12, [x10, #4]
    cmp w7, #3
    b.eq gated_read
    str w13, [x11, #8]
    ldr w0, [x9, #0xf4]
    str w0, [x6, #8]
    ldr w0, [x9, #0xfc]
    str w0, [x6, #12]
    mov x14, #0x1000
    movk x14, #0xf13a, lsl #16
    mov x15, #0x2000
    movk x15, #0xf13a, lsl #16
    str wzr, [x14, #0xb4] // IRQ429..433 group0
    mov w0, #0x3e000
    str w0, [x14, #0x134]
    mov w0, #1
    add x1, x14, #0x900
    add x1, x1, #173
    strb w0, [x1, x8]
    str w0, [x14]
    str w0, [x15]
    mov w0, #255
    str w0, [x15, #4]
    str wzr, [x9, #0x6c]
    mov w0, #0x65 // master, standard speed, restart, slave disabled
    str w0, [x9]
    str wzr, [x9, #0x30]
    cmp w7, #1
    b.eq nack
    mov w0, #0x50
    str w0, [x9, #4]
    mov w0, #1
    str w0, [x9, #0x6c]
    mov w0, #0x20
    str w0, [x9, #0x10]
    mov w0, #0x37
    str w0, [x9, #0x10]
    mov w0, #0x2a9 // second byte + STOP
    str w0, [x9, #0x10]
    ldr w0, [x9, #0x34]
    str w0, [x6, #16]
    ldr w0, [x9, #0x30]
    str w0, [x6, #20]
    ldr w0, [x15, #12]
    str w0, [x6, #24] // masked => spurious
    mov w0, #0x200
    str w0, [x9, #0x30]
    ldr w0, [x15, #12]
    str w0, [x6, #28]
    ldr w1, [x9, #0x60]
    str w0, [x15, #16]
    ldr w0, [x15, #12]
    str w0, [x6, #32]
    str wzr, [x9, #0x6c]
    mov w0, #1
    str w0, [x9, #0x6c]
    mov w0, #0x20
    str w0, [x9, #0x10]
    mov w0, #0x500 // read + RESTART
    str w0, [x9, #0x10]
    mov w0, #0x300 // read + STOP
    str w0, [x9, #0x10]
    ldr w0, [x9, #0x78]
    str w0, [x6, #36]
    ldr w0, [x9, #0x10]
    str w0, [x6, #40]
    ldr w0, [x9, #0x10]
    str w0, [x6, #44]
    // Clock removal suppresses pending STOP IRQ, restoring clock re-forwards it.
    str w12, [x10, #8]
    ldr w0, [x15, #12]
    str w0, [x6, #48]
    str w12, [x10, #4]
    ldr w0, [x15, #12]
    str w0, [x6, #52]
    str wzr, [x9, #0x6c]
    mov w0, #1
    str w0, [x9, #0x6c]
    mov w0, #0x20
    str w0, [x9, #0x10]
    mov w0, #0x500 // leave one unread byte and an active bus transaction
    str w0, [x9, #0x10]
    ldr w0, [x9, #0x78]
    str w0, [x6, #76]
    str w13, [x11, #4] // hardware-model reset clears FIFO/enable/IRQ
    ldr w0, [x6, #52]
    str w0, [x15, #16]
    str w13, [x11, #8]
    ldr w0, [x9, #0x78]
    str w0, [x6, #56]
    ldr w0, [x9, #0x9c]
    str w0, [x6, #60]
    ldr w0, [x15, #12]
    str w0, [x6, #64]
    // A fresh transaction after reset sees the same external EEPROM bytes.
    str wzr, [x9, #0x30]
    mov w0, #0x65
    str w0, [x9]
    mov w0, #0x50
    str w0, [x9, #4]
    mov w0, #1
    str w0, [x9, #0x6c]
    mov w0, #0x20
    str w0, [x9, #0x10]
    mov w0, #0x700
    str w0, [x9, #0x10]
    ldr w0, [x9, #0x10]
    str w0, [x6, #72]
    b done
nack:
    mov w0, #0x51 // absent in both profiles
    str w0, [x9, #4]
    mov w0, #1
    str w0, [x9, #0x6c]
    mov w0, #0x255
    str w0, [x9, #0x10]
    ldr w0, [x9, #0x34]
    str w0, [x6, #16]
    ldr w0, [x9, #0x80]
    str w0, [x6, #20]
    ldr w0, [x15, #12]
    str w0, [x6, #24]
    mov w0, #0x40
    str w0, [x9, #0x30]
    ldr w0, [x15, #12]
    str w0, [x6, #28]
    ldr w1, [x9, #0x54]
    str w0, [x15, #16]
    ldr w0, [x9, #0x80]
    str w0, [x6, #32]
    ldr w0, [x15, #12]
    str w0, [x6, #36]
    ldr w0, [x9, #0x34]
    str w0, [x6, #68] // RAW abort clears even though upstream syndrome retains
    str w13, [x11, #4]
    str w13, [x11, #8]
    ldr w0, [x9, #0x80]
    str w0, [x6, #72] // reset clears the retained source
done:
    mov w0, #1
    str w0, [x6]
park:
    wfi
    b park
gated_read:
    ldr w0, [x9, #0xf4]
    mov w0, #0xbad
    str w0, [x6]
    b park
fault:
    mrs x0, esr_el3
    str x0, [x6, #80]
    mrs x0, far_el3
    str x0, [x6, #88]
    mov w0, #2
    str w0, [x6]
    b park
.balign 2048
vectors:
.rept 16
    b fault
    .space 124
.endr
