"""Desktop/phone-compatible fixed command client over SSH; explicit actions only."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))


def main():
    from desktopapp.worker import setup_runtime
    setup_runtime()
    from desktopapp import cameraapi
    from desktopapp.sshupdates import Connection
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ip',required=True)
    parser.add_argument('--client-private',type=Path,required=True)
    parser.add_argument('--host-public',type=Path,required=True)
    parser.add_argument('--workspace',type=Path,required=True)
    commands=parser.add_subparsers(dest='operation',required=True)
    commands.add_parser('info');commands.add_parser('task')
    look=commands.add_parser('look');look.add_argument('slot',type=int);look.add_argument('source',type=Path);look.add_argument('--name')
    sound=commands.add_parser('sound');sound.add_argument('selection',choices=['mechanical','electronic','both']);sound.add_argument('action',choices=['on','off','custom'])
    sound.add_argument('--source',type=Path,help='Native audio .bin, or audio/video converted locally')
    sound.add_argument('--start',type=float,default=0);sound.add_argument('--duration',type=float,default=.08)
    args=parser.parse_args();payload=None;values=[]
    if args.operation=='look':
        from looktool import lookfile
        document=lookfile.read(args.source);payload=cameraapi.look_payload(document)
        values=[args.slot,args.name or document['name']]
    elif args.operation=='sound':
        values=[args.selection,args.action]
        if args.action=='custom':
            if not args.source:parser.error('custom sound requires --source')
            if args.source.suffix.lower()=='.bin':payload=args.source.read_bytes()
            else:
                sys.path.insert(0,str(ROOT/'src/shutter_sound'));import media
                output=args.workspace/'converted';media.convert(args.source,output,start=args.start,duration=args.duration)
                payload=(output/'custom-native.private.bin').read_bytes()
    connection=Connection(args.ip,args.client_private,args.host_public,args.workspace/'connection')
    result=cameraapi.call(connection,args.operation,*values,payload=payload)
    print(json.dumps(result,ensure_ascii=False));return 1 if result.get('state')=='failed' else 0


if __name__=='__main__':raise SystemExit(main())
