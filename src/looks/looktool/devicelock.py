"""Nonblocking OS lock, automatically released if a process terminates."""
import os
from pathlib import Path

class DeviceLock:
    def __init__(self,path=None):self.path=Path(path) if path is not None else Path.home()/'.a7c2-lut/device.lock'
    def __enter__(self):
        path=self.path;path.parent.mkdir(parents=True,exist_ok=True)
        # Windows byte-range locks also deny reads of the locked byte. Lock
        # the range directly (including beyond EOF); do not read it first.
        self.stream=path.open('a+b');self.stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.stream.close();raise ValueError('Another LUT process owns the camera; close it before continuing')
        return self
    def __exit__(self,*args):
        if os.name=='nt':
            import msvcrt
            self.stream.seek(0);msvcrt.locking(self.stream.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(self.stream.fileno(),fcntl.LOCK_UN)
        self.stream.close()

def serialized(method):
    from functools import wraps
    @wraps(method)
    def run(self,*args,**kwargs):
        with DeviceLock(self.root.parent/('.'+self.root.name+'.lock')):return method(self,*args,**kwargs)
    return run
