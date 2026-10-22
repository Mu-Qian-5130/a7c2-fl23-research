"""Load the bundled source layout, retaining native worker asset paths."""
from pathlib import Path
import runpy
import sys
import os
import traceback

try:
    runpy.run_path(str(Path(sys._MEIPASS) / 'desktop.py'), run_name='__main__')
except Exception:
    folder = (Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'A7C2Tools'
              if sys.platform == 'win32' else Path.home() / 'Library/Logs/A7C2Tools')
    folder.mkdir(parents=True, exist_ok=True)
    detail=traceback.format_exc()
    (folder / 'startup-error.log').write_text(detail, encoding='utf-8')
    if sys.stderr is not None:print(detail,file=sys.stderr,flush=True)
    if any(flag in sys.argv for flag in ('--offline-self-test','--smoke-test','--worker','--privileged-worker')):
        raise SystemExit(2)
    raise
