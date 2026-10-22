"""Portable numerical response snapshot for offline look compilation.

No photographs, executable firmware, USB code or Python pickle is loaded.
The snapshot is a measured approximation scoped to its acquisition WB/range.
"""
import json
import numpy as np
from scipy.interpolate import RBFInterpolator
from . import coupledfit

SCHEMA='a7c2-measured-virtual-response/1'


class TPS:
    def __init__(self, arrays, prefix):
        self.x,self.a,self.b,self.shift,self.scale=[np.asarray(arrays[prefix+'_'+key])
            for key in ('x','a','b','shift','scale')]

    def __call__(self, x):
        x=np.asarray(x);d=x[:,None]-self.x[None]
        r2=(d*d).sum(2);kernel=.5*r2*np.log(np.maximum(r2,1e-300))
        return kernel@self.a+np.c_[np.ones(len(x)),(x-self.shift)/self.scale]@self.b

    def derivative(self, x):
        d=np.asarray(x)[:,None]-self.x[None];r2=(d*d).sum(2)
        return np.einsum('nmi,mo->nio',d*(np.log(np.maximum(r2,1e-300))+1)[:,:,None],self.a)+self.b[1:]/self.scale[:,None]


class Base:
    def __init__(self, arrays):
        self.knots=arrays['base_knots'];self.inverse=arrays['base_inverse']
        self.scale=arrays['base_scale'];self.forward=TPS(arrays,'base_forward')

    def coordinates(self, rgb):return coupledfit.spline_design(rgb,self.knots)@self.inverse


class Response:
    def __init__(self, path):
        with np.load(path,allow_pickle=False) as file:
            self.arrays={key:file[key] for key in file.files}
        self.metadata=json.loads(str(self.arrays['metadata']))
        if self.metadata.get('schema')!=SCHEMA:raise ValueError('Unknown measured-response snapshot')
        self.base=Base(self.arrays)
        self.models=[(TPS(self.arrays,f'native_{i}_minus'),TPS(self.arrays,f'native_{i}_plus')) for i in range(17)]
        self.raw_forward=RBFInterpolator(self.arrays['raw_training_x'],self.arrays['raw_training_y'],
            neighbors=64,kernel='thin_plate_spline',smoothing=self.metadata['raw_smoothing'])
        self.zero_bias=TPS(self.arrays,'zero_bias')

    def bases(self, rgb):
        minus=np.stack([pair[0](rgb) for pair in self.models],axis=1)
        plus=np.stack([pair[1](rgb) for pair in self.models],axis=1)
        return (plus-minus)/2,(plus+minus)/2

    def raw_to_zero(self, rgb):
        feature=np.maximum(rgb,1e-6)**self.metadata['raw_power']
        return np.clip(self.raw_forward(feature)+self.zero_bias(feature),0,1)

    def virtual_samples(self, extra=256, seed=7219):
        from scipy.spatial import cKDTree
        raw=self.arrays['anchor_raw'];source=self.arrays['anchor_source']
        rng=np.random.default_rng(seed)
        valid=(raw.min(1)>1e-5)&(source.min(1)>.02)&(source.max(1)<.98)
        pool=np.where(valid)[0];features=np.sqrt(np.maximum(raw[pool],0))
        # Interpolate between measured neighbors in sensor space. An arbitrary
        # full RGB cube would extrapolate far outside the calibrated gamut.
        neighbors=cKDTree(features).query(features,k=min(8,len(pool)))[1]
        starts=rng.integers(len(pool),size=extra)
        ends=neighbors[starts,rng.integers(1,neighbors.shape[1],size=extra)]
        weight=rng.uniform(.15,.85,(extra,1))
        generated=raw[pool[starts]]*(1-weight)+raw[pool[ends]]*weight
        return np.r_[raw,generated],np.r_[source,self.raw_to_zero(generated)]


def snapshot(path, model, raw_forward, raw_metadata, bank, tps_class):
    """Explicit array export; no source-image or camera identity paths stored."""
    raw=np.asarray(raw_forward['RAW'])[0];source=model.native_zero[0]
    metadata=dict(schema=SCHEMA,model='ILCE-7CM2',firmware='2.01',
        raw_power=.5,raw_smoothing=.001,WB=raw_metadata['WB'][:3],
        black=raw_metadata['black'][0],white=raw_metadata['white'],
        native_controls=17,native_control_bound=.5,correction_bytes=1215,
        physical_scope='One measured chart, ISO800, 5000K; interpolation within measured input colors',
        actual_camera_color_accuracy_verified=False)
    arrays=dict(metadata=np.asarray(json.dumps(metadata)),base_knots=model.base.knots,
        base_inverse=model.base.inverse,base_scale=model.base.scale,
        anchor_raw=raw,anchor_source=source,baseline_bank=np.frombuffer(bank,dtype=np.uint8),
        raw_training_x=raw_forward['training_x'],raw_training_y=raw_forward['training_y'])
    def add(prefix, tps):
        arrays.update({prefix+'_'+key:getattr(tps,key) for key in ('x','a','b','shift','scale')})
    add('base_forward',model.base.forward)
    for i,pair in enumerate(model.models):
        for sign,tps in zip(('minus','plus'),pair):add(f'native_{i}_{sign}',tps)
    learned=RBFInterpolator(arrays['raw_training_x'],arrays['raw_training_y'],neighbors=64,
                            kernel='thin_plate_spline',smoothing=.001)
    feature=np.maximum(raw,1e-6)**.5
    add('zero_bias',tps_class(feature,source-learned(feature),smoothing=.001))
    with open(path,'xb') as stream:np.savez_compressed(stream,**arrays)
    return metadata
