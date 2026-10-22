"""Explicit continuation of a reported factory name ENOSPC, never programs.

The failed transaction is read-only evidence. A new transaction owns any new
work. Only an accounted-for native result permits removal of its exact /tmp
files; arbitrary outstanding operations are not replayed or cleaned.
"""
import json
from pathlib import Path
import re
import struct
from . import checkpoint, nameworker


def source(folder):
    root = Path(folder).resolve()
    state = json.loads((root / 'direct.private.json').read_text(encoding='utf-8'))
    if (state.get('mode') != 'factory_reset' or state.get('phase') != 'NEEDS_REVIEW'
            or not state.get('inverse_name_build') or state.get('forward_name_build')):
        raise ValueError('Only a reported factory name-space failure can use this continuation')
    journal = state['journal']
    if not journal or journal[-1].get('event') != 'native_intent' or journal[-1].get('result') != 'checkpoint.names.result' or journal[-1].get('mode') != 2:
        raise ValueError('Unaccounted operation: preserve the failed transaction')
    reports = []
    for path in (root / 'evidence').glob('*-names-2.bin'):
        raw = path.read_bytes()
        if len(raw) == nameworker.REPORT.size:
            v = nameworker.REPORT.unpack(raw)
            if (v[:3] == (b'A7NMR001', 1, 2) and v[3] in (2, 3, 6)
                    and v[4] == state['inverse_name_build']['count'] and v[5] == -28
                    and 0 < v[4] <= 68 and all(0 <= v[i] <= v[4] for i in range(12, 17))
                    and not any(v[i] for i in (6, 7, 8, 9, 10, 13, 14, 17)) and v[11] > 0):
                reports.append(raw)
    if len(reports) != 1:
        raise ValueError('One completed, cleaned-up ENOSPC name report is required')
    written = [r['result']['windows'] for r in journal if r.get('event') == 'native_result_verified'
               and r.get('stage') == 'checkpoint.staged.so' and r.get('mode') == 1
               and 'windows' in r.get('result', {})]
    if written != [b['windows'] for b in state['program_builds']]:
        raise ValueError('Program batches did not all report completion; no continuation')
    return root, state, reports[0]


def program_bytes(current, root, state):
    # Check the recorded target windows directly, with no firmware hash gate.
    for build in state['program_builds']:
        path = Path(build['path'])
        if path.parent.resolve() != (root / 'worker').resolve():
            raise ValueError('Program evidence is outside the failed transaction')
        header = path.with_suffix('.private.h').read_text(encoding='ascii')
        arrays = {int(i): bytes(map(int, values.split(','))) for i, values in
                  re.findall(r'static const u8 new_(\d+)\[\]=\{([\d,]+)\};', header)}
        rows = re.findall(r'\{(\d+)UL,(\d+),([01]),old_(\d+),new_(\d+)\}', header)
        if len(rows) != build['windows']:
            raise ValueError('Incomplete program window evidence')
        for at, size, chip, old, new in rows:
            data = arrays[int(new)]
            image = current['cpapp-b.bin' if chip == '1' else 'appFw.so']
            if old != new or len(data) != int(size) or image[int(at):int(at) + int(size)] != data:
                raise ValueError('Previously restored program bytes differ; no program replay')


def cleanup(camera, root, state, raw, record):
    blob = Path(state['inverse_name_build']['path']).read_bytes()
    expected = {'checkpoint.staged.so': blob,
                'checkpoint.names.request': struct.pack('<8sII', b'A7NAM001', 2, 0),
                'checkpoint.names.result': raw}
    if camera.temp_read('libJit.so', True) is not None:
        raise ValueError('A native plugin still exists; preserve it for inspection')
    # Inspect the entire namespace before removing anything. Missing exact
    # files are fine after a restart; unexpected bytes are never removed.
    for name in ('checkpoint.program.request', 'checkpoint.program.result'):
        if camera.temp_read(name, True) is not None:
            raise ValueError('Unexpected previous program state: ' + name)
    for name, data in expected.items():
        value = camera.temp_read(name, True)
        if value is not None and value != data:
            raise ValueError('Preserve unexpected temporary contents: ' + name)
    record('failed_name_report_accounted', failed_workspace=str(root), status=-28,
           restored=nameworker.REPORT.unpack(raw)[15])
    for name in reversed(expected):
        if camera.temp_read(name, True) is not None:
            camera.temp_remove(name)
        if camera.temp_read(name, True) is not None:
            raise ValueError('Temporary cleanup incomplete: ' + name)
    record('failed_name_temporary_cleanup_verified')
