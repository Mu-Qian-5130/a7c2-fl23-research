"""Execute the original CP pin-readiness predicate on synthetic state only.

No hardware, sound output, firmware mutation or service session. The original
predicate and its three original leaf getters run as Thumb instructions.
Requires unicorn; no mock success is substituted for a playback routine.
"""
import argparse
import json
from pathlib import Path
import struct
from inspect_native import PROFILE


def execute(cp, model, request_state, sound_mode):
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB
    from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_R0
    layout = PROFILE[model]
    cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    pages = set()

    def mapped(address, length):
        for page in range(address & ~4095, (address + length + 4095) & ~4095, 4096):
            if page not in pages:
                cpu.mem_map(page, 4096)
                pages.add(page)

    for key, length in [('cp_pin_predicate', 38), ('cp_get_request', 10),
                        ('cp_get_mode', 10), ('cp_read_mode', 4)]:
        va = layout[key]
        raw = cp[va - 0x108000:va - 0x108000 + length]
        if len(raw) != length:
            raise ValueError('Truncated native predicate/getter')
        mapped(va, length)
        cpu.mem_write(va, raw)
    for key in ['cp_request_state', 'cp_mode_state']:
        mapped(layout[key], 64)
    cpu.mem_write(layout['cp_request_state'] + 0x1c, struct.pack('<I', request_state))
    cpu.mem_write(layout['cp_mode_state'] + 10, bytes([sound_mode]))
    stack, stop = 0x40001000, 0x50000000
    mapped(stack - 4096, 4096)
    mapped(stop, 4096)
    cpu.reg_write(UC_ARM_REG_SP, stack)
    cpu.reg_write(UC_ARM_REG_LR, stop | 1)
    cpu.emu_start(layout['cp_pin_predicate'] | 1, stop, count=64)
    if cpu.reg_read(UC_ARM_REG_SP) != stack:
        raise ValueError('Native predicate did not restore its stack')
    return cpu.reg_read(UC_ARM_REG_R0)


def verify(cp, model):
    rows = []
    for state in range(5):
        for mode in range(6):
            actual = execute(cp, model, state, mode)
            expected = int(state == 2 and mode == 3)
            if actual != expected:
                raise ValueError('Original native readiness predicate differs from observed contract')
            rows.append({'request_state': state, 'sound_mode': mode, 'result': actual})
    return {'model': model, 'native_cases': rows,
            'original_getters_executed': True, 'synthetic_input_state': True,
            'playback_or_capture_simulated': False, 'camera_io': False,
            'meaning': 'Readiness predicate only; not electronic shutter activation or speaker proof'}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('cp', type=Path)
    p.add_argument('--model', choices=PROFILE, default='a7c2-2.01')
    p.add_argument('--output', type=Path)
    a = p.parse_args(argv)
    result = verify(a.cp.read_bytes(), a.model)
    text = json.dumps(result, indent=2)
    if a.output:
        with a.output.open('x', encoding='utf-8') as f:
            f.write(text + '\n')
    else:
        print(text)


if __name__ == '__main__':
    main()
