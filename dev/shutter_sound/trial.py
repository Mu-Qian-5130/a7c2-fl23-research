"""Experimental electronic-shutter trial: explicit preflight/apply/restore.

Importing this file and status/help are offline. No camera I/O is performed
unless a physical command is explicitly invoked. Keep every job private.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import zipfile

import candidate


def save(root, state):
    path = root / 'job.private.json'
    temp = path.with_suffix('.pending')
    temp.write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')
    os.replace(temp, path)


def backup(root, copy, values):
    path = root / 'before.private.zip'
    with zipfile.ZipFile(path, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name, raw in values.items():
            z.writestr(name, raw)
    copy = Path(copy).resolve()
    if copy == root or root in copy.parents:
        raise ValueError('Put the second backup outside the working job')
    copy.mkdir(parents=True, exist_ok=True)
    target = copy / 'shutter-before.private.zip'
    with path.open('rb') as src, target.open('xb') as dst:
        shutil.copyfileobj(src, dst)
        dst.flush()
        os.fsync(dst.fileno())
    with zipfile.ZipFile(path) as z, zipfile.ZipFile(target) as zz:
        if z.namelist() != zz.namelist() or any(z.read(n) != values[n] or zz.read(n) != values[n] for n in values):
            raise ValueError('Backup reconstruction differs')
    return str(target)


def factory(expected=None):
    from looktool import devicesession
    class SoundCamera(devicesession.Camera):
        def _connect(self):
            transport, self.core = devicesession.modules()
            self.link = transport.Session(self.expected)
            self.link.__enter__()
            self.identity = self.link.identity
            self.service_only = False
            return self
        def temp_read(self, name, missing=False):
            if name in ('shutter.staged.so', 'shutter.probe.result'):
                return self.link.read('/tmp/jiritsu/' + name, missing)
            return super().temp_read(name, missing)
        def temp_write(self, name, data):
            if name == 'shutter.staged.so':
                if not self.programs_pinned or not data or len(data) > 65536:
                    raise ValueError('Invalid sound preflight staging')
                self.link.select('/tmp/jiritsu/' + name)
                return self.link.jiritsu(16, b'\0\xff\0' + data)
            return super().temp_write(name, data)
        def temp_remove(self, name):
            if name in ('shutter.staged.so', 'shutter.probe.result'):
                self.link.select('/tmp/jiritsu/' + name)
                return self.link.jiritsu(18, b'\0\xff')
            return super().temp_remove(name)
    return SoundCamera(expected)


def run_native(camera, root, state, blob, kind, mode=0, plan=None):
    from looktool import devicesession, checkpointworker
    def record(event, **fields):
        state.setdefault('journal', []).append({'event': event, **fields})
        save(root, state)
    if kind == 'probe':
        stage, request, result, contents = 'shutter.staged.so', None, 'shutter.probe.result', None
        decode = candidate.parse_probe
        extras = ('a7c2.probe.result',)
    elif kind == 'program':
        stage, request, result = 'lut-program-staged.so', 'a7c2.install.request', 'a7c2.install.result'
        contents = struct.pack('<8sII', b'A7INS001', mode, 0)
        decode = lambda raw: checkpointworker.program_report(raw, mode, plan)
        extras = ()
    else:
        stage, request, result = 'lut-runtime-staged.so', 'a7c2.wbi.request', 'a7c2.wbi.result'
        contents = struct.pack('<8sII', b'A7WBI001', mode, 0)
        decode = lambda raw: camera.core.parse_native('wbi', raw, mode)
        extras = ()  # The worker includes fresh drop-log evidence in its report.
    evidence = root / 'evidence'
    evidence.mkdir(exist_ok=True)
    return devicesession.invoke(camera, Path(blob).read_bytes(), stage=stage,
        request=request, result=result, contents=contents, mode=mode, decode=decode,
        record=record, save_raw=lambda raw: (evidence / (kind + '-' + str(len(state['journal'])) + '.bin')).write_bytes(raw), extras=extras)


def capture(camera):
    return {'appFw.so': camera.read('/usr/lib/appFw.so'),
            'cpapp-b.bin': camera.read('/cp/cpapp-b.bin'),
            'settings-ram.bin': camera.snapshot(True),
            'settings-saved.bin': camera.snapshot(False)}


def preflight(root, copy, zig=None, camera_factory=factory):
    root.mkdir(parents=True, exist_ok=False)
    state = {'schema': 'a7c2-shutter-job/1', 'phase': 'preparing', 'firmware': '2.01',
             'camera_firmware_written': False, 'physical_sound_verified': False, 'journal': []}
    save(root, state)
    try:
        with camera_factory() as camera:
            values = capture(camera)
            candidate.guard(values['appFw.so'], values['cpapp-b.bin'])
            state['identity'] = camera.identity
            state['backup_copy'] = backup(root, copy, values)
            plan, _ = candidate.build(values['appFw.so'], values['cpapp-b.bin'], root / 'build', zig)
            camera.programs_pinned = True
            probe = run_native(camera, root, state, root / 'build/probe.so', 'probe')
            state['probe'] = probe
            candidate.require_registry(probe)
            native = plan['native_program']
            run_native(camera, root, state, native['path'], 'program', 0, native)
            state['phase'] = 'ready'
            state['camera_firmware_written'] = False
            save(root, state)
    except BaseException:
        state['phase'] = 'needs_review'
        save(root, state)
        raise
    return state


def change(root, *, restore=False, zig=None, camera_factory=factory):
    state = json.loads((root / 'job.private.json').read_text(encoding='utf-8'))
    allowed = ('written', 'reload_pending', 'restored') if restore else ('ready',)
    if state['phase'] not in allowed or (restore and state['phase'] == 'restored'):
        raise ValueError('Job is not at a known writable stage; inspect its evidence first')
    copy = Path(state['backup_copy'])
    with zipfile.ZipFile(root / 'before.private.zip') as a, zipfile.ZipFile(copy) as b:
        for name in a.namelist():
            if a.read(name) != b.read(name):
                raise ValueError('The two original backups differ')
    state['phase'] = 'restoring' if restore else 'applying'
    save(root, state)
    try:
        with camera_factory(state['identity']) as camera:
            fresh = capture(camera)
            plan, target = candidate.build(fresh['appFw.so'], fresh['cpapp-b.bin'],
                root / ('restore-build' if restore else 'apply-build'), zig, restore=restore)
            camera.programs_pinned = True
            probe = run_native(camera, root, state, root / 'build/probe.so', 'probe')
            candidate.require_registry(probe)
            if not restore and probe['audio_signals'] != 0:
                raise ValueError('For the first sound trial select Audio Signals On, then make a new preflight job')
            native = plan['native_program']
            run_native(camera, root, state, native['path'], 'program', 0, native)
            run_native(camera, root, state, native['path'], 'program', 1, native)
            state['program_transaction_verified'] = True
            state['camera_firmware_written'] = True
            save(root, state)
            for name, path in (('appFw.so', '/usr/lib/appFw.so'), ('cpapp-b.bin', '/cp/cpapp-b.bin')):
                if camera.read(path) != target[name]:
                    raise ValueError('Complete program readback differs: ' + name)
            from looktool import devicesettings
            for key, memory in (('settings-ram.bin', True), ('settings-saved.bin', False)):
                devicesettings.compare(camera.records(fresh[key]), camera.records(camera.snapshot(memory)), {}, camera.core)
            state['complete_readback_and_settings_verified'] = True
            state['phase'] = 'reload_pending'
            save(root, state)
            if probe['image_mode'] == '2':
                run_native(camera, root, state, root / 'build/wbi.so', 'wbi', 1)
            state['phase'] = 'restored' if restore else 'written'
            state['physical_sound_verified'] = False
            save(root, state)
    except BaseException:
        # Retain evidence; never automatically replay, roll back or power-cycle.
        state['phase'] = 'needs_review'
        save(root, state)
        raise
    return state


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    for name in ('preflight', 'apply', 'restore', 'status'):
        s = sub.add_parser(name)
        s.add_argument('--job', required=True, type=Path)
        if name != 'status':
            s.add_argument('--zig')
        if name == 'preflight':
            s.add_argument('--firmware', required=True, choices=['2.01'])
            s.add_argument('--backup-copy', required=True, type=Path)
    a = p.parse_args()
    root = a.job.resolve()
    if a.command == 'preflight':
        state = preflight(root, a.backup_copy, a.zig)
    elif a.command == 'status':
        state = json.loads((root / 'job.private.json').read_text(encoding='utf-8'))
    else:
        state = change(root, restore=a.command == 'restore', zig=a.zig)
    print(json.dumps({k: state.get(k) for k in ('phase', 'camera_firmware_written', 'physical_sound_verified')}, indent=2))
    if a.command in ('apply', 'restore'):
        print('USB I/O ended. Disconnect all external power, shut down normally, wait for the access light, then remove the battery for at least one minute. Physical validation is still required.')


if __name__ == '__main__':
    main()
