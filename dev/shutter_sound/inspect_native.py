"""Offline electronic-shutter sound research for ILCE-7CM2 2.01.

Inventory existing Sony resources and exact native paths. This entry does not
open USB, play sound, alter settings, or emit installable firmware patches.
"""
import argparse
import json
from pathlib import Path
import re
import struct


REFERENCE = {'repository': 'https://github.com/YuuLuo/a7c2-service-preload',
             'commit': '1619f938663a36d41e72302a8cfee89a0f6acd1a',
             'use': 'Service/preload boundary reference; no shutter-sound implementation supplied',
             'documentation_license': 'CC BY-SA 4.0'}
PROFILE = {
    'a7c2-2.01': {
        'ap_set_table': 0x3439620, 'ap_audio_run': 0x3439758,
        'ap_audio_request': 0x34ebcec,
        'cp_pin_predicate': 0x67f692,
        'cp_get_request': 0x67e1ce, 'cp_request_state': 0x10ef2d8,
        'cp_get_mode': 0x66679e, 'cp_read_mode': 0x6667ac,
        'cp_mode_state': 0x10d9bbc,
        'cp_send_sound': 0xb0a02e,
        'cp_capture_dispatch': 0xb19e5c,
        'cp_capture_start': 0x4a09f4, 'cp_capture_end': 0x4a0a74,
        'ap_signals_name': 0x4f24114, 'ap_menu_setting_name': 0x4f4adad,
        'ap_name_table': 0x582c248, 'ap_menu_name_table': 0x58381d8,
        'ap_lookup_cases': 0x4b8a940, 'ap_lookup_base': 0x2d99a94,
    },
    'a1ii-4.00': {
        'ap_set_table': 0x30fcb3c, 'ap_audio_run': 0x30fcc6c,
        'cp_pin_predicate': 0x6d17fc,
        'cp_get_request': 0x6d0366, 'cp_request_state': 0x11df764,
        'cp_get_mode': 0x6b868a, 'cp_read_mode': 0x6b8698,
        'cp_mode_state': 0x11c9e3c,
    },
}


def integer(text):
    if text == 'N/A':
        return None
    return int(text, 16 if text.lower().startswith('0x') or re.search('[a-fA-F]', text) else 10)


def beeplist(text):
    """Read the original comma-separated Sony sound registry, not a new format."""
    rows = []
    seen, base = {}, None
    for line in re.sub(r'/\*.*?\*/', '', text, flags=re.S).splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('/'):
            base = line
            continue
        fields = [x.strip() for x in line.split(',')]
        if len(fields) != 12:
            raise ValueError('Unexpected native beeplist row: ' + line[:60])
        label, number, memory, filename, size, offset, access, priority, kind, continuous, length, first = fields
        ident = integer(number)
        # A1 II lists unused RESERVE aliases before its real barcode sounds.
        # Retain these rows rather than treating the placeholder as an override.
        if ident in seen and seen[ident] != 'None' and filename != 'None':
            raise ValueError('Duplicate native beep identifier')
        if filename != 'None' or ident not in seen:
            seen[ident] = filename
        if memory not in ('PIN', 'APP') or access not in ('AA_RT', 'AA_FIFO'):
            raise ValueError('Unsupported native sound registry mode')
        rows.append({'label': label, 'beep_id': ident, 'memory': memory,
                     'file': filename, 'bytes': integer(size), 'offset': integer(offset),
                     'access': access, 'priority': integer(priority), 'kind': int(kind, 16),
                     'continuous': integer(continuous), 'length_text': length,
                     'first_length_text': first})
    if not base or not rows:
        raise ValueError('Missing native sound resource base/list')
    return base, rows


def inventory(directory):
    directory = Path(directory)
    base, rows = beeplist((directory / 'beeplist.txt').read_text(encoding='utf-8'))
    packed = (directory / 'SysSound.bin').read_bytes()
    selected = []
    for item in rows:
        name = item['file']
        if name == 'None' or item['bytes'] is None or item['offset'] is None:
            continue
        if Path(name).name != name or '\\' in name:
            raise ValueError('Resource name must be a single filename')
        raw = (directory / name).read_bytes()
        if len(raw) != item['bytes']:
            raise ValueError('Resource length differs: ' + name)
        at = item['offset']
        if at + len(raw) > len(packed) or packed[at:at + len(raw)] != raw:
            raise ValueError('Resource differs from native SysSound packing: ' + name)
        if item['memory'] == 'PIN':
            selected.append(item)
    return {'native_path': base, 'registered_count': len(rows),
            'packed_bytes': len(packed), 'pin_resources': selected,
            'resource_bytes_checked': True, 'audible_playback_tested': False}


def ap_property(raw, table_offset, string_offset):
    if struct.unpack_from('<Q', raw, table_offset)[0] != string_offset:
        raise ValueError('AP native property-name table differs')
    number, length = struct.unpack_from('<II', raw, table_offset - 8)
    if length != len(raw[string_offset:].split(b'\0', 1)[0]) + 1:
        raise ValueError('AP native property-name length differs')
    return 0x02cf0000 | number


def inspect(ap, cp, sounds, model='a7c2-2.01'):
    layout = PROFILE[model]
    ap, cp = Path(ap).read_bytes(), Path(cp).read_bytes()
    if ap[:4] != b'\x7fELF' or struct.unpack_from('<H', ap, 18)[0] != 183:
        raise ValueError('Expected native AArch64 AP ELF')
    predicate = layout['cp_pin_predicate'] - 0x108000
    if predicate < 0 or predicate + 38 > len(cp):
        raise ValueError('CP does not contain the selected predicate')
    result = {'model': model, 'reference': REFERENCE, 'camera_io': False,
              'status': 'OFFLINE_NATIVE_PATH_FOUND_NOT_ENABLED',
              'layout': {k: hex(v) for k, v in layout.items()},
              'resources': inventory(sounds),
              'cp_pin_predicate_bytes': cp[predicate:predicate + 38].hex(),
              'installable': False,
              'unresolved': ['Electronic-exposure sound suppression point is not yet established',
                             'Native pin route and physical speaker output are not yet tested',
                             'Single/burst timing, silent mode and movie regression are not yet tested']}
    if model == 'a7c2-2.01':
        result['settings'] = {
            'audio_signals': hex(ap_property(ap, layout['ap_name_table'], layout['ap_signals_name'])),
            'menu_beep_setting': hex(ap_property(ap, layout['ap_menu_name_table'], layout['ap_menu_setting_name']))}
        # Native switch maps enum 0/1/2/3 to four existing dispatch blocks.
        cases = struct.unpack_from('<4b', ap, layout['ap_lookup_cases'])
        result['native_setting_case_targets'] = [hex(layout['ap_lookup_base'] + n * 4) for n in cases]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ap', type=Path, required=True)
    parser.add_argument('--cp', type=Path, required=True)
    parser.add_argument('--sounds', type=Path, required=True)
    parser.add_argument('--model', choices=PROFILE, default='a7c2-2.01')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    result = inspect(args.ap, args.cp, args.sounds, args.model)
    text = json.dumps(result, indent=2)
    if args.output:
        with args.output.open('x', encoding='utf-8') as handle:
            handle.write(text + '\n')
    else:
        print(text)


if __name__ == '__main__':
    main()
