"""Execute stock AP/CP fragments linking an electronic request to selector 1.

The capture inputs are synthetic. This is not a complete camera simulation:
the ordinary capture policy inputs to 351a48 are supplied explicitly, and the
asynchronous propagation between the executed fragments is not simulated.
"""
import argparse
import json
from pathlib import Path
import struct


def ap_request(ap, still, interval, interval_type):
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_SP, UC_ARM64_REG_LR
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    for va, size in ((0x352bde4, 0x1d4), (0x1797fb4, 24), (0x370d8f0, 104)):
        cpu.mem_map(va & ~4095, 4096)
        cpu.mem_write(va, ap[va:va + size])
    cpu.mem_map(0x5bc3000, 4096)
    cpu.mem_write(0x5bc35b0, struct.pack('<I', 16))
    cpu.mem_map(0x10000000, 0x10000)
    cpu.mem_map(0x20000000, 0x4000)
    cpu.mem_map(0x50000000, 4096)
    for reg, val in ((UC_ARM64_REG_X0, still), (UC_ARM64_REG_X1, interval),
                     (UC_ARM64_REG_X2, interval_type), (UC_ARM64_REG_X3, 0x10000000),
                     (UC_ARM64_REG_SP, 0x20003000), (UC_ARM64_REG_LR, 0x50000000)):
        cpu.reg_write(reg, val)
    reached = []
    def end(uc, va, size, user):
        if va == 0x50000000:
            reached.append(True)
            uc.emu_stop()
    cpu.hook_add(UC_HOOK_CODE, end)
    cpu.emu_start(0x352bde4, 0x50000004, count=128)
    if not reached:
        raise ValueError('AP conversion did not return')
    return cpu.mem_read(0x10000008, 1)[0]


def cp_selector(cp, request, *, front_policy=0, front_subpolicy=0, special=0):
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R8, UC_ARM_REG_R11, UC_ARM_REG_SP, UC_ARM_REG_LR
    cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    pages = set()
    def put(va, data):
        for page in range(va & ~4095, (va + len(data) + 4095) & ~4095, 4096):
            if page not in pages:
                cpu.mem_map(page, 4096)
                pages.add(page)
        cpu.mem_write(va, data)
    for va, size in ((0x358ac4, 48), (0x328998, 12), (0x351a48, 0x10a)):
        put(va, cp[va - 0x108000:va - 0x108000 + size])
    for va, size in ((0x10000000, 4096), (0x20000000, 0x4000),
                     (0x30000000, 0x2000), (0x50000000, 4096),
                     (0x165a000, 0x2000), (0x1a53000, 4096), (0x1ad4000, 4096)):
        put(va, bytes(size))
    put(0x10000008, bytes([request]))
    stop = [0x50000000]
    reached = []
    def end(uc, va, size, user):
        if va == stop[0]:
            reached.append(va)
            uc.emu_stop()
    cpu.hook_add(UC_HOOK_CODE, end)
    cpu.reg_write(UC_ARM_REG_R0, 0x10000000)
    cpu.reg_write(UC_ARM_REG_SP, 0x20003000)
    cpu.reg_write(UC_ARM_REG_LR, 0x50000001)
    cpu.emu_start(0x358ac5, 0x50000002, count=128)
    if not reached or struct.unpack('<I', cpu.mem_read(0x165aaa0, 4))[0] != request:
        raise ValueError('CP native silent-shutter setter differs')
    # Original snapshot copy: native master+380 -> EC snapshot+4c8.
    put(0x10000000, struct.pack('<I', 0x165a720))
    cpu.reg_write(UC_ARM_REG_R8, 0x10000000)
    cpu.reg_write(UC_ARM_REG_R11, 0x30000000)
    stop[0] = 0x3289a4
    reached.clear()
    cpu.emu_start(0x328999, 0x3289a6, count=16)
    electronic = struct.unpack('<I', cpu.mem_read(0x300004c8, 4))[0]
    if electronic != request or not reached:
        raise ValueError('CP snapshot copy differs')
    # Execute the original ordinary after-shutter selector, no debug override.
    # 8b7f4e passes the snapshot electronic flag as r2; descriptor query as r3.
    for reg, val in ((UC_ARM_REG_R0, front_policy), (UC_ARM_REG_R1, front_subpolicy),
                     (UC_ARM_REG_R2, electronic), (UC_ARM_REG_R3, 1),
                     (UC_ARM_REG_SP, 0x20003000), (UC_ARM_REG_LR, 0x50000001)):
        cpu.reg_write(reg, val)
    put(0x20003000, struct.pack('<3I', 0, 0, special))
    stop[0] = 0x50000000
    reached.clear()
    cpu.emu_start(0x351a49, 0x50000002, count=128)
    if not reached:
        raise ValueError('CP ordinary selector did not return')
    return cpu.reg_read(UC_ARM_REG_R0)


def verify(ap, cp):
    rows = []
    for still in (0, 1):
        for interval in (0, 1):
            for interval_type in (0, 1):
                byte = ap_request(ap, still, interval, interval_type)
                expected = interval_type if interval else still
                if byte != expected or cp_selector(cp, byte) != expected:
                    raise ValueError('Native AP-to-CP fragment chain differs')
                rows.append(dict(still=still, interval=interval, interval_type=interval_type,
                                 request=byte, ordinary_selector=expected))
    for electronic in (0, 1):
        if cp_selector(cp, electronic, special=1) != 4:
            raise ValueError('Special path changed')
        for front in (0, 1):
            if cp_selector(cp, electronic, front_policy=1, front_subpolicy=front) != 2 + front:
                raise ValueError('Front-policy precedence changed')
    policy = [ap_registration_policy(ap, setting) for setting in range(4)]
    if [x[8] for x in policy] != [1, 1, 0, 0]:
        raise ValueError('Original shutter registration off policy differs')
    if [[x[i] for i in range(6)] for x in policy] != [[v] * 6 for v in (1, 0, 1, 1)]:
        raise ValueError('Original sound group Off policy differs')
    return {'native_chain_cases': len(rows), 'precedence_cases': 6,
            'native_audio_policy_cases': 4, 'audio_policy_index_8': [x[8] for x in policy],
            'audio_policy_indices_0_to_5': [[x[i] for i in range(6)] for x in policy],
            'registration_calls_observed_without_execution': True,
            'original_model_feature_leaf_executed': True, 'model_index': 16,
            'ordinary_electronic_request_selects_1': True,
            'asynchronous_propagation_simulated': False,
            'silent_mode_and_speaker_tested': False, 'camera_io': False, 'cases': rows}


def ap_registration_policy(ap, setting):
    """Observe stock run() call arguments after its separate global request.

    set_adf_table is an observation boundary: it is not executed and its return
    value is not consumed by this native caller. No registration success is
    invented. The actual model-index lookup leaf is executed unchanged.
    """
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X19, UC_ARM64_REG_LR, UC_ARM64_REG_PC
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    for va, n in ((0x3439000, 4096), (0x1797d44, 24), (0x370ce60, 104)):
        cpu.mem_map(va & ~4095, 4096)
        cpu.mem_write(va, ap[va:va + n])
    cpu.mem_map(0x5bc3000, 4096)
    cpu.mem_write(0x5bc35b0, struct.pack('<I', 16))
    cpu.mem_map(0x10000000, 0x2000)
    cpu.mem_write(0x10000014, struct.pack('<I', setting))
    cpu.reg_write(UC_ARM64_REG_X19, 0x10000000)
    result = {}
    def boundary(uc, va, size, user):
        if va == 0x3439620:
            result[uc.reg_read(UC_ARM64_REG_X1)] = uc.reg_read(UC_ARM64_REG_X2)
            uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))
        elif va == 0x3439850:
            uc.emu_stop()
    cpu.hook_add(UC_HOOK_CODE, boundary)
    cpu.emu_start(0x343987c, 0x3439a0c, count=256)
    if set(result) != set(range(9)):
        raise ValueError('Incomplete native registration-policy trace')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ap', required=True, type=Path)
    p.add_argument('--cp', required=True, type=Path)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    result = verify(a.ap.read_bytes(), a.cp.read_bytes())
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, indent=2)
        f.write('\n')


if __name__ == '__main__':
    main()
