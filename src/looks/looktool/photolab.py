"""Explicit experimental photo-stage trials, fresh backups and exact undo.

Importing this module never connects USB. The lab changes CP program bytes
only; AP, names, recipes and factory units are preserved. Unknown native
outcomes stop. It does not install arbitrary dense photo-stage look files.
"""
import importlib.util
import json
from pathlib import Path
import struct
import uuid
from datetime import datetime
from . import checkpoint, checkpointworker, device_layout, devicesettings, photobuild, photocases, photoformat
from .checkpointjob import Rollback, CheckpointCamera
from .devicelock import serialized
from .backupstore import write_json


class PhotoTrial(Rollback):
    def raw(self, name, raw):
        super().raw(name, raw)
        if name == 'runtime-0.bin' and len(raw) == 1832:
            self.state['last_runtime_boot_id'] = raw[1768:1832].split(b'\0')[0].decode('ascii').strip()
            write_json(self.state_path, self.state)


def decode_records(raw):
    path = Path(__file__).resolve().parents[2] / 'fl23/core.py'
    spec = importlib.util.spec_from_file_location('photo_lab_core', path)
    core = importlib.util.module_from_spec(spec);spec.loader.exec_module(core)
    return core.backup_records(raw)


class Lab:
    def __init__(self, root, owner_context, *, factory=CheckpointCamera, records=decode_records,
                 zig=None, looks=None):
        self.root = Path(root).resolve()
        self.state_file = self.root / 'lab.private.json'
        self.owner = json.loads(Path(owner_context).read_text(encoding='utf-8-sig'))
        if self.owner.get('schema') != 'a7c2-photo-lab-owner/1' or self.owner.get('version') != '2.01':
            raise ValueError('Experimental lab requires the prepared owner/version context')
        self.factory, self.records, self.zig = factory, records, zig
        self.looks = Path(looks).resolve() if looks else None

    def save(self, phase, **values):
        if phase=='AWAITING_RELOAD' and self.state.get('phase')!='AWAITING_RELOAD':
            values.setdefault('raw_profile_effective_since',datetime.now().isoformat(timespec='microseconds'))
        self.state.update(values, phase=phase)
        write_json(self.state_file, self.state)
        print('Native photo lab:', phase, flush=True)

    def load(self):
        self.state = json.loads(self.state_file.read_text(encoding='utf-8'))
        if self.state.get('schema') != 'a7c2-photo-lab/1':raise ValueError('Unknown lab workspace')
        checkpoint.same_body(self.owner['identity'], self.state['identity'])
        return self.state

    def original(self):
        _, source = checkpoint.read(self.root / 'before-lab.private.zip')
        _, mirror = checkpoint.read(Path(self.state['backup_copy']) / 'before-lab.private.zip')
        if source != mirror:raise ValueError('Independent pre-lab backup copy differs')
        return source

    def baseline(self, source):
        records = self.records(source['settings-ram.bin'])
        return photoformat.extract_bank(source['cpapp-b.bin'], records[1][0x02a40001].data,
            records[1][0x02a4000d].data, gamma_table_va=0x1209480,
            regular_row=0, still_row=10, color_parameter=0)[0]

    def target(self, source, case, documents=None):
        if case is None or case == 'restore':return dict(source), {'case': 'restore'}
        programs, description = photocases.make_target(
            {n: source[n] for n in checkpoint.PROGRAM_PATHS}, self.baseline(source), case,
            looks=self.looks, documents=documents)
        target = dict(source);target.update(programs)
        return target, description

    def check_owner_layout(self, source):
        layout = device_layout.structural(source['appFw.so'], source['cpapp-b.bin'])
        if layout['mask'] != 63:raise ValueError('This first lab packet requires the existing six imported slots')
        for span in self.owner['owned_regions']:
            at = int(span['offset'], 16);before = bytes.fromhex(span['before_hex'])
            if source['cpapp-b.bin'][at:at+len(before)] != before:
                raise ValueError('Retired project storage differs at ' + span['offset'])

    def trial(self, name=None):
        path = self.root / 'trials' / (name or self.state['trial'])
        helper = PhotoTrial(path, factory=self.factory, zig=self.zig)
        if (path/'rollback.private.json').exists():
            helper.state = json.loads((path/'rollback.private.json').read_text(encoding='utf-8'))
        else:
            path.mkdir(parents=True, exist_ok=False)
            helper.state = {'schema': 'a7c2-photo-lab-trial/1', 'journal': []}
            helper.save('CREATED')
        return helper

    def native(self, helper, camera, kind, mode, build=None):
        helper.state.update(last_kind=kind, last_mode=mode, last_build=build)
        write_json(helper.state_path, helper.state)
        value = helper.native(camera, kind, mode, build)
        if kind == 'runtime':value['boot_id'] = helper.state.get('last_runtime_boot_id')
        return value

    def narrow_capture(self, camera, source):
        # The worker has CP windows only. Back up AP fully once, then verify
        # its actual runtime/disk probe spans instead of rereading100MB twice
        # for each parameter trial.
        values = {'appFw.so': source['appFw.so'],
                  'cpapp-b.bin': camera.read(checkpoint.PROGRAM_PATHS['cpapp-b.bin'])}
        camera.programs_pinned = True
        values['settings-ram.bin'] = camera.snapshot(True)
        values['settings-saved.bin'] = camera.snapshot(False)
        return values

    def check_runtime(self, runtime, source):
        for span in runtime['spans']:
            wanted = source['appFw.so'][span['offset']:span['offset']+span['length']].hex()
            if span['memory'] != wanted or span['disk'] != wanted:
                raise ValueError('AP runtime/disk converter fields changed; no CP write is allowed')

    def boot_id(self, runtime):
        value = runtime.get('boot_id')
        if not value:raise ValueError('Native runtime probe did not return a kernel boot identity')
        return value

    def preservation(self, camera, before):
        for kind, memory in (('ram', True), ('saved', False)):
            devicesettings.compare(self.records(before['settings-'+kind+'.bin']),
                camera.records(camera.snapshot(memory)), {}, camera.core)

    def check_bindings(self, current, case):
        fields = devicesettings.plan(current['appFw.so'],
            self.records(current['settings-ram.bin']), self.records(current['settings-saved.bin']),
            list(range(1, 7)), hash_checks=False)
        if any(len(row['before_ram']) == 2 and row['before_ram'] != '00' for row in fields):
            raise ValueError('Native photo tests require ST as the actual saved/live base of all six slots')
        if case in ('diagnostic-pairs',) or case.startswith(('measure-', 'fit-')):
            if any(row['before_ram'] != row['after'] for row in fields):
                raise ValueError('Parameter measurements require slot adjustments to match native ST; no recipes were changed')

    def plan(self, helper, camera, current, source, case):
        if case != 'restore':self.check_bindings(current, case)
        target, description = self.target(source, case)
        current_programs = {n: current[n] for n in checkpoint.PROGRAM_PATHS}
        target_programs = {n: target[n] for n in checkpoint.PROGRAM_PATHS}
        if any(n != 'cpapp-b.bin' and current_programs[n] != target_programs[n] for n in current_programs):
            raise ValueError('Photo lab cannot edit AP program bytes')
        restoring = case == 'restore'
        builds = checkpointworker.build_programs(current_programs, target_programs,
            helper.root/'forward', self.zig, payload_limit=48000, require_single=True,
            window_priority=photocases.write_priority(restoring))
        inverse = checkpointworker.build_programs(target_programs,
            {n: source[n] for n in checkpoint.PROGRAM_PATHS}, helper.root/'undo', self.zig,
            payload_limit=48000, require_single=True, window_priority=photocases.write_priority(True))
        helper.save('BUILDING', case=case, programs=builds, undo=inverse, description=description)
        for build in builds:self.native(helper, camera, 'program', 0, build)
        runtime = self.native(helper, camera, 'runtime', 0)
        self.check_runtime(runtime, source)
        self.boot_id(runtime)
        if runtime['image_mode'].strip() not in ('0', '2'):raise ValueError('Unsupported retained image state')
        self.preservation(camera, current)
        helper.save('PREFLIGHT_VERIFIED')
        self.save('PREFLIGHT_VERIFIED', prepared_case=case, source_case=self.state.get('installed_case'),
                  runtime_patch_revision=photobuild.REVISION,
                  programs=builds, undo=inverse, description=description,
                  prepared_documents=description.get('documents'),
                  source_documents=self.state.get('installed_documents'),
                  source_phase=self.state['phase'],
                  prepared_runtime=runtime)
        return self.state

    @serialized
    def prepare(self, case, *, backup_copy=None, firmware_version='2.01', skip_reload_verification=False):
        if firmware_version != '2.01':raise ValueError('Read the camera version page: this lab supports 2.01 only')
        fresh = not self.state_file.exists()
        if fresh:
            if backup_copy is None:raise ValueError('Provide an independent backup directory for the first prepare')
            second = Path(backup_copy).resolve()
            if second == self.root or second in self.root.parents or self.root in second.parents:
                raise ValueError('Use independent work and backup directories')
            for path in (self.root, second):
                if path.exists() and any(path.iterdir()):raise ValueError('Preserve old work; select new empty directories')
            self.root.mkdir(parents=True, exist_ok=True);second.mkdir(parents=True, exist_ok=True)
            self.state = {'schema': 'a7c2-photo-lab/1', 'identity': self.owner['identity'],
                          'backup_copy': str(second), 'installed_case': None}
            self.save('READING_ORIGINAL')
        else:
            self.load()
            allowed = ('BACKED_UP', 'PREFLIGHT_VERIFIED', 'LOADED', 'VERIFIED', 'RESTORED')
            if self.state['phase'] not in allowed and not ((case == 'restore' or skip_reload_verification)
                                                         and self.state['phase'] == 'AWAITING_RELOAD'):
                raise ValueError('Inspect or verify the existing trial before preparing another case')
            if case == self.state.get('installed_case') and case != 'compiled-six' and self.state['phase'] in ('LOADED','VERIFIED','RESTORED'):
                return self.state
        self.state['trial'] = case+'-'+uuid.uuid4().hex[:10]
        helper = self.trial();self.save(self.state['phase'])
        try:
            with self.factory(self.state['identity']) as camera:
                checkpoint.same_body(self.state['identity'], camera.identity)
                camera.byte_checks = True
                if fresh:
                    current = helper.capture(camera)
                    self.check_owner_layout(current)
                    checkpoint.write(self.root/'before-lab.private.zip', current, camera.identity,
                                     provenance={'type': 'before-native-photo-lab'})
                    checkpoint.copy(self.root/'before-lab.private.zip',
                                    Path(self.state['backup_copy'])/'before-lab.private.zip')
                    self.save('BACKED_UP', identity=camera.identity)
                    source = current
                    (self.root/'ST.photo-bank.private.bin').write_bytes(self.baseline(source).pack())
                else:
                    source = self.original();current = self.narrow_capture(camera, source)
                    expected, _ = self.target(source, self.state.get('installed_case'), self.state.get('installed_documents'))
                    if any(current[n] != expected[n] for n in checkpoint.PROGRAM_PATHS):
                        raise ValueError('Current programs differ from the last known lab state')
                return self.plan(helper, camera, current, source, case)
        except BaseException as error:
            self.save('NEEDS_REVIEW', error=str(error), failed_during=helper.state.get('phase'))
            raise

    @serialized
    def install(self, battery, *, power_confirmed=False, full_readback=True):
        self.load()
        if self.state['phase'] != 'PREFLIGHT_VERIFIED':raise ValueError('Prepare and preflight this exact trial first')
        if self.state.get('runtime_patch_revision') != photobuild.REVISION:
            raise ValueError('Native-photo builder changed since prepare; no camera connection started. Prepare again before installation')
        if battery is None and power_confirmed is True:
            power = {'source': 'owner-confirmed adequate continuous power', 'battery_percent': None}
        elif type(battery) is int and 50 <= battery <= 100:
            power = {'source': 'owner-reported percentage', 'battery_percent': battery}
        else:raise ValueError('Battery percentage 50..100 or explicit adequate-power confirmation required')
        source = self.original();expected, _ = self.target(source, self.state.get('source_case'), self.state.get('source_documents'))
        target, _ = self.target(source, self.state['prepared_case'], self.state.get('prepared_documents'))
        helper = self.trial()
        try:
            with self.factory(self.state['identity']) as camera:
                checkpoint.same_body(self.state['identity'], camera.identity)
                camera.byte_checks = True;current = self.narrow_capture(camera, source)
                if any(current[n] != expected[n] for n in checkpoint.PROGRAM_PATHS):
                    raise ValueError('Programs changed since preparation; no write was started')
                if self.state['prepared_case'] != 'restore':self.check_bindings(current, self.state['prepared_case'])
                before_runtime = self.native(helper, camera, 'runtime', 0)
                self.check_runtime(before_runtime, source)
                boot = self.boot_id(before_runtime)
                self.save('WRITING', writing_boot=boot, power_confirmation=power);helper.save('WRITING')
                for build in self.state['programs']:self.native(helper, camera, 'program', 1, build)
                if full_readback and camera.read(checkpoint.PROGRAM_PATHS['cpapp-b.bin']) != target['cpapp-b.bin']:
                    raise ValueError('Complete CP program byte readback differs')
                self.preservation(camera, current)
                # Confirm the exact undo is readable before ending this session.
                for build in self.state['undo']:self.native(helper, camera, 'program', 0, build)
                runtime = self.native(helper, camera, 'runtime', 0)
                self.check_runtime(runtime, source)
                if self.boot_id(runtime) != boot:
                    raise ValueError('Kernel restarted during the trial; inspect evidence before testing')
                mode = runtime['image_mode'].strip()
                if mode == '2':
                    self.native(helper, camera, 'wbi', 0);self.native(helper, camera, 'wbi', 1)
                elif mode != '0':raise ValueError('Unsupported retained image state')
            helper.save('AWAITING_RELOAD', complete_CP_readback=full_readback, native_changed_window_readback=True, AP_probe_spans_unchanged=True,
                        AP_program_not_written=True, settings_unchanged=True)
            self.save('AWAITING_RELOAD', installed_case=self.state['prepared_case'], boot_before=boot,
                      loaded_scope='Awaiting full power reload; installed runtime not yet confirmed',
                      installed_documents=self.state.get('prepared_documents'),
                      complete_CP_readback=full_readback, native_changed_window_readback=True, AP_probe_spans_unchanged=True,
                      AP_program_not_written=True, settings_unchanged=True)
            return self.state
        except BaseException as error:
            self.save('NEEDS_REVIEW', error=str(error), failed_during=helper.state.get('phase'))
            raise

    @serialized
    def verify(self, accept_photos=False, *, full_readback=True):
        self.load()
        if self.state['phase'] not in ('AWAITING_RELOAD', 'LOADED', 'VERIFIED', 'RESTORED'):
            raise ValueError('An interrupted or uninstalled trial requires inspection')
        source = self.original();target, _ = self.target(source, self.state['installed_case'], self.state.get('installed_documents'))
        helper = self.trial()
        with self.factory(self.state['identity']) as camera:
            checkpoint.same_body(self.state['identity'], camera.identity)
            if full_readback:
                current = self.narrow_capture(camera, source)
                if any(current[n] != target[n] for n in checkpoint.PROGRAM_PATHS):raise ValueError('Stored programs differ from the installed trial')
            else:camera.programs_pinned = True
            runtime = self.native(helper, camera, 'runtime', 0)
            self.check_runtime(runtime, source)
            boot = self.boot_id(runtime)
            if boot == self.state['boot_before']:raise ValueError('Finish one full power removal; do not reflash')
        phase = 'RESTORED' if self.state['installed_case'] == 'restore' else 'VERIFIED' if accept_photos else 'LOADED'
        self.save(phase, user_preview_and_photos_accepted=accept_photos, boot_after=boot,
                  loaded_scope=('Disk CP bytes and AP boot/spans; CP RAM is not directly read' if full_readback
                                else 'AP boot/spans; whole CP file and CP RAM not read'))
        if phase in ('VERIFIED','RESTORED'):
            from .rawidentity import after_verified
            after_verified(self.state,self.save,self.state['trial'],
                self.state.get('installed_documents') or [None]*6,list(range(1,7)))
        return self.state

    @serialized
    def inspect(self):
        """Read an interrupted result and files; never stage or replay native code."""
        self.load()
        if not (self.root/'before-lab.private.zip').is_file():
            return {'lab_phase': self.state['phase'], 'camera_program_writes': False,
                    'native_code_executed': False, 'backup_complete': False,
                    'error': self.state.get('error'),
                    'next_action': 'Initial backup was not completed; preserve this workspace and use new empty directories'}
        source = self.original();helper = self.trial()
        expected, _ = self.target(source, self.state.get('source_case'), self.state.get('source_documents'))
        target, _ = self.target(source, self.state.get('prepared_case'), self.state.get('prepared_documents'))
        intent = next((event for event in reversed(helper.state.get('journal', []))
                       if event['event'] == 'native_intent'), None)
        report = {'lab_phase': self.state['phase'], 'camera_program_writes': False,
                  'native_code_executed': False, 'pending_result': None,
                  'temporary_files_removed': False}
        with self.factory(self.state['identity']) as camera:
            checkpoint.same_body(self.state['identity'], camera.identity)
            cp = camera.read(checkpoint.PROGRAM_PATHS['cpapp-b.bin'])
            report['CP_matches_before'] = cp == expected['cpapp-b.bin']
            report['CP_matches_target'] = cp == target['cpapp-b.bin']
            if intent:
                raw = camera.temp_read(intent['result'], True)
                if raw is not None:
                    helper.raw('inspected-result.bin', raw)
                    if intent['result'] == 'checkpoint.program.result' and len(raw) == 240:
                        values = struct.unpack_from('<8sIIIIqqqqqqqQQQQ', raw)
                        report['pending_result'] = {'mode': values[2], 'phase': values[3],
                            'writes': values[4], 'status': values[5], 'rollback': values[6],
                            'remount': values[7], 'readonly': values[8], 'cleanup': values[9]}
                    else:report['pending_result'] = {'name': intent['result'], 'bytes': len(raw)}
        helper.record('read_only_lab_inspection', **report)
        return report

    @serialized
    def recover(self):
        """Finish only a positively completed call; never repeat a CP write."""
        self.load()
        if self.state['phase'] != 'NEEDS_REVIEW':return self.state
        source = self.original();helper = self.trial()
        before, _ = self.target(source, self.state.get('source_case'), self.state.get('source_documents'))
        target, _ = self.target(source, self.state.get('prepared_case'), self.state.get('prepared_documents'))
        intent = next((e for e in reversed(helper.state.get('journal', [])) if e['event']=='native_intent'), None)
        if intent is None:raise ValueError('No native completion intent is recorded; inspect the existing trial')
        with self.factory(self.state['identity']) as camera:
            checkpoint.same_body(self.state['identity'], camera.identity)
            camera.programs_pinned = True
            raw = camera.temp_read(intent['result'], True)
            tail = helper.state['journal'][helper.state['journal'].index(intent)+1:]
            cleaned = any(e['event']=='native_cleanup_verified' and e['mode']==intent['mode'] for e in tail)
            verified = any(e['event']=='native_result_verified' and e['mode']==intent['mode'] for e in tail)
            kind = helper.state.get('last_kind')
            build = helper.state.get('last_build')
            known = cleaned and verified
            if raw is not None:
                helper.raw('recovered-result.bin', raw)
                if kind == 'program':
                    try:checkpointworker.program_report(raw, intent['mode'], build);known = True
                    except ValueError:
                        v = struct.unpack_from('<8sIIIIqqqqqqqQQQQ',raw) if len(raw)==240 else ()
                        known = bool(v and v[:3]==(b'A7IRP001',1,intent['mode']) and v[3]==6 and
                                     v[5]<0 and v[6]==0 and v[7]==0 and v[8]==0 and v[9]==0)
                else:
                    camera.core.parse_native(kind, raw, intent['mode'] if kind=='wbi' else None)
                    known = True
            if not known:raise ValueError('Native completion is unknown; no cleanup, firmware write or retry was performed')
            cp = camera.read(checkpoint.PROGRAM_PATHS['cpapp-b.bin'])
            if cp != before['cpapp-b.bin'] and cp != target['cpapp-b.bin']:
                raise ValueError('CP differs from both completed states; preserve logs and inspect before recovery')
            if not cleaned:
                from .nativebuild import ROOT
                blob = (Path(build['path']) if kind=='program' else ROOT/'src/fl23/assets'/('runtime.so' if kind=='runtime' else 'wbi.so')).read_bytes()
                expected = {intent['stage']:blob,'libJit.so':blob,intent['result']:raw}
                if intent.get('request'):expected[intent['request']] = bytes.fromhex(intent['contents_hex'])
                for name, contents in expected.items():
                    actual = camera.temp_read(name, True)
                    if actual is not None:
                        if contents is None or actual != contents:raise ValueError('Unowned temporary contents: '+name)
                        camera.temp_remove(name)
                if kind == 'runtime':
                    extra = camera.temp_read('a7c2.probe.result',True)
                    if extra is not None:
                        camera.core.parse_native('probe',extra);camera.temp_remove('a7c2.probe.result')
                helper.record('known_completion_temporaries_removed_without_program_replay')
            if cp == target['cpapp-b.bin']:
                runtime = self.native(helper,camera,'runtime',0);self.check_runtime(runtime,source)
                boot = self.boot_id(runtime)
                if runtime['image_mode'].strip()=='2':
                    self.native(helper,camera,'wbi',0);self.native(helper,camera,'wbi',1)
                elif runtime['image_mode'].strip()!='0':raise ValueError('Unsupported retained image state')
                self.save('AWAITING_RELOAD',installed_case=self.state['prepared_case'],
                          installed_documents=self.state.get('prepared_documents'),
                          boot_before=self.state.get('writing_boot',boot),
                          recovered_without_program_replay=True,complete_CP_readback=True)
            else:
                self.save(self.state.get('source_phase','BACKED_UP'),
                          installed_case=self.state.get('source_case'),
                          installed_documents=self.state.get('source_documents'),
                          recovered_without_program_replay=True)
        return self.state
