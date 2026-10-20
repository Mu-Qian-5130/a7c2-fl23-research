"""Offline custom-sound feasibility tools, not a camera installer.

native: replace a same-size, already encoded native BIN in copies of the sound
bank/resources and keep a compressed inverse. No audio codec is inferred.
pcm: extract PCM16 from a WAV and prepare a native LPCM registration template.
The camera sample rate, buffer lifetime/routing and playback remain unverified.
"""
import argparse
import base64
import json
from pathlib import Path
import struct
import wave
import zlib

from inspect_native import beeplist, inventory


def registration(kind, address, length, *, enabled=True, audio_format=1,
                 access=0, continuous=0, loop_length=0, first_length=0):
    """AP 2.01's 40-byte 200d/0329 message, not a live transport frame."""
    if not 1 <= kind <= 255 or not 0 <= address < 2**64 or not 0 <= length < 2**32:
        raise ValueError('Registration field outside the original ABI width')
    if audio_format not in (0, 1) or access not in (0, 1):
        raise ValueError('Use the original ADPCM/LPCM and RT/FIFO values')
    if continuous not in (0, 1) or not all(0 <= x < 2**32 for x in (loop_length, first_length)):
        raise ValueError('Invalid native loop parameters')
    data = bytearray(40)
    struct.pack_into('<4H', data, 0, 0x200d, 0x329, 40, 0x8001)
    data[20] = kind
    if enabled:
        struct.pack_into('<QI', data, 8, address, length)
        data[21:25] = bytes((access, 1, audio_format, continuous))
        struct.pack_into('<II', data, 28, loop_length, first_length)
    return bytes(data)


def selected(directory, label):
    _, rows = beeplist((Path(directory) / 'beeplist.txt').read_text(encoding='utf-8'))
    matches = [r for r in rows if r['label'] == label]
    if len(matches) != 1:
        raise ValueError('Choose one existing native beep label')
    item = matches[0]
    if item['memory'] != 'PIN' or item['file'] == 'None' or item['bytes'] is None:
        raise ValueError('Choose an existing PIN sound with a concrete allocation')
    if label not in ('BEEP_ID_KA', 'BEEP_ID_SHA', 'BEEP_ID_KASHA') and 'SHUTTER' not in label:
        raise ValueError('This experiment selects single-shot shutter resources only')
    if item['continuous']:
        raise ValueError('Continuous/looped audio requires a separate timing investigation')
    return item, rows


def reconstruct(files, inverse):
    """Exact edited-byte guards; preserve later changes outside these regions."""
    restored = dict(files)
    for entry in inverse['edits']:
        name, offset = entry['file'], entry['offset']
        before = zlib.decompress(base64.b64decode(entry['before_zlib']))
        after = zlib.decompress(base64.b64decode(entry['after_zlib']))
        current = bytearray(restored[name])
        if len(current) != entry['file_bytes'] or current[offset:offset + len(after)] != after:
            raise ValueError('Selected sound bytes changed since the candidate was made')
        current[offset:offset + len(after)] = before
        restored[name] = bytes(current)
    return restored


def native_candidate(directory, label, replacement):
    directory = Path(directory)
    inventory(directory)
    item, rows = selected(directory, label)
    replacement = bytes(replacement)
    if len(replacement) != item['bytes']:
        raise ValueError('Native BIN must fit the exact existing allocation; no implicit truncation')
    # Changing an individual file also affects every registered use of that file.
    uses = [item]
    while True:
        names = {r['file'] for r in uses}
        windows = {(r['offset'], r['bytes']) for r in uses}
        found = list(uses)
        for at, length in windows:
            if length != len(replacement):
                raise ValueError('Shared native filename has incompatible allocation sizes')
            for other in rows:
                if other['bytes'] is None or other['offset'] is None:
                    continue
                start, size = other['offset'], other['bytes']
                overlap = max(at, start) < min(at + length, start + size)
                if overlap and (start, size) != (at, length):
                    raise ValueError('Overlapping partial sound allocation cannot be changed alone')
                if (overlap or other['file'] in names) and other not in found:
                    found.append(other)
        if len(found) == len(uses):
            break
        uses = found
    names = {r['file'] for r in uses}
    before = {'SysSound.bin': (directory / 'SysSound.bin').read_bytes()}
    before.update({n: (directory / n).read_bytes() for n in names})
    after = dict(before)
    bank = bytearray(after['SysSound.bin'])
    edits = []

    def edit(name, offset, original, changed):
        edits.append({'file': name, 'offset': offset, 'file_bytes': len(before[name]),
                      'before_zlib': base64.b64encode(zlib.compress(original, 9)).decode(),
                      'after_zlib': base64.b64encode(zlib.compress(changed, 9)).decode()})

    for at, size in sorted(windows):
        edit('SysSound.bin', at, bytes(bank[at:at + size]), replacement)
        bank[at:at + size] = replacement
    after['SysSound.bin'] = bytes(bank)
    for name in sorted(names):
        edit(name, 0, before[name], replacement)
        after[name] = replacement
    inverse = {'schema': 'a7c2-sound-byte-inverse/1', 'edits': edits}
    if reconstruct(after, inverse) != before:
        raise ValueError('Native sound inverse did not reproduce the original input')
    touched = set()
    for at, size in windows:
        touched.update(range(at, at + size))
    if any(a != b and n not in touched for n, (a, b) in enumerate(zip(before['SysSound.bin'], bank))):
        raise ValueError('Sound bank changed outside the selected allocations')
    report = {'status': 'OFFLINE_NATIVE_RESOURCE_CANDIDATE', 'camera_io': False,
              'native_codec_input_assumed_not_decoded': True, 'playback_verified': False,
              'affected_labels': [r['label'] for r in uses],
              'allocation_bytes': item['bytes'], 'kind': item['kind'],
              'bank_bytes': len(bank), 'registry_changed': False,
              'untargeted_bank_bytes_preserved': True, 'inverse_byte_equal': True,
              'limitations': ['No WAV encoding or proof that this BIN decodes as intended',
                              'Boot source/bank residency and capture trigger remain unresolved',
                              'Do not write this output to a camera or raw partition']}
    return after, inverse, report


def pcm_candidate(wav_path, kind):
    with wave.open(str(wav_path), 'rb') as wav:
        if wav.getcomptype() != 'NONE' or wav.getsampwidth() != 2 or wav.getnchannels() != 1:
            raise ValueError('Prototype accepts an uncompressed mono PCM16 WAV')
        rate, frames = wav.getframerate(), wav.getnframes()
        pcm = wav.readframes(frames)
    if not frames or len(pcm) != frames * 2:
        raise ValueError('Empty or truncated WAV')
    # Alignment is a construction choice for the candidate, not proof of DMA
    # suitability. Original declared resources and bank offsets use 64-byte units.
    padded = pcm + bytes((-len(pcm)) % 64)
    report = {'status': 'OFFLINE_LPCM_REGISTRATION_TEMPLATE',
              'camera_io': False, 'kind': kind, 'format': 'LPCM',
              'source_wav_rate_hz': rate, 'source_frames': frames,
              'source_duration_ms': 1000 * frames / rate,
              'pcm_bytes': len(pcm), 'buffer_bytes': len(padded),
              'native_rate_and_pcm_layout_verified': False,
              'address_is_synthetic': True, 'playback_verified': False,
              'limitations': ['Template address is not a real camera allocation',
                              'Native sample rate, PCM layout and output path need confirmation',
                              'LPCM must not replace ADPCM bytes without changing registration format',
                              'Pinned buffer lifetime and release/restore are not implemented']}
    request = registration(kind, 0x10000000, len(padded), audio_format=1)
    return padded, request, report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    native = sub.add_parser('native')
    native.add_argument('--sounds', type=Path, required=True)
    native.add_argument('--label', required=True)
    native.add_argument('--bin', type=Path, required=True)
    native.add_argument('--output', type=Path, required=True)
    pcm = sub.add_parser('pcm')
    pcm.add_argument('--wav', type=Path, required=True)
    pcm.add_argument('--kind', type=int, required=True)
    pcm.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv)
    if a.output.exists():
        p.error('Choose a new private output directory')
    if a.command == 'native':
        files, inverse, report = native_candidate(a.sounds, a.label, a.bin.read_bytes())
        files['inverse.private.json'] = json.dumps(inverse, indent=2).encode()
    else:
        data, request, report = pcm_candidate(a.wav, a.kind)
        files = {'custom.pcm': data, 'registration-template.private.bin': request}
    a.output.mkdir(parents=True)
    for name, data in files.items():
        (a.output / name).write_bytes(data)
    (a.output / 'report.private.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
