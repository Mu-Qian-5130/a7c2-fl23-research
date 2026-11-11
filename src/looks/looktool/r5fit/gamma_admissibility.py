"""Choose legal RAW Gamma ordinates before exact Windows candidate scoring.

The real float32 builder and strict inverse-table validators are unchanged.
R5 half-unit export requires even ordinates. A small even RAW offset is tried
only when native float32 expansion backsteps on an almost-flat segment.
Every proposal is checked against the actual expanded signed integer table.
"""
import inspect,json,textwrap
from pathlib import Path
import numpy as np

def legal(ctx,y):
    from windows_gamma import expand
    g=expand(ctx.axis,y,ctx.contrast).view('<i2')[32768:].astype(np.int64)
    return bool(np.all(np.diff(g)>=0)),g

def project(ctx,values):
    original=np.asarray(values,dtype=np.int64)
    if original.shape!=(128,)or original[0]!=0 or np.any(np.diff(original)<0)or np.any(original<0)or np.any(original>262143):
        raise ValueError('Cannot project invalid RAW Gamma node order or range')
    # Exact R5 half-unit export roundtrip, before candidate acceptance.
    y=np.minimum(262142,2*((original+1)//2))
    before_ok,before=legal(ctx,y)
    method='half-unit-roundtrip';offset=0;alpha=0.
    result=y
    if not before_ok:
        found=False
        for offset in (2,4,6,8,10,12,14):
            proposal=np.where(y>0,np.minimum(y+offset,262142),0)
            if legal(ctx,proposal)[0]:
                result=proposal;method='small-even-RAW-offset';found=True;break
        if not found:
            for alpha in [2.**k for k in range(-16,1)]:
                proposal=np.minimum(262142,2*np.rint(((1-alpha)*y+alpha*ctx.gamma_y)/2)).astype(np.int64)
                proposal[0]=0
                if legal(ctx,proposal)[0]:
                    result=proposal;method='blend-to-verified-factory-RAW';found=True;break
        if not found:raise ValueError('No legal Windows Gamma projection found')
    after_ok,after=legal(ctx,result)
    if not after_ok:raise AssertionError('Projected Gamma still violates original inverse guard')
    return result,dict(method=method,offset_raw=int(offset)if method=='small-even-RAW-offset'else 0,factory_mix=float(alpha)if method=='blend-to-verified-factory-RAW'else 0,
        before_backsteps=int(np.count_nonzero(np.diff(before)<0)),after_backsteps=0,max_raw_node_change=int(np.max(abs(result-original))),max_expanded_code_change=int(np.max(abs(after-before))),
        zero_fixed=True,even_export_exact=bool(np.all(result%2==0)),builder_unchanged=True)

def install(output):
    import fit_anchor_native,optimizer_policy
    output=Path(output);cache={};old_params=fit_anchor_native.SmoothNative.params
    def record(value):
        with (output/'gamma-admissibility.jsonl').open('a',encoding='utf-8')as f:f.write(json.dumps(value)+'\n')
    def params(self,v):
        result=old_params(self,v);key=result['gamma_y'].tobytes()
        if key not in cache:
            repaired,note=project(self.ctx,result['gamma_y'])
            cache[key]=repaired.copy()
            if note['before_backsteps']:
                record(dict(stage='continuous-to-integer-candidate',raw_before=result['gamma_y'].tolist(),raw_after=repaired.tolist(),**note))
        result['gamma_y']=cache[key].copy()
        return result
    fit_anchor_native.SmoothNative.params=params
    source=inspect.getsource(optimizer_policy.refine_native)
    before='        rgb=center_mean(render_native(ctx.build(**p),inputs))/16383'
    assert source.count(before)==1
    after="""        try:
            rgb=center_mean(render_native(ctx.build(**p),inputs))/16383
        except ValueError as error:
            if str(error) != 'MainGamma must be signed and monotone on positive input':
                raise
            return float('inf')"""
    patched=source.replace(before,after)
    namespace=dict(optimizer_policy.__dict__)
    exec(compile(patched,'<original-refine-native-reject-nonmonotone-Windows-Gamma>','exec'),namespace)
    optimizer_policy.refine_native=fit_anchor_native.refine_native=namespace['refine_native']
    audit=dict(change='quantized-parameter admissibility only; actual Windows builder and inverse guards unchanged',even_RAW_offsets=[2,4,6,8,10,12,14],fallback='verified factory RAW curve blend; acceptance still uses original exact candidate output',integer_search='illegal Gamma moves have infinite cost and are rejected',
        original_sources_modified=False,camera_io=False)
    (output/'gamma-admissibility-policy.json').write_text(json.dumps(audit,indent=2)+'\n')
    return audit
