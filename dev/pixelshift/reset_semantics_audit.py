"""Distinguish Sony program-exposure shift reset from sensor Pixel Shift.

Follows original RTTI/vtable/method calls to the AP packet sender on both
private application ELFs. Static only: does not issue any reset or camera I/O.
"""
import argparse
import json
from pathlib import Path
import re
import struct

from audit import Image


TYPE = b'N5model32sequence_set_program_shift_resetE\0'
DRIVE_TYPE = b'N5model32sequence_set_program_shift_driveE\0'


def trace_sequence(image, type_name, label_name, expected_command, candidates):
    name = image.address(image.data.index(type_name))
    tables = []
    for name_pointer in image.data_references(name):
        for reference in image.data_references(name_pointer - 8):
            if image.qword(reference - 8) != 0:
                continue
            methods = [image.qword(reference + 8 + n * 8) for n in range(5)]
            if all(image.text_address(value) for value in methods):
                tables.append((reference + 8, methods))
    if len(tables) != 1:
        raise ValueError('Expected one source-defined program-shift-reset vtable')
    table, methods = tables[0]

    def instructions(address):
        result = []
        for ins in image.instructions(address, 0x100):
            result.append(ins)
            if ins.mnemonic == 'ret' or ins.mnemonic == 'b':
                break
        return result

    def calls(address):
        return [int(ins.op_str.lstrip('#'), 0) for ins in instructions(address) if ins.mnemonic == 'bl']

    sequence_calls = calls(methods[2])
    if len(sequence_calls) != 1:
        raise ValueError('Program reset sequence no longer has its single wrapper call')
    wrapper = sequence_calls[0]
    wrapper_calls = calls(wrapper)
    if len(wrapper_calls) != 2:
        raise ValueError('Expected diagnostic-begin and packet-sender wrapper calls')
    sender = wrapper_calls[1]
    code = instructions(sender)
    command = next((int(ins.op_str.split('#')[1], 0) for ins in code
                    if ins.mnemonic == 'mov' and ins.op_str.startswith('w0, #0x40')), None)
    if command != expected_command:
        raise ValueError('Program-reset sequence emitted a different command')
    if not any(ins.mnemonic == 'strh' and ins.op_str.startswith('w0, ') for ins in code):
        raise ValueError('Missing native command-field store')
    # These are distinct C2/CR registration locations, checked against source
    # instructions and the exact label address rather than assumed identical.
    label = image.address(image.data.index(label_name.encode() + b'\0'))
    matches = []
    for candidate in candidates:
        block = image.instructions(candidate, 24)
        if len(block) != 6:
            continue
        if (block[0].mnemonic == 'adrp' and block[0].op_str == f'x2, #{hex(label & ~4095)}'
                and block[2].mnemonic == 'add' and block[2].op_str == f'x2, x2, #{hex(label & 4095)}'
                and block[4].mnemonic == 'mov' and block[4].op_str == f'w1, #{hex(expected_command)}'):
            matches.append(candidate)
    if len(matches) != 1:
        raise ValueError('Program-reset command/label registration was not resolved')
    return dict(rtti=type_name.rstrip(b'\0').decode(), vtable=hex(table), sequence_method=hex(methods[2]),
                wrapper=hex(wrapper), sender=hex(sender), command=hex(command),
                registration=hex(matches[0]), label=label_name, label_address=hex(label),
                meaning='program exposure shift', sensor_pixel_shift_reset=False,
                camera_io=False, instructions_executed=False)


def audit(directory):
    image = Image(Path(directory) / 'appFw.so')
    reset = trace_sequence(image, TYPE, 'PID_SET_P_SHIFT_RESET', 0x4043, (0x17129a4, 0x1712a84))
    drive = trace_sequence(image, DRIVE_TYPE, 'PID_SET_P_SHIFT_DRIVE', 0x401b, (0x17125e4, 0x17126c4))
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data = (Path(directory) / 'cpapp-b.bin').read_bytes()

    def cp_entry(command):
        rows = []
        for match in re.finditer(re.escape(struct.pack('<I', command)), data):
            at = match.start()
            if at % 4 or at + 20 > len(data):
                continue
            row = struct.unpack_from('<5I', data, at)
            if row[1] & 1 and 0x108000 < row[1] < 0x108000 + len(data):
                rows.append((at + 0x108000, row))
        if len(rows) != 1:
            raise ValueError('CP command descriptor is not unique')
        return rows[0]

    drive_record, d = cp_entry(0x401b)
    reset_record, r = cp_entry(0x4043)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def cp_code(entry, size):
        start = entry & ~1
        return list(md.disasm(data[start-0x108000:start-0x108000+size], start))

    if not any(ins.mnemonic == 'strb.w' and ins.op_str == 'r0, [r1, #0x2bb]'
               for ins in cp_code(d[1], 0x62)):
        raise ValueError('Program shift drive handler no longer writes the inspected byte')
    if not any(ins.mnemonic == 'strb.w' and ins.op_str == 'r1, [r0, #0x2bd]'
               for ins in cp_code(r[1], 0x10)):
        raise ValueError('Program shift reset handler no longer sets the adjacent reset flag')
    if not any(ins.mnemonic == 'ldrb.w' and ins.op_str == 'r1, [r5, #0x2bb]'
               for ins in cp_code(d[4], 0x50)):
        raise ValueError('Program shift descriptor no longer refers to the actual drive-field checker')
    checker = d[4] & ~1
    if b'CheckSetPShiftDrive\0' not in data[checker-0x108000:checker-0x108000+0xb0]:
        raise ValueError('The descriptor checker is not named CheckSetPShiftDrive')
    reset.update(drive=drive, cp=dict(drive_record=hex(drive_record), drive_handler=hex(d[1] & ~1),
                 drive_checker=hex(checker), drive_field='sc_PShiftDrive',
                 reset_record=hex(reset_record), reset_handler=hex(r[1] & ~1),
                 field_is_program_exposure_shift=True, sensor_position_units_identified=False))
    return reset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = dict(target=audit(args.c2), reference=audit(args.reference), camera_io=False)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps(report))


if __name__ == '__main__':
    main()
