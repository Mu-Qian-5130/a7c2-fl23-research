.text
.global _start
_start:
    mrs x9, mpidr_el1
    ands x9, x9, #0xff
    b.ne secondary_fixture
    mov x0, #0x0d000000
    mov sp, x0
    adr x0, vectors
    msr vbar_el3, x0
    isb
    bl install_fixture_mmu
    msr ttbr0_el3, x0
    mov x0, #0xff04
    msr mair_el3, x0
    mov x0, #0x3519
    movk x0, #0x8082, lsl #16
    msr tcr_el3, x0
    dsb sy
    tlbi alle3
    dsb sy
    isb
    mrs x0, sctlr_el3
    orr x0, x0, #1
    bic x0, x0, #2
    bic x0, x0, #4
    bic x0, x0, #0x1000
    msr sctlr_el3, x0
    isb
    bl vm_main
1:  wfi
    b 1b
fault:
    mrs x9, mpidr_el1
    and x9, x9, #0xff
    mov x6, #0x0f000000
    cbz x9, record_fault
    add x6, x6, #0x1000
    add x6, x6, x9, lsl #7
record_fault:
    mrs x0, esr_el3
    str x0, [x6, #104]
    mrs x0, far_el3
    str x0, [x6, #112]
    mov x0, #0xbad
    str x0, [x6]
2:  wfi
    b 2b
/* Secondary actors wait for the fixture's publication, then use the
 * unchanged NOR ERET path and CP108000 primary/secondary selector. They
 * never run primary setup or modify native SMP phase/owner words.
 */
secondary_fixture:
    mov x0, #0x0d000000
    add x0, x0, x9, lsl #16
    mov sp, x0
    adr x0, vectors
    msr vbar_el3, x0
    isb
    mov x6, #0x0f000000
wait_fixture:
    ldr x0, [x6]
    cmp x0, #1
    b.ne wait_fixture
    dmb sy
    ldr x1, [x6, #72]
    ubfx x1, x1, #3, #1
    mov x0, #0x8000
    movk x0, #0x10, lsl #16
    mov x16, #0x3e20
    movk x16, #0xfe05, lsl #16
    br x16
.balign 2048
vectors:
.rept 16
    b fault
    .space 124
.endr
