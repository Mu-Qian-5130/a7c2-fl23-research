"""Sign a local C2 FDAT as an offline DAT candidate; never opens a device."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plaintext',type=Path)
    parser.add_argument('--official-container',type=Path,required=True)
    parser.add_argument('--private-key',type=Path,required=True)
    parser.add_argument('--public-key',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    from desktopapp.firmwaresign import sign_candidate
    report=sign_candidate(args.plaintext,args.official_container,args.private_key,args.public_key,args.output)
    args.output.with_suffix('.private.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
