import numpy as np
def unpack_plane(buf,width,rows,pitch):
    """12-bit little-endian packed, 6 bytes per 4 samples (firmware accessor 0x31a64)."""
    a=np.frombuffer(buf,dtype=np.uint8,count=rows*pitch).reshape(rows,pitch)
    n=width//4
    g=a[:,:6*n].reshape(rows,n,6).astype(np.uint16)
    o=np.zeros((rows,width),np.uint16)
    o[:,0::4]=g[...,0]|((g[...,1]&15)<<8)
    o[:,1::4]=(g[...,1]>>4)|(g[...,2]<<4)
    o[:,2::4]=g[...,3]|((g[...,4]&15)<<8)
    o[:,3::4]=(g[...,4]>>4)|(g[...,5]<<4)
    return o
