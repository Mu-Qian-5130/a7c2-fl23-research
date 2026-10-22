"""Fresh sound requests supersede history; one live session owns device work."""
from contextlib import contextmanager
from functools import wraps
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import threading
import uuid

_local=threading.local()


class ReconnectRequired(RuntimeError):
    pass


@contextmanager
def command_lock(root):
    from looktool.devicelock import DeviceLock
    root=Path(root).resolve()
    held=getattr(_local,'locks',set())
    if root in held:
        yield
        return
    lock=DeviceLock(root.parent/('.'+root.name+'.sound.lock'))
    try:lock.__enter__()
    except ValueError as exc:
        raise RuntimeError('另一个声音操作仍在执行，请等它结束后再点击。') from exc
    _local.locks=held|{root}
    try:yield
    finally:
        _local.locks=held
        lock.__exit__(None,None,None)


def active():
    return getattr(_local,'replacement',None)


def optional_job(path):
    if not path:return None
    try:return json.loads((Path(path)/'job.private.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):return None


def replace_request(command,*,refresh=True):
    """Old task records never block a new sound request.

    refresh=True re-reads the connected body for the current selection
    (Save, Audition, On). refresh=False keeps the recorded switch/installation
    jobs that the command itself acts on (Off, Restore, Verify). Both archive
    an unresolved earlier operation and reconcile only accounted camera files.
    """
    def decorate(fn):
        @wraps(fn)
        def run(root,state,*args,**kwargs):
            if active() is not None:
                # Save prepares support with On inside the same request/session.
                return fn(root,state,*args,**kwargs)
            with command_lock(root):
                with CurrentRequest(root,state,command,refresh=refresh):
                    return fn(root,state,*args,**kwargs)
        return run
    return decorate


def supersede_pending(root,state,command):
    """Host-only records: archive an unresolved operation instead of blocking."""
    import sound_cli
    pending=state.get('pending')
    if not pending:return False
    state.setdefault('history',[]).append(dict(command=pending.get('command'),job=pending.get('job'),
        phase='superseded_by_current_selection',outcome=pending.get('outcome'),replacement=command))
    state['pending']=None
    sound_cli.save(root,state)
    return True


class BorrowedCamera:
    def __init__(self,request,expected):self.request,self.expected=request,expected
    def __enter__(self):return self.request.open(self.expected)
    def __exit__(self,*args):return False


class CurrentRequest:
    def __init__(self,root,state,command,*,refresh=True):
        self.root,self.state,self.command,self.refresh=Path(root),state,command,refresh
        self.camera=None;self.opening=False;self.previous=None

    def __enter__(self):
        import sound_cli
        self.previous=active()
        if self.previous:raise RuntimeError('Nested sound replacement request')
        self.evidence=self.root/'jobs'/('replace-'+uuid.uuid4().hex[:12])
        self.evidence.mkdir(parents=True)
        (self.evidence/'workspace-before.private.json').write_text(json.dumps(self.state,indent=2))
        pending=self.state.get('pending')
        if pending:
            self.state.setdefault('history',[]).append(dict(command=pending.get('command'),job=pending.get('job'),
                phase='superseded_by_current_selection',outcome=pending.get('outcome'),replacement=self.command))
            self.state['pending']=None
            print('使用本次选择替换声音；旧任务已归档，接下来读取相机现况，不重放旧命令。',flush=True)
        if self.refresh:
            if self.state.get('native_job'):
                self.state.setdefault('history',[]).append(dict(command='previous_native_support',
                    job=self.state.pop('native_job'),phase='refresh_from_current_camera'))
            self.state.pop('native_identity',None)
            audio=optional_job(self.state.get('audio_job'))
            if self.state.get('audio_job') and (not audio or not audio.get('result',{}).get('temporary_pcm_registered')):
                self.state.setdefault('legacy_audio_jobs',[]).append(self.state.pop('audio_job'))
        sound_cli.save(self.root,self.state)
        _local.replacement=self
        return self

    def __exit__(self,*args):
        try:
            if self.camera:self.camera.__exit__(*args)
        finally:_local.replacement=self.previous
        return False

    def open(self,expected):
        import trial
        if self.camera is None:
            self.opening=True
            try:
                camera=trial.factory(expected)
                self.camera=camera.__enter__()
            finally:self.opening=False
            self.prepare()
        if expected and any(expected.get(k)!=self.camera.identity.get(k) for k in ('model','serial_sha256')):
            raise ValueError('当前声音操作的机身绑定不一致')
        return self.camera

    def jobs(self):
        paths=[self.state.get(k) for k in ('native_job','audio_job','boot_job')]
        paths+=self.state.get('legacy_audio_jobs',[])
        paths+=[h.get('job') for h in self.state.get('history',[])]
        paths+=[str(p.parent) for p in self.root.glob('jobs/*/job.private.json')]
        for path in dict.fromkeys(p for p in paths if p):
            value=optional_job(path)
            if value and all(value.get('identity',{}).get(k)==self.camera.identity.get(k) for k in ('model','serial_sha256')):
                yield Path(path),value

    def stop(self,reason,files):
        import sound_cli
        marker=self.camera.read('/tmp/jiritsu/shutter.custom.lease',True)
        if marker is not None:files=dict(files,**{'shutter.custom.lease':marker})
        self.state['replacement_stop']=dict(reason=reason,identity=self.camera.identity,boot_id=self.boot,
            files={name:data.hex() for name,data in files.items() if data is not None})
        sound_cli.save(self.root,self.state)
        self.camera.mark_unknown()
        raise ReconnectRequired(reason)

    def prepare(self):
        """Remove only accounted, finished sound workers; never replay them."""
        import trial,buffer_trial
        camera=self.camera
        boot=camera.read('/proc/sys/kernel/random/boot_id',True)
        self.boot=boot.decode('ascii',errors='replace').strip() if boot else ''
        old_stop=self.state.get('replacement_stop') or {}
        new_boot=(bool(re.fullmatch(r'[0-9a-fA-F-]{36}',self.boot)) and old_stop.get('boot_id')
            and self.boot!=old_stop['boot_id'] and all(old_stop.get('identity',{}).get(k)==camera.identity.get(k)
                for k in ('model','serial_sha256')))
        history=list(self.jobs())
        # Reconcile each outstanding invocation in the sound-only evidence.
        for root,state in history:
            journal=state.get('journal',[])
            stages=[i for i,e in enumerate(journal) if e.get('event')=='native_stage_intent']
            if not stages:continue
            at=stages[-1];intent=journal[at];tail=journal[at+1:]
            if any(e.get('event')=='native_cleanup_verified' for e in tail):continue
            stage,request,result=intent.get('stage'),intent.get('request'),intent.get('result')
            if stage not in ('shutter.staged.so','lut-program-staged.so','lut-runtime-staged.so'):continue
            if result not in ('shutter.probe.result','a7c2.install.result','a7c2.wbi.result'):continue
            names=list(dict.fromkeys(n for n in (stage,request,'libJit.so',result,'a7c2.probe.result') if n))
            actual={n:camera.temp_read(n,True) for n in names}
            if not any(v is not None for v in actual.values()):continue
            for n,v in actual.items():
                if v is not None:(self.evidence/(n+'.before.private.bin')).write_bytes(v)
            blob=actual[stage]
            if blob is not None and hashlib.sha256(blob).hexdigest()!=intent.get('worker_sha256'):
                # This namespace may belong to a more recent sound attempt.
                # Its own journal or the orphan pass below must account for it.
                continue
            if actual.get('libJit.so') is not None and hashlib.sha256(actual['libJit.so']).hexdigest()!=intent.get('worker_sha256'):
                self.stop('相机端存在其他临时命令，本次没有覆盖它。',actual)
            if request and actual.get(request) is not None and actual[request]!=bytes.fromhex(intent.get('contents_hex') or ''):
                self.stop('相机端的临时声音请求不一致，本次尚未开始替换。',actual)
            raw=actual[result]
            finished=raw is not None and complete_report(raw,intent.get('mode'))
            exact_after_boot=new_boot and all(old_stop.get('files',{}).get(n)==v.hex() for n,v in actual.items() if v is not None)
            if actual.get('libJit.so') is not None or not finished:
                if not exact_after_boot:
                    self.stop('旧声音命令没有完整结束报告，需要完整断电结束旧命令后，再点同一个保存或试听按钮。',actual)
            if raw is not None and raw[:8]==b'A7PCM001' and finished:
                parsed=buffer_trial.parse(raw)
                if parsed.get('temporary_pcm_registered'):
                    recovered=dict(state,result=parsed)
                    (self.evidence/'report.private.bin').write_bytes(raw)
                    trial.save(self.evidence,recovered)
                    self.state.setdefault('legacy_audio_jobs',[]).append(str(self.evidence))
                elif parsed.get('audio_registration_trial'):
                    marker=camera.read('/tmp/jiritsu/shutter.custom.lease',True)
                    try:owned=buffer_trial.marker_bytes(parsed,state.get('lease_token_hex',''))
                    except (KeyError,ValueError):owned=None
                    if owned is not None and marker==owned:
                        (self.evidence/'finished-failed-marker.private.bin').write_bytes(marker)
                        camera.temp_remove('shutter.custom.lease')
                        if camera.read('/tmp/jiritsu/shutter.custom.lease',True) is not None:
                            self.stop('已结束的旧试听标记未清理完成，本次尚未开始替换。',{'shutter.custom.lease':marker})
            for n in [n for n in names if n!=result]+[result]:
                if camera.temp_read(n,True)!=actual[n]:self.stop('旧声音临时文件仍在变化，本次尚未开始替换。',actual)
                if actual[n] is not None:camera.temp_remove(n)
                if camera.temp_read(n,True) is not None:self.stop('旧声音报告清理尚未完成，请断电重开后再点同一按钮。',actual)
        # Missing host history needs actionable recovery, not a generic conflict.
        orphan={n:camera.temp_read(n,True) for n in ('shutter.staged.so','shutter.probe.result')}
        if any(v is not None for v in orphan.values()):
            for n in ('libJit.so','a7c2.probe.result','a7c2.install.request'):
                value=camera.temp_read(n,True)
                if value is not None:
                    if n=='a7c2.install.request' and value[:8]!=b'A7SFQ001':
                        self.stop('相机内还有其他未结束的命令，本次声音替换尚未开始。',orphan)
                    orphan[n]=value
            exact_after_boot=new_boot and all(old_stop.get('files',{}).get(n)==v.hex()
                                              for n,v in orphan.items() if v is not None)
            if not exact_after_boot:
                self.stop('相机内有旧声音临时命令但缺少本机记录；完整断电重开后再点同一按钮。',orphan)
            if orphan.get('libJit.so') is not None and orphan['libJit.so']!=orphan.get('shutter.staged.so'):
                self.stop('相机内的临时命令不属于已记录的声音程序，请保留诊断包。',orphan)
            for n,v in orphan.items():
                if v is None:continue
                if camera.temp_read(n,True)!=v:self.stop('旧声音临时文件仍在变化。',orphan)
                (self.evidence/(n+'.orphan-before.private.bin')).write_bytes(v)
                camera.temp_remove(n)
                if camera.temp_read(n,True) is not None:self.stop('旧声音临时文件未清理完成。',orphan)
        # A completed temporary lease may be replaced directly. Do not release
        # old CP handles: their lifetime may have ended on another power cycle.
        marker=camera.read('/tmp/jiritsu/shutter.custom.lease',True)
        if marker is not None:
            paths=[str(root) for root,_ in history]+self.state.get('legacy_audio_jobs',[])
            try:buffer_trial.replace_completed_marker(camera,self.evidence,paths)
            except ValueError:
                if new_boot and old_stop.get('files',{}).get('shutter.custom.lease')==marker.hex():
                    camera.temp_remove('shutter.custom.lease')
                    if camera.read('/tmp/jiritsu/shutter.custom.lease',True) is not None:
                        self.stop('旧试听标记未清理完成，请重新连接后再试。',{'shutter.custom.lease':marker})
                else:self.stop('旧试听缺少可核对的完成报告；完整断电重开后再点同一按钮即可替换。',{'shutter.custom.lease':marker})
        self.state.pop('replacement_stop',None)


def complete_report(raw,mode):
    """A complete terminal report proves the old worker returned, even on error."""
    if len(raw)<16:return False
    magic,version=struct.unpack_from('<8sI',raw)
    if version!=1:return False
    sizes={b'A7SND001':1256,b'A7PCM001':208,b'A7DMA001':144,b'A7BUF001':112,b'A7SFILE1':88,b'A7WBR001':192}
    if magic in sizes:
        if len(raw)!=sizes[magic]:return False
        if magic==b'A7SND001':return struct.unpack_from('<I',raw,12)[0]==16
        if magic in (b'A7PCM001',b'A7DMA001',b'A7BUF001'):
            phase=struct.unpack_from('<I',raw,12)[0]
            return phase==10 or (phase==1 and struct.unpack_from('<q',raw,16)[0]!=0)
        return struct.unpack_from('<I',raw,12)[0]==mode
    if magic==b'A7IRP001':
        from looktool.worker import REPORT
        if len(raw)!=REPORT.size+128:return False
        v=REPORT.unpack_from(raw)
        return v[2]==mode and v[3]<=9 and v[10]==0 and v[11]>0
    return False
