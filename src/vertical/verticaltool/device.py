"""Small reversible resource transaction and a RAM-only native setting."""
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
ASSETS = ROOT / 'src/vertical/assets'
SETTING = 0x02cf1906
VALUE_RVA = 0x7e732b8
SOURCES = [f'/usr/share/app/image_{i:02d}_32_IPSX.uxc' for i in range(3)]
ALIASES = [f'/usr/share/app/image_{i:02d}_23_IPSX.uxc' for i in range(3)]


def save_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.flush()
        __import__('os').fsync(stream.fileno())
    temporary.replace(path)


class Journal:
    def __init__(self, folder, command):
        self.folder = Path(folder).resolve()
        self.folder.mkdir(parents=True, exist_ok=True)
        self.state_path = self.folder / 'state.private.json'
        self.previous = (json.loads(self.state_path.read_text(encoding='utf-8'))
                         if self.state_path.exists() else {})
        if command == 'enable' and self.previous.get('phase') in ('running', 'needs_review'):
            raise ValueError('Previous operation needs review; preserve its report and inspect status first')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        self.run = self.folder / (stamp + '-' + uuid4().hex[:8])
        self.run.mkdir()
        self.path = self.run / 'report.private.json'
        self.report = dict(command=command, program_writes=False, bitmap_writes=False,
                           backup_API_writes=False, events=[])
        if self.previous.get('report'):
            self.report['previous_report'] = self.previous['report']
            self.report['previous_phase'] = self.previous.get('phase')
        self.record('started')

    def record(self, event, **data):
        self.report['events'].append(dict(event=event, **data))
        save_json(self.path, self.report)

    def raw(self, label, data):
        (self.run / (label + '.private.bin')).write_bytes(data)

    def state(self, phase, identity):
        save_json(self.state_path, dict(schema='a7c2-vertical-preview/1', phase=phase,
                  identity=identity, report=str(self.path), aliases=ALIASES))


def parse_probe(raw):
    if len(raw) != 64:
        raise ValueError('Incomplete vertical probe result')
    magic, version, model, status, rva, value, reserved, info = struct.unpack('<8sIIqQII24s', raw)
    if magic != b'A7VUI001' or version != 1 or rva != VALUE_RVA or reserved:
        raise ValueError('Unexpected vertical probe ABI')
    if not status and (model != 16 or value not in (0, 1)):
        raise ValueError('Unexpected native model/value')
    return dict(status=status, model_index=model, value=value, info_hex=info.hex())


def parse_ram(raw, target):
    if len(raw) != 72:
        raise ValueError('Incomplete vertical RAM result')
    row = struct.unpack('<8sIIqQIIII24s', raw)
    if row[0] != b'A7VTR001' or row[1] != 1 or row[4] != VALUE_RVA or row[7] != target:
        raise ValueError('Unexpected vertical RAM ABI')
    if not row[3] and (row[2] != 16 or row[5] not in (0, 1) or row[6] != target
                      or row[8] != int(row[5] != target)):
        raise ValueError('Unexpected vertical RAM write result')
    return dict(status=row[3], before=row[5], after=row[6], wrote=row[8])


def parse_aliases(raw, mode):
    if len(raw) != 104:
        raise ValueError('Incomplete resource-alias result')
    row = struct.unpack('<8sIIIIqqqIIII3II3Q', raw)
    if row[:3] != (b'A7VRS001', 1, mode) or row[4] != 3 or row[15]:
        raise ValueError('Unexpected resource-alias ABI')
    return dict(mode=mode, phase=row[3], status=row[5], rollback=row[6], readonly=row[7],
                source_ok=row[8], prior=row[9], created=row[10], removed=row[11],
                source_counts=list(row[12:15]), source_sizes=list(row[16:19]))


def require_ok(result):
    if result['status']:
        raise ValueError('Native operation stopped: ' + str(result))
    return result


def require_aliases(result):
    require_ok(result)
    if result['readonly'] or result['source_ok'] != 7 or result['phase'] != (1 if result['mode'] == 0 else 5):
        raise ValueError('Resource transaction did not confirm the original banks/read-only mount')
    return result


class Workers:
    def __init__(self, camera, journal):
        self.camera, self.journal = camera, journal
        self.sequence = 0

    def call(self, name, decoder, mode=0, contents=None):
        from looktool.devicesession import invoke
        self.sequence += 1
        aliases = name == 'aliases.so'
        return invoke(self.camera, (ASSETS / name).read_bytes(),
            stage='lut-names-staged.so' if aliases else 'lut-runtime-staged.so',
            request='a7c2.names.request' if aliases else None,
            result='a7c2.names.result' if aliases else 'a7c2.runtime.result',
            contents=contents, mode=mode, decode=decoder, record=self.journal.record,
            save_raw=lambda raw: self.journal.raw(f'{self.sequence:02d}-{name}', raw),
            extras=('a7c2.probe.result',))

    def probe(self):
        return require_ok(self.call('vertical_probe.so', parse_probe))

    def ram(self, target):
        name = 'vertical_enable_ram.so' if target == 0 else 'vertical_disable_ram.so'
        return require_ok(self.call(name, lambda raw: parse_ram(raw, target), mode=target))

    def aliases(self, mode):
        result = self.call('aliases.so', lambda raw: parse_aliases(raw, mode), mode=mode,
                           contents=struct.pack('<8sII', b'A7VRS001', mode, 0))
        self.journal.report['last_alias_result'] = result
        self.journal.record('alias_result', result=result)
        return result


def settings(camera):
    selected = {}
    for label, memory in [('ram', True), ('saved', False)]:
        record = camera.records(camera.snapshot(memory))[0][SETTING]
        selected[label] = dict(value_hex=record.data.hex(), attribute=record.attr)
    return selected


def prepare_camera(camera, journal):
    camera.byte_checks = True
    ap = camera.read('/usr/lib/appFw.so')
    cp = camera.read('/cp/cpapp-b.bin')
    camera.pin_programs(ap, cp)
    if camera.identity_pending:
        # Existing shared read-only native model probe for initial busy/no-media sessions.
        from looktool.devicesession import invoke
        blob = (ROOT / 'src/fl23/assets/runtime.so').read_bytes()

        def decode(raw):
            parsed = camera.core.parse_native('runtime', raw)
            parsed['model_index'] = struct.unpack_from('<I', raw, 48)[0]
            return parsed

        runtime = invoke(camera, blob, stage='lut-runtime-staged.so', request=None,
            result='a7c2.runtime.result', contents=None, mode=0, decode=decode,
            record=journal.record, save_raw=lambda raw: journal.raw('identity', raw),
            extras=('a7c2.probe.result',))
        camera.confirm_identity(runtime)


def execute(command, folder, *, camera_factory=None, workers_factory=Workers):
    if command not in ('status', 'enable', 'disable', 'remove'):
        raise ValueError('Unknown vertical-display command')
    journal = Journal(folder, command)
    expected = journal.previous.get('identity')
    identity = expected
    camera = None
    workers = None
    ram_intent = False
    adding = False
    before_settings = None
    if camera_factory is None:
        from looktool.devicesession import Camera
        camera_factory = Camera
    try:
        with camera_factory(expected=expected) as camera:
            prepare_camera(camera, journal)
            identity = camera.identity
            workers = workers_factory(camera, journal)
            journal.state('running', identity)
            before = workers.probe()
            before_settings = settings(camera)
            inspected = require_aliases(workers.aliases(0))
            journal.report.update(identity=identity, before=before,
                                  settings_before=before_settings, inspected=inspected)
            journal.record('inspection_complete')
            try:
                if command != 'status':
                    if any(row['value_hex'] != '01' for row in before_settings.values()):
                        raise ValueError('Preview requires saved/Backup-RAM vertical setting OFF; no settings were changed')
                    if command == 'enable':
                        if inspected['prior'] not in (0, 7):
                            raise ValueError('Partial aliases exist; inspect the report and use remove before enable')
                        originals = [camera.read(path) for path in SOURCES]
                        if [len(data) for data in originals] != inspected['source_sizes']:
                            raise ValueError('Original graphics length changed during the session')
                        if not inspected['prior']:
                            if before['value'] == 0:
                                ram_intent = True
                                workers.ram(1)
                            adding = True
                            installed = workers.aliases(1)
                            require_aliases(installed)
                            if installed['created'] != 7 or installed['removed']:
                                raise ValueError('All three aliases were not added')
                        for path, original in zip(ALIASES, originals):
                            if camera.read(path) != original:
                                raise ValueError('Complete alias readback differs: ' + path)
                        journal.record('all_alias_targets_fully_read_back')
                        ram_intent = True
                        workers.ram(0)
                    else:
                        ram_intent = True
                        workers.ram(1)
                        if command == 'remove':
                            require_aliases(workers.aliases(2))
                            if any(camera.read(path, True) is not None for path in ALIASES):
                                raise ValueError('An alias still resolves after removal')
                after = workers.probe()
                after_settings = settings(camera)
                final_aliases = require_aliases(workers.aliases(0))
                if after_settings != before_settings:
                    raise ValueError('Selected saved/Backup-RAM setting changed during the trial')
                target = 0 if command == 'enable' else 1 if command in ('disable', 'remove') else before['value']
                if after['value'] != target:
                    raise ValueError('Running vertical switch did not read back as requested')
                expected_aliases = 7 if command == 'enable' else 0 if command == 'remove' else inspected['prior']
                if final_aliases['prior'] != expected_aliases:
                    raise ValueError('Final alias set differs from the requested operation')
                journal.report.update(after=after, settings_after=after_settings,
                                      final_aliases=final_aliases, complete=True)
                journal.record('completed')
            except BaseException:
                if camera.link.healthy:
                    if ram_intent:
                        try:
                            workers.ram(1)
                            journal.record('known_failure_running_switch_restored_OFF')
                        except BaseException as cleanup:
                            journal.record('RAM_cleanup_stopped', error=str(cleanup))
                    last = journal.report.get('last_alias_result', {})
                    if adding and camera.link.healthy and last.get('readonly') == 0:
                        # Only a known result permits cleanup; invoke marks unknown outcomes unhealthy.
                        try:
                            require_aliases(workers.aliases(2))
                            journal.record('known_failure_new_aliases_removed')
                        except BaseException as cleanup:
                            journal.record('alias_cleanup_stopped', error=str(cleanup))
                raise
        # Reading status must not silently clear an unresolved earlier write.
        unresolved = (command == 'status' and journal.previous.get('phase') in ('running', 'needs_review'))
        journal.state('needs_review' if unresolved else 'complete', identity)
        return dict(running='ON' if after['value'] == 0 else 'OFF',
                    saved='OFF' if after_settings['saved']['value_hex'] == '01' else 'ON',
                    alias_count=final_aliases['prior'].bit_count(), report=str(journal.path))
    except BaseException as exc:
        journal.record('stopped', error_type=type(exc).__name__, error=str(exc))
        unknown = camera is not None and not camera.link.healthy
        unresolved = journal.previous.get('phase') in ('running', 'needs_review')
        phase = 'needs_review' if ram_intent or adding or unknown or unresolved else 'failed_before_change'
        journal.state(phase, identity)
        raise
