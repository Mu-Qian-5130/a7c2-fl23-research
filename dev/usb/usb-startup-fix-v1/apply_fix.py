"""Offline host-file update only. No camera library imports or device access."""
import ast
import base64
import hashlib
import os
from pathlib import Path
import tempfile

# Filled from the reviewed candidate by the single-file builder.
ORIGINAL_SHA = '1c10d080dd5b67bb0f78eaefec2328deefc51a1b0673ed141eaa64a9ec74add4'
PATCHED_SHA = '__PATCHED_SHA__'
PATCHED_B64 = '__PATCHED_B64__'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def apply_fix(base):
    base = Path(base).resolve()
    target = base / 'transport.py'
    backup = base / 'transport.py.before-usb-startup-fix-v1.bak'
    if not (base / 'app.py').is_file() or not (base / 'vendor/pmca/usb/sony.py').is_file():
        raise RuntimeError('Put this file beside Start.cmd in the original preview package.')
    original = target.read_bytes()
    if sha(original) == PATCHED_SHA:
        print('USB startup fix is already installed. No files were changed.')
        return
    if sha(original) != ORIGINAL_SHA:
        raise RuntimeError('Unknown transport.py version. Stopped without changing it.')
    patched = base64.b64decode(PATCHED_B64, validate=True)
    if sha(patched) != PATCHED_SHA:
        raise RuntimeError('Embedded update failed its integrity check.')
    ast.parse(patched.decode('utf-8'))
    if backup.exists():
        if backup.read_bytes() != original:
            raise RuntimeError('Existing backup differs. Stopped without changing files.')
    else:
        with backup.open('xb') as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
    if backup.read_bytes() != original:
        raise RuntimeError('Original-file backup verification failed.')
    stage = None
    try:
        with tempfile.NamedTemporaryFile(dir=base, prefix='.usb-startup-', suffix='.tmp', delete=False) as stream:
            stage = Path(stream.name)
            stream.write(patched)
            stream.flush()
            os.fsync(stream.fileno())
        if sha(stage.read_bytes()) != PATCHED_SHA:
            raise RuntimeError('Staged update verification failed.')
        if target.read_bytes() != original:
            raise RuntimeError('transport.py changed while updating. Stopped.')
        os.replace(stage, target)
        if sha(target.read_bytes()) != PATCHED_SHA:
            raise RuntimeError('Final update verification failed. Keep the original backup.')
    finally:
        if stage is not None and stage.exists():
            stage.unlink()
    print('USB startup fix installed and verified.')
    print('Original transport.py was preserved as transport.py.before-usb-startup-fix-v1.bak')
    print('No camera connection, firmware write, or backup-folder change was performed.')
    print('Reopen Start.cmd and use new empty workspace and backup folders for step 1.')


def main():
    print('A7C II preview 0.1.0 - initial USB startup fix v1')
    print('Close the preview tool before applying this update.')
    try:
        apply_fix(Path(__file__).resolve().parent)
    except Exception as exc:
        print('Update stopped: ' + str(exc))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
