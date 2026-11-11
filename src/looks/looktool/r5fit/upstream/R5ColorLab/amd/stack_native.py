from gpu_runtime import resolve_device, available, synchronize, empty_cache

import numpy as np
from stack_objective import data_loss,acceptable

class FrozenGamma:
    def __init__(self,gamma):self.gamma=np.array(gamma,copy=True)
    def curve(self,tail):return self.gamma/16
    def integer_curve(self,tail):return self.gamma.copy()
    def tensor_curve(self,torch,tail):return torch.as_tensor(self.gamma.copy(),device=tail.device,dtype=tail.dtype)/16

def native_update(tools,smooth,vector,base,grid,scorer,render_native,progress,evaluations=120):
    from scipy.optimize import minimize
    from apple_gpu import SmoothGPU
    from gpu_color import paired_tensor
    gpu=SmoothGPU(smooth,device=tools.device,dtype=tools.dtype)
    lookup={int(row):i for i,row in enumerate(scorer.train)}
    did=tools.tensor([lookup[int(i)]for i in scorer.direction.source_indices],True)
    sid=tools.tensor([lookup[int(i)]for i in scorer.derivatives.source_indices],True)
    desired=tools.tensor(scorer.target[scorer.train]);mass=tools.tensor(scorer.weights/scorer.weights.sum())
    fixed=tools.tensor(grid);tail=tools.tensor(vector[104:])
    calls=0
    def loss(v):
        rgb=gpu.render(v)/16383
        p=paired_tensor(tools,rgb,fixed,scorer.model.identity)
        return (data_loss(tools,p,desired,mass)
            +scorer.direction.tensor_loss(tools,p[did],30)
            +scorer.derivatives.tensor_loss(tools,p[sid]))*255**2
    # Independent CPU64 gate uses the same smooth native relaxation, not an
    # assumption that it is identical to the true integer native renderer.
    smooth_rgb=smooth.render(vector)/16383
    predicted=scorer.model.predict_cpu(smooth_rgb,grid)
    from multiround import cpu_cost
    expected=cpu_cost(predicted,scorer.target[scorer.train],scorer.weights)
    expected+=scorer.direction.cost(predicted[did.cpu().numpy()],30)
    expected+=scorer.derivatives.cpu_cost(predicted[sid.cpu().numpy()])
    actual=float(loss(tools.tensor(vector)).detach().cpu())
    if abs(actual-expected)>max(.02,abs(expected)*3e-3):
        raise ValueError(f'Stack native GPU/CPU smooth loss mismatch {actual} vs {expected}')
    def fg(v):
        nonlocal calls
        color=tools.tensor(v).requires_grad_(True)
        complete=tools.torch.cat([color,tail])
        value=loss(complete);value.backward();calls+=1
        f=float(value.detach().cpu());g=color.grad.detach().cpu().numpy().astype(float)
        if not np.isfinite(f) or not np.isfinite(g).all():raise ValueError('Nonfinite native stack gradient')
        if calls%10==0:progress(stage='叠加：固定整数网格优化CC1/block13，Gamma冻结',evaluations=calls,max_evaluations=evaluations)
        return f,g
    seed=vector.copy()
    radius=np.r_[np.full(8,.08),np.full(96,.12)]
    lower=np.maximum(seed[:104]-radius,np.r_[np.full(4,-.999),np.full(4,.05),np.full(96,-6)])
    upper=np.minimum(seed[:104]+radius,np.r_[np.full(4,.996),np.full(4,3.98),np.full(96,6)])
    fitted=minimize(fg,np.clip(seed[:104],lower,upper),jac=True,method='L-BFGS-B',bounds=list(zip(lower,upper)),
        options=dict(maxfun=evaluations,maxiter=evaluations,maxls=20,ftol=1e-10,gtol=1e-6))
    best,best_base=seed,base;before=score=scorer.score(base,grid);selected_params=None
    attempts=[]
    for alpha in (1.,.5,.25):
        trial=seed.copy();trial[:104]+=alpha*(fitted.x-seed[:104])
        params=smooth.params(trial)
        if not np.array_equal(params['gamma_y'],smooth.gamma_shape.gamma):raise ValueError('Frozen Gamma changed')
        params['cc1'][4:]=2*np.minimum(1023,(params['cc1'][4:]+1)//2)
        candidate_base=render_native(params)
        proposal=scorer.score(candidate_base,grid)
        attempts.append(dict(alpha=alpha,score=proposal))
        if acceptable(score,proposal):best,best_base,score,selected_params=trial,candidate_base,proposal,params
    return best,best_base,selected_params,dict(before=before,after=score,calls=calls,attempts=attempts,
        solver_message=str(fitted.message),gamma_frozen=True,coordinate_and_response_gradients=True,
        cpu64_smooth_gate=dict(cpu=expected,gpu=actual),integer_native_acceptance=True)

def fields(params):
    return dict(matrix_780f_hex=params['matrix_payload'].hex(),
        cc1_direct_raw=params['cc1'].tolist(),gamma_7806_y=params['gamma_y'].tolist())
