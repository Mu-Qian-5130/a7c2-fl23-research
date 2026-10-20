"""Offline A7C II/A7CR pixel-shift call-path audit; never opens the camera.

Input is privately extracted firmware. Output contains addresses/disassembly,
not program bytes, settings, calibration or an installable patch.
"""
import argparse
import io
import json
from pathlib import Path
import struct


SEQUENCE_TYPE = b'N5model38sequence_start_pixel_shift_multi_shootE\0'
DEBUG_STRINGS = [
    'void model::model_api::detail::set_remote_px_shift_multi_shoot_mode',
    'void model::model_api::detail::set_remote_px_shift_multi_shoot_number',
    'void model::model_api::detail::set_remote_px_shift_multi_shoot_interval',
    'void model::sequence_still_record::pixel_shift_multi_shoot_start_proc',
    'void model::sequence_still_record::pixel_shift_multi_shoot_capture_start_common_proc',
    'void model::sequence_still_record::pixel_shift_multi_shoot_end_proc',
]


class Image:
    def __init__(self, path):
        from elftools.elf.elffile import ELFFile
        from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
        self.data = Path(path).read_bytes()
        elf = ELFFile(io.BytesIO(self.data))
        if elf['e_machine'] != 'EM_AARCH64' or not elf.little_endian or elf.elfclass != 64:
            raise ValueError('Expected the AArch64 little-endian application ELF')
        self.segments = [dict(s.header) for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
        text = elf.get_section_by_name('.text')
        self.text = dict(text.header)
        self.md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)

    def offset(self, address, size=1):
        for segment in self.segments:
            delta = address - segment['p_vaddr']
            if 0 <= delta and delta + size <= segment['p_filesz']:
                return segment['p_offset'] + delta
        raise ValueError('Address outside file-backed mappings: ' + hex(address))

    def address(self, offset, size=1):
        for segment in self.segments:
            delta = offset - segment['p_offset']
            if 0 <= delta and delta + size <= segment['p_filesz']:
                return segment['p_vaddr'] + delta
        raise ValueError('Offset outside file-backed mappings: ' + hex(offset))

    def instructions(self, address, size):
        offset = self.offset(address, size)
        return list(self.md.disasm(self.data[offset:offset + size], address))

    def text_address(self, address):
        return self.text['sh_addr'] <= address < self.text['sh_addr'] + self.text['sh_size']

    def data_references(self, value):
        target = struct.pack('<Q', value)
        at, refs = 0, []
        while True:
            pos = self.data.find(target, at)
            if pos < 0:
                return refs
            at = pos + 1
            if pos % 8:
                continue
            try:
                address = self.address(pos, 8)
            except ValueError:
                continue
            if not self.text_address(address):
                refs.append(address)

    def qword(self, address):
        return struct.unpack_from('<Q', self.data, self.offset(address, 8))[0]

    def sequence(self):
        offset = self.data.find(SEQUENCE_TYPE)
        if offset < 0:
            raise ValueError('Pixel-shift sequence RTTI not found')
        name = self.address(offset)
        result = []
        for name_pointer in self.data_references(name):
            typeinfo = name_pointer - 8
            for reference in self.data_references(typeinfo):
                if self.qword(reference - 8) != 0:
                    continue
                functions = []
                for slot in range(16):
                    function = self.qword(reference + 8 + slot * 8)
                    if not self.text_address(function):
                        break
                    functions.append(function)
                if len(functions) < 3:
                    continue
                run = functions[2]
                end = min((f for f in functions if f > run), default=run + 1024)
                code = self.instructions(run, end - run)
                result.append({'typeinfo': hex(typeinfo), 'vtable': hex(reference - 8),
                               'virtual_methods': [hex(f) for f in functions],
                               'run': hex(run), 'run_end': hex(end),
                               'run_direct_calls': [{'site': hex(i.address), 'target': i.op_str}
                                                    for i in code if i.mnemonic == 'bl']})
        if len(result) != 1:
            raise ValueError('Pixel-shift RTTI did not resolve to one virtual table')
        return result[0]

    def debug_references(self):
        """Find actual ADRP/ADD materializations of specific debug strings.

        These establish code references to a name, not a verified function start.
        """
        import numpy as np
        start, size = self.text['sh_offset'], self.text['sh_size']
        words = np.frombuffer(self.data[start:start + size], dtype='<u4')
        idx = np.flatnonzero((words & 0x9f000000) == 0x90000000)
        w = words[idx].astype(np.int64)
        displacement = (((w >> 5) & 0x7ffff) << 2) | ((w >> 29) & 3)
        displacement = np.where(displacement & (1 << 20), displacement - (1 << 21), displacement)
        addresses = self.text['sh_addr'] + idx * 4
        pages = (addresses & ~4095) + (displacement << 12)
        results = []
        for text in DEBUG_STRINGS:
            pos = self.data.find(text.encode())
            if pos < 0:
                results.append({'name': text, 'found': False})
                continue
            target = self.address(pos)
            refs = []
            for i in idx[pages == (target & ~4095)]:
                register = int(words[i] & 31)
                for j in range(int(i) + 1, min(int(i) + 7, len(words))):
                    value = int(words[j])
                    if (value & 0xffc00000 == 0x91000000
                            and ((value >> 5) & 31) == register
                            and ((value >> 10) & 4095) == (target & 4095)):
                        refs.append(hex(self.text['sh_addr'] + int(i) * 4))
            results.append({'name': text, 'found': True, 'string_address': hex(target),
                            'code_references': refs})
        return results


def audit(directory):
    image = Image(Path(directory) / 'appFw.so')
    sequence = image.sequence()
    # Pinned 2.01 addresses resolved from the two original sequences. This is a
    # diagnostic profile, not admission of a firmware for writing.
    profiles = {
        0x348bcf0: {'model': 'ILCE-7CM2', 'wrapper': 0x34d1508,
                    'marshalling': 0x353a260, 'send': 0x35358b8, 'trace': 0x36825d0,
                    'selection': 0x34a19ec, 'configure_shot': 0x349fa84},
        0x348c1b8: {'model': 'ILCE-7CR', 'wrapper': 0x34d19f0,
                    'marshalling': 0x353a748, 'send': 0x3535da0, 'trace': 0x3682ab8,
                    'selection': 0x34a1ec4, 'configure_shot': 0x349ff5c},
    }
    profile = profiles.get(int(sequence['run'], 16))
    output = {'sequence': sequence, 'debug_string_references': image.debug_references()}
    if profile:
        wrapper = image.instructions(profile['wrapper'], 0x40)
        marshalling = image.instructions(profile['marshalling'], 0xb0)
        if not any(row['target'] == '#' + hex(profile['wrapper']) for row in sequence['run_direct_calls']):
            raise ValueError('Pixel-shift sequence no longer reaches documented wrapper')
        if not any(i.mnemonic == 'bl' and i.op_str == '#' + hex(profile['marshalling']) for i in wrapper):
            raise ValueError('Sequence wrapper no longer calls documented packet builder')
        if not any(i.mnemonic == 'mov' and i.op_str == 'w1, #0x4036' for i in marshalling):
            raise ValueError('Documented generic capture command differs')
        if not any(i.mnemonic == 'bl' and i.op_str == '#' + hex(profile['send']) for i in marshalling):
            raise ValueError('Documented packet send boundary differs')
        output.update(profile={k: hex(v) if isinstance(v, int) else v for k, v in profile.items()},
                      generic_capture_command='0x4036',
                      packet_builder=[{'address': hex(i.address), 'asm': i.mnemonic + ' ' + i.op_str}
                                      for i in marshalling],
                      generic_command_is_not_proof_of_pixel_shift=True)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True, help='Original C2 component directory')
    parser.add_argument('--reference', type=Path, required=True, help='Original A7CR component directory')
    parser.add_argument('--output', type=Path, required=True, help='New private JSON report')
    args = parser.parse_args(argv)
    result = {'schema': 'a7c2-pixelshift-audit/1', 'status': 'OFFLINE_RESEARCH_NOT_INSTALLABLE',
              'camera_io': False, 'firmware_modified': False,
              'target': audit(args.c2), 'reference': audit(args.reference),
              'unresolved': ['Model capability gate and downstream capture configuration',
                             'Physical IBIS positioning, settling and exposure synchronization',
                             'RAW grouping/shift metadata and verified compatible composition',
                             'Cancellation, return-to-center and ordinary photography regression']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, indent=2)
    print(json.dumps({'status': result['status'], 'target_run': result['target']['sequence']['run'],
                      'reference_run': result['reference']['sequence']['run'],
                      'camera_io': False, 'output': str(args.output)}, indent=2))


if __name__ == '__main__':
    main()
