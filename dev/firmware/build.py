"""Build an unsigned local firmware candidate; never contacts a camera."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path,help='Official C2 2.01 DAT or decoded FDAT')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--update-version',default='3.01')
    parser.add_argument('--whitebalance',action='store_true')
    parser.add_argument('--ssh',action='store_true')
    parser.add_argument('--client-key',type=Path)
    parser.add_argument('--artifacts',type=Path)
    parser.add_argument('--no-fl23',action='store_true')
    parser.add_argument('--sound',action='store_true')
    parser.add_argument('--no-default-looks',action='store_true')
    args=parser.parse_args()
    from desktopapp.firmwarelocal import build
    request=dict(sony_firmware=str(args.source),workspace=str(args.output),update_version=args.update_version,
                 whitebalance=args.whitebalance,ssh=args.ssh,fl23=not args.no_fl23,sound=args.sound)
    if not args.no_default_looks:
        from desktopapp.presets import PACK
        request['preset_pack']=PACK
    if args.client_key:request['client_key']=str(args.client_key)
    if args.artifacts:request['artifacts']=str(args.artifacts)
    result=build(request,args.output.parent)
    print(json.dumps(result,indent=2,ensure_ascii=False))


if __name__=='__main__':main()
