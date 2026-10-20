.text
.global _start
_start:
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
    mov x6, #0x0f000000
    mrs x0, esr_el3
    str x0, [x6, #104]
    mrs x0, far_el3
    str x0, [x6, #112]
    mov x0, #0xbad
    str x0, [x6]
2:  wfi
    b 2b
.balign 2048
vectors:
.rept 16
    b fault
    .space 124
.endr
