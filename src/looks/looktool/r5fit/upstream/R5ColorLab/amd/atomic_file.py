"""Atomic metadata publication with bounded Windows sharing-lock retries."""
from pathlib import Path
import os
import time
import uuid


def write_bytes(path, data, *, allow_skip=False, timeout=2.):
    path=Path(path)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.pending')
    try:
        temporary.write_bytes(data)
        deadline=time.monotonic()+timeout
        while True:
            try:
                os.replace(temporary,path)
                return True
            except PermissionError:
                # A Windows reader lacking FILE_SHARE_DELETE can temporarily
                # prevent rename even when it permits reads and writes.
                if time.monotonic()>=deadline:
                    if allow_skip:
                        # Progress is observational. Retain the previous
                        # snapshot; a later callback will publish fresh data.
                        return False
                    raise
                time.sleep(.01)
    finally:
        try:temporary.unlink(missing_ok=True)
        except OSError:pass


def write_text(path, text, **kwargs):
    return write_bytes(path,text.encode('utf-8'),**kwargs)
