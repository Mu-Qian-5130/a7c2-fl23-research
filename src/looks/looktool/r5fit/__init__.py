"""C2 integration of Hearts-Ace colorlab 06c3557 numerical fitting.

The response is calibrated on C2 measurements. Only original native integer
parameters and a packed grid are exported; no PC model enters the firmware.
"""
from pathlib import Path
import json
import os
import sys
import types

ROOT=Path(__file__).resolve().parent
COMMIT='06c35577255eddef641c695d179b0e6f699ffe62'
IDENTITY=dict(schema='r5-measured-grid-response/1',preset='c2-hybrid-20261110',model='ILCE-7CM2')

def initialize(threads=3,calibration=None):
    """Select CPU explicitly; keep upstream objectives and integer acceptance."""
    for folder in (ROOT,ROOT/'upstream/R5ColorLab/amd',ROOT/'upstream/R5ColorLab/scripts'):
        if str(folder) not in sys.path:sys.path.insert(0,str(folder))
    device=os.environ.get('A7LOOK_FIT_DEVICE','cpu')
    if device not in ('cpu','cuda'):raise ValueError('Unsupported C2 fitting device')
    runtime=types.ModuleType('gpu_runtime')
    runtime.resolve_device=lambda:device
    runtime.available=lambda:True
    runtime.synchronize=lambda:torch.cuda.synchronize()if device=='cuda'else None
    runtime.empty_cache=lambda:torch.cuda.empty_cache()if device=='cuda'else None
    runtime.configure=lambda:None
    runtime.policy=lambda:dict(device=device,backend='PyTorch '+device+'; upstream mathematical objectives',threads=threads)
    sys.modules['gpu_runtime']=runtime
    import torch
    if device=='cuda'and not torch.cuda.is_available():raise RuntimeError('Requested CUDA accelerator is unavailable')
    torch.set_num_threads(threads)
    if device=='cuda':
        torch.set_float32_matmul_precision('highest')
        torch.backends.cuda.matmul.allow_tf32=False
        torch.backends.cudnn.allow_tf32=False
        # The GPU hosts' older OpenBLAS crashes inside the tall-Jacobian
        # DGESDD correction when the upstream progress wrapper enables ten
        # BLAS threads. Keep the same SVD/objective on one BLAS thread.
        from threadpoolctl import threadpool_limits
        threadpool_limits(limits=1,user_api='blas')
        import training_progress
        progress_init=training_progress.TrainingProgress.__init__
        if not getattr(progress_init,'c2_single_blas',False):
            def initialize_progress(self,path,total=0,gradient_workers=1):
                progress_init(self,path,total,gradient_workers=1)
            initialize_progress.c2_single_blas=True
            training_progress.TrainingProgress.__init__=initialize_progress
    # The GPU nodes have an older SciPy. Their fallback has identical finite
    # differences and bounds; only observational callback/worker dispatch was
    # added in 1.16. Keep this compatibility shim outside numerical objectives.
    import inspect,scipy.optimize
    original_ls=scipy.optimize.least_squares
    if 'callback'not in inspect.signature(original_ls).parameters:
        def least_squares(*args,callback=None,workers=None,**kwargs):return original_ls(*args,**kwargs)
        scipy.optimize.least_squares=least_squares
    from hybrid_response import HybridModel
    value=json.loads(Path(calibration or ROOT/'data/response.json').read_text(encoding='utf-8'))
    if value.get('response_basis')!='rgb-hue3-nonlinear/1' or value.get('source',{}).get('model')!='ILCE-7CM2':
        raise ValueError('Select a C2 Hybrid response JSON; R5 camera coefficients cannot be used')
    model=HybridModel(value,None,identity=IDENTITY)
    model.value['metadata']=dict(model='ILCE-7CM2',physical_scope='C2 historical physical grid probes')
    model.base.value['metadata']=model.value['metadata'].copy()
    measured=types.ModuleType('measured_response')
    measured.SCHEMA=IDENTITY['schema']
    measured.is_measured=lambda v:isinstance(v,dict)and v.get('schema')==IDENTITY['schema']
    def get(v):
        if v!=IDENTITY:raise ValueError('C2 fitting requires the bundled C2 response')
        return model
    measured.get=get
    measured.require=lambda v:(get(v),v)[1]
    measured.hybrid_response=measured.default_response=lambda:IDENTITY.copy()
    sys.modules['measured_response']=measured
    import compute_backend
    compute_backend.WORKERS=threads
    import numpy as np
    original_render=getattr(compute_backend.render_native,'_c2_original',compute_backend.render_native)
    def render_flatfield(model,inputs):
        values=np.asarray(inputs)
        if values.ndim==3 and values.shape[1]==9 and np.all(values==values[:,:1,:]):
            # The source cohort repeats one post-SSCS integer RGB nine times.
            # Retain the original nine-point output and its averaging order.
            # The recovered hue frontend requires its original five-pixel
            # horizontal stencil. A constant patch has the same center output.
            once=original_render(model,values[:,:5,:])[:,2:3,:]
            return np.broadcast_to(once,values.shape).copy()
        return original_render(model,values)
    render_flatfield._c2_original=original_render
    compute_backend.render_native=render_flatfield
    import edit_parameter_context
    from windows_gamma import expand
    from windows_area import area_comp
    edit_parameter_context.expand_gamma=expand
    edit_parameter_context.RuntimeColor.area_comp=lambda self,p:area_comp(p,self.area_controls)
    import gpu_optimizer
    original=gpu_optimizer.StageObjective.__init__
    if not getattr(original,'c2_cpu',False):
        def init(self,*args,**kwargs):
            kwargs['device']=device;kwargs['dtype']=torch.float64 if device=='cpu'else torch.float32
            original(self,*args,**kwargs)
        init.c2_cpu=True
        gpu_optimizer.StageObjective.__init__=init
    return model

def context():
    import numpy as np
    from edit_color_pipeline import RuntimeColor
    with np.load(ROOT/'data/context.npz')as z:
        return RuntimeColor(*(z[k].tobytes()for k in ('runtime','raw','settings')),area_controls=z['area'].tobytes())

def save(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')

def metrics(target,prediction):
    import numpy as np
    e=np.abs(np.floor(np.clip(target,0,1)*255+.5)-np.floor(np.clip(prediction,0,1)*255+.5))
    return dict(points=len(e),rmse=float(np.sqrt(np.mean(e*e))),p95_channel=float(np.percentile(e,95)),
        p99_channel=float(np.percentile(e,99)),maximum_channel=float(e.max()),severe_gt30_points=int(np.count_nonzero(e.max(1)>30)))

def preflight():
    """Exercise packaged CPU/tensor inference, signed grid codec and gradients."""
    import numpy as np
    model=initialize()
    import torch
    from gpu_tensor import TensorTools
    from gpu_color import paired_tensor
    from residual_grid import pack,unpack
    rng=np.random.default_rng(20261110)
    rgb=np.r_[rng.uniform(.015,.985,(256,3)),np.linspace(0,1,17)[:,None]*np.ones((1,3))]
    table=rng.integers(-64,64,(405,3))
    if not np.array_equal(unpack(pack(table)),table):raise ValueError('Signed native grid roundtrip differs')
    tools=TensorTools('cpu',torch.float64)
    x=tools.tensor(rgb).requires_grad_(True)
    actual=paired_tensor(tools,x,tools.tensor(table),IDENTITY)
    error=float(np.max(np.abs(actual.detach().numpy()-model.predict_cpu(rgb,table))))
    if error>1e-12:raise ValueError('C2 Hybrid CPU/tensor inference differs')
    actual.sum().backward()
    if not torch.isfinite(x.grad).all():raise ValueError('Nonfinite C2 response gradient')
    np.testing.assert_array_equal(model.predict_cpu(rgb,np.zeros((405,3))),rgb)
    return dict(model='ILCE-7CM2',upstream_commit=COMMIT,points=len(rgb),cpu_tensor_max_abs_error=error,
        gradients_finite=True,signed_grid_roundtrip=True,zero_grid_identity=True,camera_io=False)

def fit(target,output,*,evaluations=2000,starts=12,threads=3,previous=None,calibration=None):
    """Native baseline, up to five target-grid rounds, three frozen-Gamma stacks."""
    import copy
    import numpy as np
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    run_input=dict(evaluations=evaluations,starts=starts,
        response=json.loads(Path(calibration or ROOT/'data/response.json').read_text(encoding='utf-8')))
    request=output/'run-input.json'
    if request.exists()and json.loads(request.read_text(encoding='utf-8'))!=run_input:
        raise ValueError('Saved fitting inputs changed; use a new work directory')
    if not request.exists():save(request,run_input)
    frozen_context=output/'input-context.npz'
    context_bytes=(ROOT/'data/context.npz').read_bytes()
    if frozen_context.exists()and frozen_context.read_bytes()!=context_bytes:
        raise ValueError('Saved native color context changed; use a new work directory')
    if not frozen_context.exists():frozen_context.write_bytes(context_bytes)
    model=initialize(threads,calibration)
    device=os.environ.get('A7LOOK_FIT_DEVICE','cpu')
    from edit_parameter_context import ParameterContext,RuntimeColor
    from patch_sampling import center_mean
    from compute_backend import render_native
    from residual_grid import pack,unpack
    from training_progress import TrainingProgress
    with np.load(ROOT/'data/inputs.npz')as z:data={k:z[k].copy()for k in z.files}
    target=np.asarray(target,dtype=float)
    if target.shape!=(len(data['input']),3)or not np.isfinite(target).all():raise ValueError('C2 target array differs')
    pairs=output/'pairs.npz'
    if pairs.exists():
        with np.load(pairs)as z:
            if not np.array_equal(z['0_target'],target*16383):raise ValueError('Saved fit target differs; use a new work folder')
            if any(k not in z or not np.array_equal(z[k],v)for k,v in data.items()):
                raise ValueError('Saved C2 source cohort differs; use a new work folder')
    else:np.savez_compressed(pairs,**data,**{'0_target':target*16383})
    if (output/'complete.json').exists():
        report=json.loads((output/'complete.json').read_text(encoding='utf-8'))
        if report['budget']!={'evaluations':evaluations,'starts':starts}:raise ValueError('Saved fitting budget differs')
        return json.loads((output/'parameters.json').read_text(encoding='utf-8')),(output/'grid.payload').read_bytes(),report
    factory=context();ctx=ParameterContext(factory)
    capture=output/'context';capture.mkdir(exist_ok=True)
    save(capture/'report.json',dict(model='ILCE-7CM2',camera_io=False))
    RuntimeColor.from_capture=classmethod(lambda cls,folder,index=0:factory)
    import fit_anchor_native as fn
    profile=json.loads((ROOT/'formal_profile.json').read_text(encoding='utf-8'))
    options=profile['options']['search_options'].copy();options['starts']=starts
    # Original C2 gamma builder remains in use, with illegal candidates rejected.
    if not (output/'fit/recipe.json').exists():
        import gamma_admissibility
        gamma_admissibility.install(output)
        import native_checkpoints
        native_checkpoints.install(output)
        argv=sys.argv
        sys.argv=['c2-r5-fit',str(pairs),'--capture',str(capture),'--context','4','--gamut','0',
            '--output',str(output/'fit'),'--evaluations',str(evaluations),'--pc-compensation',
            '--search-options',json.dumps(options),'--pc-options',json.dumps(dict(curve_mode='tone-tint',grid_enabled=True,response=IDENTITY)),
            '--target-description','C2 source-bound target; latest upstream Hybrid; no device I/O']
        try:fn.main()
        finally:sys.argv=argv
    recipe=json.loads((output/'fit/recipe.json').read_text(encoding='utf-8'))
    p=recipe['parameters']
    params=dict(matrix_payload=bytes.fromhex(p['matrix_780f_hex']),cc1=np.asarray(p['cc1_direct_raw']),gamma_y=np.asarray(p['gamma_7806_y']))
    def render(q):return center_mean(render_native(ctx.build(**q),data['input']))/16383
    base=render(params)
    split=data['split'];train_rows=np.flatnonzero((split=='train')&(data['anchor_index']<0)&(data['sector16_index']<0))
    train,_,_,weights=fn.training_plan(split,data['anchor_index'],recipe['fitting']['group_total_weights'],data['sector16_index'],data['baseline_tonal_index'],train_rows,data['sample_kind'],options)
    valid=np.flatnonzero(split=='valid')
    from grid_distillation import fit_target
    from continuity_grid import constrain
    from multiround import cpu_cost
    tracker=TrainingProgress(output/'grid-progress.json',5)
    if (output/'grid-parent.payload').exists():
        grid=unpack((output/'grid-parent.payload').read_bytes());grid_rounds=json.loads((output/'grid-rounds.json').read_text(encoding='utf-8'))
    else:
        grid,audit=fit_target(base[train],target[train],weights,IDENTITY,progress=tracker.update,training_penalties=False)
        current=grid.copy();best=grid.copy();score=cpu_cost(model.predict_cpu(base[valid],grid),target[valid]);grid_rounds=[dict(round=1,validation=score,fit=audit)]
        for index in range(2,6):
            before=cpu_cost(model.predict_cpu(base[train],current),target[train],weights)
            proposal,audit=constrain(current,base[train],target[train],weights,IDENTITY,0,None,tracker.update,evaluations=160,device=device,training_penalties=False)
            proposal=unpack(pack(proposal));after=cpu_cost(model.predict_cpu(base[train],proposal),target[train],weights)
            changed=pack(proposal)!=pack(current)
            if after<=before:current=proposal
            value=cpu_cost(model.predict_cpu(base[valid],current),target[valid])
            grid_rounds.append(dict(round=index,accepted=bool(after<=before),validation=value,fit=audit))
            if value<score:best=current.copy();score=value
            if not changed:break
        grid=best
        (output/'grid-parent.payload').write_bytes(pack(grid));save(output/'grid-rounds.json',grid_rounds)
    from stack_native import FrozenGamma,native_update,fields
    from stack_objective import Scorer,TargetDerivatives,optimize_grid,optimize_rounding
    from hue_direction import HueDirectionBank
    from gpu_tensor import TensorTools
    import torch
    direction=HueDirectionBank(data['design_srgb'],target,split,data['sample_kind'])
    derivative=TargetDerivatives(data['design_srgb'],target,split,data['sample_kind'],.02)
    scorer=Scorer(model,target,train,weights,direction,derivative)
    smooth=fn.SmoothNative(ctx,data['input'][train]);smooth.gamma_shape=FrozenGamma(params['gamma_y'])
    vector=fn.vector_for(ParameterContext(ctx.build(**params)))
    def val(b,g):return cpu_cost(model.predict_cpu(b[valid],g),target[valid])
    current=dict(params=params,vector=vector,base=base,grid=grid,label='new-native-parent',validation=val(base,grid))
    chosen=copy.deepcopy(current);rounds=[]
    # Compare old installed coefficients on this SAME response and target. The
    # old candidate is a conservative option, not a claim it was newly fitted.
    if previous is not None:
        q=previous['edit_native']['fitted']
        oldparams=dict(matrix_payload=bytes.fromhex(q['matrix_780f_hex']),cc1=np.asarray(q['cc1_direct_raw']),gamma_y=np.asarray(q['gamma_7806_y']))
        import base64
        oldgrid=unpack(base64.b64decode(previous['table_base64']));oldbase=render(oldparams)
        oldscore=val(oldbase,oldgrid)
        if oldscore<chosen['validation']:
            chosen=dict(params=oldparams,base=oldbase,grid=oldgrid,label='previous-conservative-parent',validation=oldscore)
            current=copy.deepcopy(chosen)
            current['vector']=fn.vector_for(ParameterContext(ctx.build(**oldparams)))
            smooth.gamma_shape=FrozenGamma(oldparams['gamma_y'])
            chosen=copy.deepcopy(current)
    tools=TensorTools(device,torch.float32);settings=profile['settings']
    stack_started_from=current['label']
    tracker=TrainingProgress(output/'stack-progress.json',3)
    for index in range(1,4):
        tracker.update(round=index,stage='C2 Hybrid native/grid/integer stack',state='running')
        vector,base,changed,audit=native_update(tools,smooth,current['vector'],current['base'],current['grid'],scorer,render,tracker.update,settings['native_evaluations'])
        params=current['params']if changed is None else changed
        grid,continuous,ga=optimize_grid(tools,base,current['grid'],scorer,tracker.update,settings['grid_evaluations'])
        grid,ra=optimize_rounding(tools,base,grid,continuous,scorer,tracker.update,settings['rounding_steps'],settings['block_budget'])
        value=val(base,grid);current=dict(params=params,vector=vector,base=base,grid=grid,label='stack-'+str(index),validation=value)
        if value<chosen['validation']:chosen=copy.deepcopy(current)
        rounds.append(dict(round=index,native=audit,grid=ga,rounding=ra,validation=value,selected=chosen['label']))
        save(output/('stack-round-%d.json'%index),rounds[-1])
    prediction=model.predict_cpu(chosen['base'],chosen['grid'])
    report=dict(upstream_commit=COMMIT,algorithm='C2 Hybrid native12-grid5-stack3',execution_device=device,camera_io=False,
        selected=chosen['label'],selected_validation=chosen['validation'],stack_started_from=stack_started_from,budget=dict(evaluations=evaluations,starts=starts),
        grid_rounds=grid_rounds,stack_rounds=rounds,
        metrics={s:metrics(target[split==s],prediction[split==s])for s in ('train','valid','test')},
        physical_color_accuracy_verified=False,historical_test_previously_observed=True)
    native=fields(chosen['params']);save(output/'parameters.json',native)
    (output/'grid.payload').write_bytes(pack(chosen['grid']))
    np.savez_compressed(output/'prediction.npz',prediction=prediction,target=target,baseline=chosen['base'],split=split)
    save(output/'complete.json',report)
    return native,pack(chosen['grid']),report
