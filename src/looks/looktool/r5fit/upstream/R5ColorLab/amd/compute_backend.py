"""Exact native integer acceptance on CPU; floating/grid fits run on ROCm."""
from concurrent.futures import ThreadPoolExecutor
import numpy as np
WORKERS=10


def render_native(model,inputs):
    values=np.asarray(inputs)
    if len(values)<2048:return model.color_only(values)
    with ThreadPoolExecutor(max_workers=WORKERS,thread_name_prefix='r5-native') as pool:
        return np.concatenate(list(pool.map(model.color_only,np.array_split(values,WORKERS))))
