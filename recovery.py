"""Independent A7C II recovery: restore a complete or original FL23 backup."""
import argparse
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parent

def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version',action='version',version='2.2-preview.1')
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('restore',help='Return to the selected backup, including later FL23/LUT changes')
    p.add_argument('backup',type=Path);p.add_argument('--work-dir',type=Path)
    p.add_argument('--firmware-version',required=True);p.add_argument('--battery-percent',type=int,required=True);p.add_argument('--zig')
    p=sub.add_parser('verify',help='Verify loaded state after the completed restore and cold restart')
    p.add_argument('work',type=Path);p.add_argument('--accept-photos',action='store_true')
    p=sub.add_parser('inspect',help='Show the backup type and scope offline')
    p.add_argument('backup',type=Path)
    args=parser.parse_args(argv)
    try:
        if sys.version_info<(3,10) or struct.calcsize('P')!=8:raise ValueError('64-bit Python 3.10+ required')
        sys.path.insert(0,str(ROOT/'src/looks'))
        from looktool.checkpointcli import main as run
        if args.command=='restore':
            call=['rollback',str(args.backup),'--firmware-version',args.firmware_version,'--battery-percent',str(args.battery_percent)]
            if args.work_dir:call+=['--work-dir',str(args.work_dir)]
            if args.zig:call+=['--zig',args.zig]
        elif args.command=='verify':
            call=['rollback-verify',str(args.work)]+(['--accept-photos'] if args.accept_photos else [])
        else:call=['inspect-checkpoint',str(args.backup)]
        return run(call)
    except (ValueError,OSError,ImportError,RuntimeError) as exc:
        print('Stopped: '+str(exc),file=sys.stderr);return 2
    except KeyboardInterrupt:
        print('Interrupted. Preserve the recovery work folder and its native reports; inspect the outcome before another write.',file=sys.stderr);return 130

if __name__=='__main__':raise SystemExit(main())
