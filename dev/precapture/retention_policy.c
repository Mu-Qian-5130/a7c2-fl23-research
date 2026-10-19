/* Offline-only reconstruction of A7C II queue policy. No frame allocation,
 * capture, scheduler, firmware hook, or device access is provided here.
 */
typedef unsigned int u32;

/* Values correspond to actual reads in the original target pruning routine:
 * policy, limit, reference timestamp, oldest-frame timestamp, frame count.
 * All arithmetic intentionally follows the target's unsigned 32-bit behavior.
 */
int queue_should_trim(const u32 *v) {
    if(!v||!v[4])return 0;
    if(v[0]==1)return v[4]>v[1];
    if(v[0]==0)return v[3]<(u32)(v[2]-v[1]*2000u);
    return 0;
}

/* Decision at the original post-trigger flush boundary. v contains policy,
 * limit, trigger-reference timestamp, frame timestamp, frame marker.
 * Return1=discard,0=record path; this does not itself record or release a frame.
 */
int queue_should_discard(const u32 *v) {
    if(!v)return 1;
    if(v[4]!=0xffffffffu)return 0;
    if(v[0]==1)return 0;
    if(v[0]==0)return v[3]<(u32)(v[2]-v[1]*2000u);
    return 1;
}

/* A proposed adapter for a caller-owned, EMPTY and IDLE target-layout object.
 * No actual camera instance address or call site has been bound.
 * q+0xc=count; q+0x14=policy; q+0x18=limit; q+0x1c=state.
 */
int queue_configure(u32 *q,u32 duration_ms) {
    if(!q||duration_ms<5||duration_ms>1000)return -22;
    if(q[3]||q[7])return -16;
    q[5]=0;q[6]=duration_ms;return 0;
}

/* Reproduce target callback0xa09e10: latch a reference sequence once,
 * update its timestamp, and preserve every unrelated object field.
 * This is NOT a physical shutter event provider.
 */
void queue_latch_reference(u32 *q,u32 sequence,u32 timestamp) {
    unsigned char *bytes=(unsigned char*)q;
    if(!q)return;
    q[8]=timestamp;
    if(!bytes[0x2c]) {q[9]=sequence;bytes[0x2c]=1;}
}
