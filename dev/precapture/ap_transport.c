/* Offline AP marshalling prototype; no installer or host USB API.
 *
 * Target native sender file VA: 0x35358b8 (AArch64 appFw.so 2.01).
 * A runtime binding must account for the actual appFw load bias. A caller
 * supplies the function pointer; this source never guesses a load address.
 * Requests use the original AP leaf layout: context, setting, option.
 */
typedef unsigned int u32;
typedef unsigned long long u64;
typedef unsigned short u16;
typedef unsigned char u8;
typedef void (*ap_sender)(u32 route, const void *request, u64 request_size,
                          u16 reply_command, void *reply, u64 reply_size);

extern int encode_setting(const u32 *values, u8 *output, u32 capacity);
extern int encode_shooting(const u32 *values, u8 *output, u32 capacity);

int precapture_ap_setting(const u32 *request, u32 *result,
                          u32 domain, ap_sender sender) {
    u32 values[4];
    u8 packet[16];
    if (!request || !result || !sender)
        return -22;
    values[0] = request[1];
    values[1] = request[2];
    values[2] = domain; /* actual target domain dependency is still unbound */
    values[3] = request[0];
    if (encode_setting(values, packet, sizeof(packet)) != sizeof(packet)) {
        *result = 1;
        return -22;
    }
    sender(0x90030001u, packet, sizeof(packet), 0, (void *)0, 0);
    /* Matches the donor's no-reply setting marshaller. Zero here does not
     * prove that CP applied the setting or that a sensor acquired a frame.
     */
    *result = 0;
    return 0;
}

int precapture_ap_shooting(const u32 *request, u32 *result,
                           ap_sender sender) {
    u32 values[3];
    u8 packet[12];
    u32 reply[3] = {0, 0, 0};
    if (!request || !result || !sender)
        return -22;
    values[0] = request[1];
    values[1] = request[2];
    values[2] = request[0];
    if (encode_shooting(values, packet, sizeof(packet)) != sizeof(packet)) {
        *result = 1;
        return -22;
    }
    sender(0x90030001u, packet, sizeof(packet), 0x4173, reply, sizeof(reply));
    /* Donor checks the third reply word against 0xf000. Never replace
     * this with success inferred from enqueue or a CP handler returning1.
     */
    *result = reply[2] != 0xf000u;
    return 0;
}
