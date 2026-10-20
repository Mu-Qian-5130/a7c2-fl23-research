/* Private, disposable VM fixture, never a camera program or loader patch.
 * Native backup reader, GPIO helper, mode writer and EL3->A32 handoff run
 * unchanged. Preinitialized BK4/log controller state and memory aliases
 * are explicit laboratory inputs; full cold-boot initialization is omitted.
 */
typedef unsigned long u64;
typedef unsigned int u32;
typedef unsigned char u8;
#define BASE 0xfe049000ul
static volatile u64 *const result=(volatile u64 *)0x0f000000;
static const volatile u64 *const input=(const volatile u64 *)0x0f000100;
static u8 context[0x300];
static void fail(u64 n) {result[14]=n;result[0]=0xdead;for(;;)__asm__ volatile("wfi");}
void vm_main(void) {
    int (*initialize)(u64)=(void *)(BASE+0x4564);
    int (*read)(u32,void *)=(void *)(BASE+0x36dc);
    int (*gpio)(void)=(void *)(BASE+0xaba8);
    int (*mode)(void *)=(void *)(BASE+0x97b0);
    void (*enter)(u64,u64)=(void *)(BASE+0xae20);
    u64 destination=0;u32 port=0,bit=0,selector=0,secondary=0;
    result[0]=0;result[1]=1;
    if(initialize(input[0]))fail(1);
    if(read(0xfa0173,&destination)!=8)fail(2);
    if(read(0xf909d5,&port)!=4||read(0xf909d6,&bit)!=4)fail(3);
    if(read(0x51005c,&selector)!=4||read(0x510050,&secondary)!=(int)input[4])fail(4);
    if(destination!=(input[1]<<32)+0x3e42000||port!=18||bit!=input[3]||selector!=2)fail(5);
    result[2]=destination;result[3]=port;result[4]=bit;result[5]=selector;result[6]=secondary;
    /* Explicit preinitialized fixture state selects the original BK4 API.
     * This word is a loader reader mode, NOT CP EXEC_MODE or readiness.
     */
    *(volatile u32 *)0xfe26c300=1;
    int sampled=gpio();
    if(sampled<0||sampled>1||sampled!=(int)input[2])fail(6);
    result[7]=sampled;result[1]=2;
    /* The context composition matches the separately audited original
     * f6b8 producer. The full monolithic context-init caller is not run.
     */
    context[0x1f5]=1;context[0x238]=(u8)sampled|4;
    int status=mode(context);
    result[8]=(u32)status;result[9]=context[0x238];
    result[10]=*(volatile u32 *)destination;
    result[11]=*(volatile u32 *)(destination+4);
    result[12]=*(volatile u32 *)0x03e42000;
    if(status||result[10]!=((u32)sampled<<8)||result[12]!=result[10]||result[11]!=secondary)fail(7);
    result[1]=3;result[0]=1;
    enter(0x108000,(context[0x238]>>3)&1);
    fail(8);
}
