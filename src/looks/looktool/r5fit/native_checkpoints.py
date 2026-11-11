"""Resume solved native stages using frozen numerical inputs, without digests."""
from pathlib import Path
import json
import os
import time
import numpy as np

def jsonable(value):
    if isinstance(value,np.ndarray):return value.tolist()
    if isinstance(value,np.generic):return value.item()
    if isinstance(value,dict):return {k:jsonable(v)for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [jsonable(v)for v in value]
    if value is None or isinstance(value,(str,int,float,bool)):return value
    raise TypeError('Not a checkpoint scalar')

def install(folder,progress_class=None):
    if progress_class is None:
        from training_progress import TrainingProgress
        progress_class=TrainingProgress
    folder=Path(folder)/'native-checkpoints';folder.mkdir(exist_ok=True)
    original=getattr(progress_class.solve,'_c2_original_solver',progress_class.solve)
    def solve(self,solver,stage,*args,**kwargs):
        self._c2_step=getattr(self,'_c2_step',0)+1
        prefix=folder/('%s-%03d'%(self.path.stem,self._c2_step))
        archive=prefix.with_suffix('.npz');record=prefix.with_suffix('.json')
        initial=np.asarray(args[1]);residual=np.asarray(args[0](initial))
        options=jsonable({k:v for k,v in kwargs.items()if k!='gpu_objective'and not callable(v)})
        if archive.exists()and record.exists():
            saved=json.loads(record.read_text(encoding='utf-8'))
            with np.load(archive,allow_pickle=False)as z:
                matches=saved['stage']==stage and saved['options']==options and z['initial'].dtype==initial.dtype and z['initial_residual'].dtype==residual.dtype and np.array_equal(z['initial'],initial)and np.array_equal(z['initial_residual'],residual)
            if matches:
                from scipy.optimize import OptimizeResult
                result=OptimizeResult(**saved['result']);result.x=np.asarray(result.x,dtype=saved['x_dtype'])
                self.convergence.append(saved['convergence'])
                self.value.update(saved['progress']);self.update(restored_native_stage=True)
                return result
            prior=folder/'superseded'/str(time.time_ns());prior.mkdir(parents=True)
            os.replace(archive,prior/archive.name);os.replace(record,prior/record.name)
        self.value.pop('restored_native_stage',None)
        result=original(self,solver,stage,*args,**kwargs)
        # The fitter consumes x and scalar convergence fields, never the very
        # large least-squares Jacobian. Keep that out of the checkpoint.
        values={k:jsonable(v)for k,v in dict(result).items()if k not in ('jac','fun','hess_inv')}
        temporary=archive.with_suffix('.npz.tmp')
        with temporary.open('wb')as stream:np.savez_compressed(stream,initial=initial,initial_residual=residual)
        os.replace(temporary,archive)
        value=dict(stage=stage,options=options,x_dtype=np.asarray(result.x).dtype.str,result=values,convergence=jsonable(self.convergence[-1]),progress=jsonable(self.value))
        temporary=record.with_suffix('.json.tmp');temporary.write_text(json.dumps(value,allow_nan=False)+'\n',encoding='utf-8');os.replace(temporary,record)
        return result
    solve._c2_original_solver=original
    progress_class.solve=solve
