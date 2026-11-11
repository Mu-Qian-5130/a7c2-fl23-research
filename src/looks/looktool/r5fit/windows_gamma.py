"""Windows Edit's observed float32 weighted-sum Gamma expansion.

Independent arithmetic transcription of the local x64 builder. The Mac model
uses a different interpolation evaluation order; their one-code differences
must not be removed by relaxing an exact comparison.
"""


def expand(axis,values,contrast=None):
    import numpy as np
    axis=np.asarray(axis,dtype=np.int64);values=np.asarray(values,dtype=np.int64)
    if axis.shape!=values.shape or axis.ndim!=1 or not 2<=len(axis)<=128:
        raise ValueError('Expected matched native axis/value vectors')
    if axis[0]!=0 or values[0]!=0 or np.any(np.diff(axis)<=0) or np.any(values<0):
        raise ValueError('Expected nonnegative, increasing zero-origin axis')
    sample=np.arange(1,32768,dtype=np.int64)*128
    # Native keeps its last visited right node as the next left node. If a
    # synthetic axis has intervals narrower than 128, multiple knots can be
    # skipped in one sampling step; generic np.interp would use another left.
    left=np.empty(len(sample),int);right=np.empty(len(sample),int)
    previous=current=0
    for j,point in enumerate(sample):
        if point>axis[current]:
            found=int(np.searchsorted(axis,point,side='right'))
            if found>=len(axis):previous=current=len(axis)-1
            else:previous,current=current,found
        left[j],right[j]=previous,current
    width=axis[right]-axis[left]
    weight=(axis[right]-sample).astype(np.float32)/np.where(width==0,1,width).astype(np.float32)
    a=values[left].astype(np.float32)*weight
    b=values[right].astype(np.float32)*(np.float32(1)-weight)
    interpolated=np.where(width==0,values[left],np.trunc((a+b).astype(np.float32))).astype(np.int64)
    quarter=interpolated>>2
    if contrast is not None:
        table=np.asarray(contrast)
        if table.shape not in ((1024,),(1025,)) or not np.issubdtype(table.dtype,np.integer):
            raise ValueError('Expected 1024/1025 contrast integers')
        index=quarter>>6
        lo=np.minimum(index,1023);hi=np.minimum(index+1,1023)
        fraction=(quarter-(index<<6)).astype(np.float32)*np.float32(1/64)
        a=table[lo].astype(np.float32)*(np.float32(1)-fraction)
        b=table[hi].astype(np.float32)*fraction
        quarter=np.trunc((a+b).astype(np.float32)).astype(np.int64)
    positive=(quarter>>2).astype('<u2')
    result=np.zeros(65536,dtype='<u2');result[32769:]=positive
    result[:32768]=((-result[32768:].astype(np.int64)[::-1])&65535).astype('<u2')
    return result
