"""Full original checkpoint operations shared by FL23 and LUT."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import uuid
from . import checkpoint

COMMANDS={'rollback','rollback-verify','inspect-checkpoint'}

def main(argv):
    action=argv[0];p=argparse.ArgumentParser(prog='recovery.py '+{'rollback':'restore','rollback-verify':'verify','inspect-checkpoint':'inspect'}[action])
    if action=='inspect-checkpoint':
        p.add_argument('backup2',type=Path);a=p.parse_args(argv[1:]);manifest,_=checkpoint.load_target(a.backup2)
        # Do not print body IDs or private provenance paths to public logs.
        print(json.dumps({k:manifest[k] for k in ('schema','model','version','scope','limitations')},indent=2));return 0
    from .checkpointjob import Rollback
    if action=='rollback':
        p.add_argument('backup2',type=Path);p.add_argument('--battery-percent',type=int,required=True)
        p.add_argument('--firmware-version',required=True);p.add_argument('--work-dir',type=Path);p.add_argument('--zig')
        a=p.parse_args(argv[1:])
        folder=a.work_dir or Path.home()/'.a7c2-recovery/jobs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
        print('Rollback work:',folder,flush=True)
        state=Rollback(folder,zig=a.zig).run(a.backup2,a.battery_percent,a.firmware_version)
    else:
        p.add_argument('work',type=Path);p.add_argument('--accept-photos',action='store_true')
        a=p.parse_args(argv[1:]);state=Rollback(a.work).verify(a.accept_photos)
    print('Rollback:',state['phase']);return 0
