"""Windows Edit AVX AreaComp bulk arithmetic, observed at RVA 0x39977d.

The vector branch separately rounds products and sums to float32. Its final
sum of both corrections precedes adding the encoded chroma sample. This is
distinct from the scalar/Mac branch's promoted double accumulation.
"""
import numpy as np


def area_comp(pixels,controls):
    a=np.asarray(pixels)
    if (a.ndim!=2 or a.shape[1]!=3 or np.any(~np.isfinite(a))
            or np.any(a!=np.trunc(a)) or np.any(a<0) or np.any(a>65535)):
        raise ValueError('Expected integer encoded YCC triples')
    if len(controls)!=65 or controls[64]not in (0,1):
        raise ValueError('Expected captured AreaComp controls')
    c=np.frombuffer(controls,dtype='<f4',count=16)
    if not np.isfinite(c).all():raise ValueError('Nonfinite AreaComp controls')
    cr=a[:,1].astype(np.float32)-np.float32(32768)
    cb=a[:,2].astype(np.float32)-np.float32(32768)
    x,y=c[0]+cr,c[1]+cb
    u=np.minimum(np.maximum(y*c[6]+x*c[4],0),np.maximum(c[7]*y+c[5]*x,0))
    x,y=c[2]+cr,c[3]+cb
    v=np.minimum(np.maximum(y*c[10]+x*c[8],0),np.maximum(c[11]*y+c[9]*x,0))
    if controls[64]:u=np.minimum(u,v);v=np.zeros_like(u)
    out=a.astype('<u2').copy()
    for channel,k in ((1,12),(2,13)):
        correction=(u*c[k]+v*c[k+2]).astype(np.float32)
        value=a[:,channel].astype(np.float32)+correction
        # VCVTPS2DQ uses the default nearest-even MXCSR rounding, unlike
        # the scalar tail's CVTTSD2SI truncation.
        out[:,channel]=(np.rint(value).astype(np.int64)&65535).astype('<u2')
    return out
