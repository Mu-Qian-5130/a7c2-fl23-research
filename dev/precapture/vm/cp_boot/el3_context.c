/* Explicit EL3 laboratory translation context. Not recovered cold-boot tables.
 * Packed BK4 fields need Normal-memory semantics; default MMU-off EL3 accesses
 * otherwise fault as Device memory. Preserve device attributes on peripherals.
 */
typedef unsigned long u64;
u64 install_fixture_mmu(void) {
    volatile u64 *root=(volatile u64 *)0x0c000000;
    volatile u64 *peripherals=(volatile u64 *)0x0c001000;
    const u64 normal=1ul|(1ul<<10)|(3ul<<8)|(1ul<<2);
    const u64 device=1ul|(1ul<<10)|(1ul<<53)|(1ul<<54);
    for(unsigned i=0;i<512;i++) {
        root[i]=0;
        peripherals[i]=(0xc0000000ul+((u64)i<<21))|device;
    }
    root[0]=normal;
    root[16]=0x400000000ul|normal;
    root[32]=0x800000000ul|normal;
    root[3]=0x0c001000ul|3;
    peripherals[(0xfe000000ul-0xc0000000ul)>>21]=0xfe000000ul|normal;
    peripherals[(0xfe200000ul-0xc0000000ul)>>21]=0xfe200000ul|normal;
    return 0x0c000000;
}
