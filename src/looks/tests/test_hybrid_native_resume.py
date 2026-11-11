"""Completed numerical stages survive interruption without stale reuse."""
from pathlib import Path
import numpy as np
from scipy.optimize import OptimizeResult
from looktool.r5fit.native_checkpoints import install

def progress_type():
    class Progress:
        calls=0
        def __init__(self):self.path=Path('training_progress.json');self.value={'round':0};self.convergence=[]
        def update(self,**kw):self.value.update(kw)
        def solve(self,solver,stage,function,initial,**options):
            type(self).calls+=1;self.value['round']+=1
            self.convergence.append(dict(stage=stage,calls=1))
            return OptimizeResult(x=np.asarray(initial,dtype=np.float32)+1,nfev=1,cost=2.,optimality=0.,status=1,success=True,message='fixture')
    return Progress

def test_restart_reuses_solved_stage_and_preserves_dtype(tmp_path):
    progress=progress_type();install(tmp_path,progress)
    first=progress().solve(None,'stage',lambda x:x*x,np.array([.5,1.]),bounds=(np.zeros(2),np.ones(2)*3))
    second_progress=progress();second=second_progress.solve(None,'stage',lambda x:x*x,np.array([.5,1.]),bounds=(np.zeros(2),np.ones(2)*3))
    np.testing.assert_array_equal(first.x,second.x)
    assert second.x.dtype==np.float32 and progress.calls==1
    assert second_progress.value['round']==1 and second_progress.value['restored_native_stage']

def test_changed_residual_recomputes_and_preserves_prior_checkpoint(tmp_path):
    progress=progress_type();install(tmp_path,progress)
    progress().solve(None,'stage',lambda x:x,np.array([.5,1.]))
    progress().solve(None,'stage',lambda x:2*x,np.array([.5,1.]))
    assert progress.calls==2 and len(list((tmp_path/'native-checkpoints/superseded').glob('*/training_progress-001.npz')))==1

def test_changed_solver_budget_is_not_reused(tmp_path):
    progress=progress_type();install(tmp_path,progress)
    for budget in [2,4]:progress().solve(None,'stage',lambda x:x,np.array([.5,1.]),max_nfev=budget)
    assert progress.calls==2

def test_incomplete_checkpoint_is_not_a_completed_stage(tmp_path):
    progress=progress_type();install(tmp_path,progress)
    folder=tmp_path/'native-checkpoints'
    with (folder/'training_progress-001.npz').open('wb')as f:np.savez(f,initial=[.5,1.],initial_residual=[.5,1.])
    progress().solve(None,'stage',lambda x:x,np.array([.5,1.]))
    assert progress.calls==1 and (folder/'training_progress-001.json').exists()
