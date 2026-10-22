"""Reusable bounded native-photo/correction fitting against a measured model.

Inputs are numerical source/target RGB; no camera or reference-renderer I/O.
Parameter limits stay within the admitted experimental native-photo basis.
"""
import numpy as np
from scipy.optimize import least_squares
from scipy.sparse import block_diag, csr_matrix, eye, hstack, vstack
from . import coupledfit, measuredfit, photomeasure


class Problem:
    def __init__(self, model, source, target, smooth, native_penalty=.001):
        self.model=model;self.source=np.asarray(source);self.target=np.asarray(target)
        self.smooth=smooth
        self.coordinates=model.base.coordinates(self.source)
        self.field=np.clip(self.coordinates,0,1)
        self.ids,self.weights=measuredfit.interpolation(self.field)
        self.basezero=np.clip(model.base.forward(self.coordinates),0,1)
        self.regularizer=block_diag((coupledfit.native_curvature()*np.sqrt(smooth),
            eye(17)*native_penalty),format='csr');self.cache={}

    def evaluate(self, vector):
        if 'vector' not in self.cache or not np.array_equal(vector,self.cache['vector']):
            correction=(vector[:1215].reshape(405,3)[self.ids]*self.weights[...,None]).sum(1)
            at=self.coordinates+correction*self.model.base.scale
            forward=self.model.base.forward(at)
            corrected=self.source+np.clip(forward,0,1)-self.basezero
            point=np.clip(corrected,0,1);j,q=self.model.bases(point);controls=vector[1215:]
            raw=corrected+np.einsum('ndc,d->nc',j,controls)+np.einsum('ndc,d->nc',q,controls**2)
            self.cache=dict(vector=vector.copy(),at=at,forward=forward,corrected=corrected,
                            point=point,j=j,q=q,raw=raw)
        return self.cache

    def residual(self, vector):
        return np.r_[(np.clip(self.evaluate(vector)['raw'],0,1)-self.target).ravel(),self.regularizer@vector]

    def jacobian(self, vector):
        value=self.evaluate(vector);controls=vector[1215:]
        if 'dj' not in value:
            a=np.stack([pair[0].derivative(value['point']) for pair in self.model.models],axis=1)
            b=np.stack([pair[1].derivative(value['point']) for pair in self.model.models],axis=1)
            value.update(dj=(b-a)/2,dq=(b+a)/2)
        native_input=np.einsum('ndio,d->nio',value['dj'],controls)+np.einsum('ndio,d->nio',value['dq'],controls**2)
        native_input*=((value['corrected']>0)&(value['corrected']<1))[:,:,None]
        native_input+=np.eye(3)[None]
        derivative=self.model.base.forward.derivative(value['at'])
        derivative*=((value['forward']>0)&(value['forward']<1))[:,None,:]
        derivative*=self.model.base.scale[None,:,None]
        derivative=np.einsum('nai,nio->nao',derivative,native_input)
        unclipped=(value['raw']>0)&(value['raw']<1)
        derivative*=unclipped[:,None,:]
        native_j=(value['j']+2*value['q']*controls[None,:,None]).transpose(0,2,1)
        native_j*=unclipped[:,:,None]
        return vstack((hstack((measuredfit.design(self.field,derivative),
            csr_matrix(native_j.reshape(-1,17))),format='csr'),self.regularizer),format='csr')

    def prediction(self, vector, integer=True):
        if integer:
            vector=np.r_[np.rint(vector[:1215]),photomeasure.quantized(vector[1215:])]
        return np.clip(self.evaluate(vector)['raw'],0,1)


def solve(problem, initial=None, *, max_evaluations=100, loss='linear'):
    if initial is None:
        adjusted=np.clip(problem.target-problem.source+problem.basezero,0,1)
        seed,_=coupledfit.solve(problem.model.base,problem.coordinates,adjusted,smooth=problem.smooth)
        initial=np.r_[seed.ravel(),np.zeros(17)]
    result=least_squares(problem.residual,initial,jac=problem.jacobian,
        bounds=(np.r_[np.full(1215,-64.),np.full(17,-.5)],np.r_[np.full(1215,63.),np.full(17,.5)]),
        method='trf',tr_solver='lsmr',max_nfev=max_evaluations,ftol=1e-5,xtol=1e-5,gtol=1e-6,
        loss=loss,f_scale=.01)
    def objective(vector):
        residual=problem.residual(vector)
        if loss=='linear':return float(np.dot(residual,residual))
        if loss=='soft_l1':return float((2*.01**2*(np.sqrt(1+(residual/.01)**2)-1)).sum())
        raise ValueError('Unsupported numerical fitting loss')
    before=objective(initial);after=objective(result.x)
    vector=result.x if after<=before else initial.copy()
    return vector,dict(optimizer_converged=bool(result.success),evaluations=int(result.nfev),
        objective_kind=loss,objective_before=before,objective_after=min(before,after),
        integer_metrics=coupledfit.metrics(problem.prediction(vector),problem.target))


def table_seed(problem, max_evaluations=80, return_report=False):
    """Optimize the nested table-only problem before adding native controls."""
    adjusted=np.clip(problem.target-problem.source+problem.basezero,0,1)
    seed,seed_report=coupledfit.solve(problem.model.base,problem.coordinates,adjusted,smooth=problem.smooth)
    cache={}
    def value(table):
        if 'table' not in cache or not np.array_equal(table,cache['table']):
            correction=(table.reshape(405,3)[problem.ids]*problem.weights[...,None]).sum(1)
            at=problem.coordinates+correction*problem.model.base.scale
            forward=problem.model.base.forward(at)
            corrected=problem.source+np.clip(forward,0,1)-problem.basezero
            cache.update(table=table.copy(),at=at,forward=forward,corrected=corrected)
        return cache
    regularizer=problem.regularizer[:-17,:1215]
    def residual(table):
        current=value(table)
        return np.r_[(np.clip(current['corrected'],0,1)-problem.target).ravel(),regularizer@table]
    def jacobian(table):
        current=value(table)
        derivative=problem.model.base.forward.derivative(current['at'])
        derivative*=((current['forward']>0)&(current['forward']<1))[:,None,:]
        derivative*=problem.model.base.scale[None,:,None]
        derivative*=((current['corrected']>0)&(current['corrected']<1))[:,None,:]
        return vstack((measuredfit.design(problem.field,derivative),regularizer),format='csr')
    result=least_squares(residual,seed.ravel(),jac=jacobian,bounds=(-64,63),method='trf',
        tr_solver='lsmr',max_nfev=max_evaluations,ftol=1e-5,xtol=1e-5,gtol=1e-6)
    before=residual(seed.ravel());after=residual(result.x)
    improved=np.isfinite(after).all() and np.dot(after,after)<=np.dot(before,before)
    table=result.x if improved else seed.ravel()
    vector=np.r_[table,np.zeros(17)]
    report=dict(seed=seed_report,optimizer_converged=bool(result.success),
        evaluations=int(result.nfev),retained_refinement=bool(improved))
    return (vector,report) if return_report else vector
