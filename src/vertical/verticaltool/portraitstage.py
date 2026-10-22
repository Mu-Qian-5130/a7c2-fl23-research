"""Scoped portrait resource transaction inside an existing camera session."""
from pathlib import Path
import struct
from . import portraitbank,portraitlayout,portraitworker


class Stage:
    def __init__(self,camera,owner,*,ap=None,sources=None):
        self.camera,self.owner=camera,owner
        self.ap=ap if ap is not None else camera.read('/usr/lib/appFw.so')
        self.sources=sources if sources is not None else [camera.read(path) for path in portraitworker.PATHS[:2]]
        self.prepared=[portraitbank.prepare(source,group) for group,source in enumerate(self.sources)]
        self.originals=[row[0] for row in self.prepared]
        self.targets=[row[1] for row in self.prepared]
        self.plans=[row[2] for row in self.prepared]
        self.windows=portraitlayout.canonical_windows(self.ap)
        self.build=None
        self.restored=[original+source[len(original):] for original,source in zip(self.originals,self.sources)]
        self.target_ap=portraitlayout.references(self.ap,True)[0]
        self.original_ap=portraitlayout.references(self.ap,False)[0]
        self.owner.state['portrait_plan']=dict(
            bank_plans=self.plans,AP_windows=self.windows,assets=len(portraitlayout.IMAGES),shared_gauge_assets_changed=7)
        self.owner.record('portrait_current_bytes_planned',
            appended_bytes=sum(len(t)-len(o) for t,o in zip(self.targets,self.originals)),
            AP_windows=len(self.windows),assets=len(portraitlayout.IMAGES))

    def reconcile(self):
        """Archive our former worker; a new plan operates on captured bytes."""
        names=('portrait.staged.so','portrait.request','portrait.result')
        values={name:self.camera.temp_read(name,True) for name in names}
        if not any(value is not None for value in values.values()):return
        staged=values['portrait.staged.so']
        if staged is not None and not (staged.startswith(b'\x7fELF') and b'portrait.request' in staged and
                                       b'portrait.result' in staged and b'image_00_32_IPSX.uxc' in staged):
            raise ValueError('Existing portrait worker is not recognized; retain its diagnostics')
        raw=values['portrait.result']
        if raw is not None and (len(raw)!=struct.calcsize(portraitworker.FORMAT) or raw[:8]!=portraitworker.MAGIC):
            raise ValueError('Existing portrait result is not recognized; retain its diagnostics')
        request=values['portrait.request']
        if request is not None and (len(request)!=16 or request[:8]!=portraitworker.MAGIC):
            raise ValueError('Existing portrait request is not recognized; retain its diagnostics')
        jit=self.camera.temp_read('libJit.so',True)
        if jit is not None and (staged is None or jit!=staged):
            raise ValueError('Another native operation owns libJit.so; retain its diagnostics')
        probe=self.camera.temp_read('a7c2.probe.result',True)
        if probe is not None:
            self.camera.core.parse_native('probe',probe)
            values['a7c2.probe.result']=probe
        for name,value in values.items():
            if value is not None:self.owner.raw('prior-'+name,value)
        self.owner.record('portrait_prior_worker_accounted_from_current_bytes',has_result=raw is not None)
        for name,value in values.items():
            if value is not None:self.camera.temp_remove(name)
        if jit is not None:self.camera.temp_remove('libJit.so')

    def invoke(self,mode):
        from looktool.devicesession import invoke
        if self.build is None:
            self.reconcile()
            self.build=portraitworker.build(self.plans,self.ap,self.owner.root/'portrait-worker',ap_windows=self.windows)
        return invoke(self.camera,Path(self.build['path']).read_bytes(),stage='portrait.staged.so',
            request='portrait.request',result='portrait.result',contents=struct.pack('<8sII',portraitworker.MAGIC,mode,0),
            mode=mode,decode=lambda raw:portraitworker.decode(raw,mode),record=self.owner.record,
            save_raw=lambda raw:self.owner.raw('portrait-'+str(mode)+'.bin',raw),extras=('a7c2.probe.result',))

    def verify(self,enabled,*,clean=False):
        expected=self.targets if enabled else self.originals if clean else self.restored
        for path,target in zip(portraitworker.PATHS[:2],expected):
            if self.camera.read(path)!=target:raise ValueError('Portrait resource readback differs: '+path)
        ap=self.target_ap if enabled else self.original_ap
        if self.camera.read('/usr/lib/appFw.so')!=ap:raise ValueError('Portrait AP reference readback differs')
        self.owner.record('portrait_full_resource_and_AP_bytes_verified',enabled=enabled,clean=clean)

    def restore(self,*,cleanup=True):
        changed=self.ap!=self.original_ap or self.sources!=self.restored
        result=self.invoke(2) if changed else dict(writes=0,bytes_written=0)
        self.verify(False)
        if cleanup and any(len(source)>len(original) for source,original in zip(self.sources,self.originals)):
            cleaned=self.invoke(3)
            if cleaned.get('cleanup_deferred'):
                self.owner.record('portrait_inert_tail_cleanup_after_reload',bytes=sum(len(s)-len(o) for s,o in zip(self.sources,self.originals)))
            else:self.verify(False,clean=True)
            result.update(cleanup=cleaned)
        return result
