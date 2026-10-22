"""Local factory transaction discovery and accounted temporary-state cleanup.

No device access at import/discovery. Recovery re-plans from current bytes;
it never replays a request with an unknown outcome.
"""
import json
import os
from pathlib import Path

FINISHED = {'AWAITING_RELOAD', 'LOADED', 'COMPLETE'}


def supersede_temporary(camera, folder, record):
    """Archive inert project work files before planning a NEW factory target.

    This does not infer success of, or replay, the former operation. The caller
    captures current programs/settings/resources AFTER cleanup and builds new
    byte-checked writes from the built-in reference. Never replace libJit.so.
    """
    from .devicesession import TEMP_NAMES
    from .checkpointjob import TEMPS
    names=sorted((TEMP_NAMES | TEMPS)-{'libJit.so'})
    actual={name:camera.temp_read(name,True) for name in names}
    actual={name:raw for name,raw in actual.items() if raw is not None}
    if not actual:return 0
    if camera.temp_read('libJit.so',True) is not None:
        raise ValueError('相机执行插件仍存在，不能在执行期间覆盖；本次尚未恢复写入，请结束连接后完整断电再重试')
    if camera.read('/etc/ld.so.preload',True):
        raise ValueError('相机存在启用中的 preload，尚未覆盖临时工作文件或开始恢复写入')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    # Save every captured byte before removing anything on the camera. These
    # are tiny private worker/request/report files, not a body firmware backup.
    for name,raw in actual.items():
        path=folder/name
        with path.open('xb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        if path.read_bytes()!=raw:raise ValueError('Temporary archive readback differs: '+name)
    record('factory_temporary_archived',files={name:len(raw) for name,raw in actual.items()},
           old_operation_replayed=False,previous_outcome_inferred=False)
    # Check the whole namespace before deletion. A newly appearing report or
    # loader means it is changing, not merely leftover data.
    if camera.temp_read('libJit.so',True) is not None:
        raise ValueError('相机执行插件出现，已保存诊断，未覆盖工作文件')
    for name in names:
        if camera.temp_read(name,True)!=actual.get(name):
            raise ValueError('相机临时状态仍在变化，已保存诊断，未覆盖工作文件：'+name)
    # Keep reports until last if the connection fails during cleanup.
    for name in sorted(actual,key=lambda value:value.endswith('.result')):
        if camera.temp_read(name,True)!=actual[name]:
            raise ValueError('Temporary state changed during factory cleanup: '+name)
        camera.temp_remove(name)
        if camera.temp_read(name,True) is not None:
            raise ValueError('Temporary cleanup incomplete: '+name)
    record('factory_temporary_superseded',files=list(actual),old_operation_replayed=False)
    print('旧临时工作文件已保存诊断并清理；重新读取相机现况，直接按内建原厂基准生成恢复计划，不重放旧任务。',flush=True)
    return len(actual)


def prewrite_temporary_conflict(state):
    """A fresh restore stopped on shared names before any changing worker."""
    if (state.get('mode')!='factory_reset' or state.get('phase')!='NEEDS_REVIEW'
            or state.get('failed_during') not in ('READING','PLANNED','PREFLIGHT_VERIFIED')
            or state.get('resume_from')):
        return False
    if state.get('error') not in {
        'Existing temporary state needs recovery: '+name for name in
        ('lut-names-staged.so','a7c2.names.request','a7c2.names.result')
    } | {'相机执行插件仍存在，不能在执行期间覆盖；本次尚未恢复写入，请结束连接后完整断电再重试'}:return False
    outstanding=set()
    for event in state.get('journal',[]):
        kind=event.get('event','')
        if kind.endswith('native_intent') and event.get('mode')!=0:return False
        if kind.endswith('native_stage_intent'):
            if event.get('mode')!=0:return False
            outstanding.add((kind[:-len('stage_intent')],event.get('stage')))
        elif kind.endswith('native_cleanup_verified'):
            outstanding.discard((kind[:-len('cleanup_verified')],event.get('stage')))
    return not outstanding


def connection_failed_before_restore(state):
    return (state.get('mode')=='factory_reset' and state.get('phase')=='NEEDS_REVIEW'
            and state.get('failed_during')=='READING' and state.get('journal')==[]
            and not state.get('identity') and not state.get('resume_from'))


def chain(folder):
    result, seen = [], set()
    while folder:
        root = Path(folder).resolve()
        if root in seen:
            raise ValueError('Recovery transaction ancestry contains a loop')
        seen.add(root)
        state = json.loads((root / 'direct.private.json').read_text(encoding='utf-8'))
        if state.get('mode') != 'factory_reset':
            raise ValueError('Not a factory recovery transaction')
        result.append((root, state))
        folder = state.get('resume_from')
    return list(reversed(result))


def pending(work_root, preferred=None):
    """Find the latest meaningful transaction per body, ignoring read-only failures.

    Old records are evidence for a restore, never a precondition: one that
    cannot be read or attributed is skipped (and kept), so the restore button
    re-plans from the connected camera instead of stopping on stale state.
    """
    paths = set(Path(work_root).glob('*/direct.private.json'))
    if preferred and Path(preferred, 'direct.private.json').is_file():
        paths.add(Path(preferred, 'direct.private.json'))
    rows = []
    for path in paths:
        try:
            state = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            print('本地记录无法读取，未用于自动续接（记录保留）：' + str(path), flush=True)
            continue
        if not isinstance(state, dict):
            continue
        if state.get('mode') != 'factory_reset' or not state.get('identity'):
            continue
        journal = state.get('journal', [])
        stages = [i for i, r in enumerate(journal) if r.get('event') == 'native_stage_intent']
        unfinished_native = bool(stages) and not any(r.get('event') == 'native_cleanup_verified' for r in journal[stages[-1] + 1:])
        meaningful = (state.get('phase') in FINISHED or bool(state.get('resume_from')) or
                      unfinished_native or any(r.get('event') == 'native_intent' and r.get('mode') in (1, 2) for r in journal))
        if not meaningful:
            continue
        identity = state['identity']
        key = (identity.get('model'), identity.get('serial_sha256') or identity.get('usb_serial_sha256'))
        if not all(key):
            print('恢复记录缺少机身身份，未用于自动续接（记录保留）：' + str(path), flush=True)
            continue
        rows.append((path.stat().st_mtime_ns, str(path), key, path.parent.resolve(), state))
    latest = {}
    for row in sorted(rows):
        latest[row[2]] = row
    # LOADED + verified RO is already a completed device recovery. Physical
    # photo acceptance remains separate; it must not keep hijacking future
    # Restore clicks after the owner installs other features again.
    active = [r for r in latest.values() if not (
        r[4].get('phase') == 'COMPLETE' or
        (r[4].get('phase') == 'LOADED' and r[4].get('readonly_after_reload_verified') is True))]
    if preferred:
        selected = Path(preferred).resolve()
        for row in active:
            try:
                ancestry = [root for root, _ in chain(row[3])]
            except (OSError, ValueError):
                ancestry = [row[3]]
            if selected in ancestry:
                return row[3], row[4]
    if len(active) > 1:
        # Which body is connected is unknown until USB opens; a fresh restore
        # binds to the connected body and re-plans from its current bytes.
        print('有多台机身的未完成恢复记录（均保留）；本次按当前连接的相机重新生成恢复计划：' +
              '; '.join(str(r[3]) for r in active), flush=True)
        return None
    return (active[0][3], active[0][4]) if active else None
