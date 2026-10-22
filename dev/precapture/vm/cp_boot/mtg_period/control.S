// CP is reference data only; the A64 control never executes its code.
.text
.global _start
_start:
    adr x0, vectors
    msr vbar_el3, x0
    isb
    mov x6, #0x0f000000
    ldr w7, [x6, #128]
    mov x9, #0x1010
    movk x9, #0xf541, lsl #16
    cmp w7, #1
    b.eq read_first
    cmp w7, #2
    b.eq wrong_width
    cmp w7, #3
    b.eq outside_words
    cmp w7, #4
    b.eq change_source_before_first_write
    cmp w7, #5
    b.eq late_changed_source
    cmp w7, #6
    b.eq other_word_undefined
    cmp w7, #7
    b.eq change_label_before_first_write
    mov w0, #0x7e47
    movk w0, #0x1b, lsl #16
    str w0, [x9]
    ldr w1, [x9]
    cmp w0, w1
    b.ne failed
    mov w2, #0x5dd9
    movk w2, #0x22, lsl #16
    str w2, [x9, #4]
    ldr w1, [x9, #4]
    cmp w1, w2
    b.ne failed
    mov w3, #-1
    str w3, [x9, #8]
    ldr w1, [x9, #8]
    cmp w1, w3
    b.ne failed
    ldr w1, [x9]
    cmp w0, w1
    b.ne failed
    str wzr, [x9]
    ldr w0, [x9]
    cbnz w0, failed
    ldr w0, [x9, #4]
    cmp w0, w2
    b.ne failed
    ldr w0, [x9, #8]
    cmp w0, w3
    b.ne failed
    mov w0, #3
    str w0, [x6, #8]
    mov w0, #1
    str w0, [x6]
    b park
read_first:
    ldr w0, [x9]
    b failed
wrong_width:
    strb wzr, [x9]
    b failed
outside_words:
    ldr w0, [x9, #12]
    b failed
changed_source:
    str wzr, [x9]
    b failed
change_source_before_first_write:
    mov x10, #0xb674
    movk x10, #0xb9, lsl #16
    b mutate_reference
change_label_before_first_write:
    mov x10, #0x2a34
    movk x10, #0xfe, lsl #16
mutate_reference:
    ldr w0, [x10]
    str w0, [x6, #20]
    eor w0, w0, #1
    str w0, [x10]
    dsb sy
    ldr w0, [x10]
    str w0, [x6, #24]
    b changed_source
other_word_undefined:
    mov w0, #1
    str w0, [x9]
    ldr w0, [x9]
    cmp w0, #1
    b.ne failed
    ldr w0, [x9, #4]
    b failed
late_changed_source:
    mov w0, #1
    str w0, [x9]
    mov x10, #0xb674
    movk x10, #0xb9, lsl #16
    ldr w0, [x10]
    str w0, [x6, #20]
    eor w0, w0, #1
    str w0, [x10] // change reference data, never executed CP code
    dsb sy
    ldr w0, [x10]
    str w0, [x6, #24]
    ldr w0, [x9]
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
