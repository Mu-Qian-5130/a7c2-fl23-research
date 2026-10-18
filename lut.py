"""Portable LUT/DCP CLI. Offline only; no camera connections or automatic pip."""
import argparse
import importlib.util
import json
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parent
COMMANDS={'inspect':'Inspect a DCP/CUBE reference','plan':'View an existing project slot plan',
          'check-bindings':'Check host ST binding declarations','calibrate':'Generate calibration from measured inputs',
          'fit':'Fit native table candidates','prepare-transition':'Prepare exact-source forward/reverse manifests',
          'prepare-six-program':'Reproduce programs from the pinned historical three-look source',
          'prepare-preview-retry':'Prepare the exact historical preview repair'}

def missing_packages():
    return [name for name in ['numpy','scipy'] if importlib.util.find_spec(name) is None]

def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    parser=argparse.ArgumentParser(description=__doc__,epilog='Run from the extracted root: python lut.py inspect path/to/profile.dcp')
    parser.add_argument('--version',action='version',version='2.0')
    parser.add_argument('command',nargs='?',choices=['doctor',*COMMANDS],help='doctor checks the host; other commands are offline conversion')
    if not argv or argv[0] in ['-h','--help']:
        parser.print_help()
        for name,description in COMMANDS.items():print('  '+name+': '+description)
        return 0
    if argv==['--version']:print('2.0');return 0
    try:
        if argv[0] not in ['doctor',*COMMANDS]:raise ValueError('Unknown command; run python lut.py --help')
        valid=sys.version_info>=(3,10) and struct.calcsize('P')==8
        missing=missing_packages()
        if argv[0]=='doctor':
            parser.parse_args(argv)
            print(json.dumps({'python':sys.executable,'version':sys.version.split()[0],
                'bits':struct.calcsize('P')*8,'platform':sys.platform,'host_supported':valid,
                'missing_packages':missing,'camera_io':False,'device_installation_command_included':False},indent=2))
            return 0 if valid and not missing else 2
        if not valid:raise ValueError('64-bit Python 3.10+ is required')
        if missing:raise ValueError('Missing '+', '.join(missing)+'. Use this interpreter: '+sys.executable+' -m pip install -r '+str(ROOT/'src/looks/requirements.txt'))
        sys.path.insert(0,str(ROOT/'src/looks'))
        from looktool.__main__ import main as run
        return run(argv)
    except (ValueError,OSError,ImportError) as exc:
        print('Stopped: '+str(exc),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
