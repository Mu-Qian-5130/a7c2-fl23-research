"""Explicit macOS media unmount requested from the connection page."""
from pathlib import Path
import subprocess
import sys

def unmount_camera_volume(volume):
    if sys.platform!='darwin' or not str(volume).startswith('/Volumes/'):
        raise ValueError('Select the mounted camera volume under /Volumes')
    path=Path(volume)
    if not (path/'DCIM').is_dir():
        raise ValueError('Selected volume does not contain a camera DCIM directory')
    done=subprocess.run(['/usr/sbin/diskutil','unmount',str(path)],capture_output=True,text=True)
    print(done.stdout);print(done.stderr,file=sys.stderr)
    if done.returncode:raise RuntimeError('macOS could not unmount the selected camera volume')
    return {'unmounted':str(path),'camera_firmware_written':False}
