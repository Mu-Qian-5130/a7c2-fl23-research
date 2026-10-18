"""Human-operated LUT installation commands; no AI service is used."""
import argparse,json,uuid
from datetime import datetime,timezone
from pathlib import Path
from .devicejob import Job,write_json

CONFIG=Path.home()/'.a7c2-lut/config.json'
DEFAULT_MODEL=Path(__file__).resolve().parents[1]/'assets/rendering-model-v1.json'
COMMANDS={'configure','import','install','verify','restore','recover','resume'}

def settings():
    if not CONFIG.exists():return {}
    value=json.loads(CONFIG.read_text(encoding='utf-8'))
    if value.get('schema')!='a7c2-lut-user-config/1':raise ValueError('Unknown local configuration')
    return value

def main(argv):
    parser=argparse.ArgumentParser(prog='lut.py '+argv[0])
    action=argv[0]
    if action=='configure':
        parser.add_argument('--calibration',type=Path,required=True);parser.add_argument('--backup-root',type=Path,required=True)
        args=parser.parse_args(argv[1:]);from .calibration import validate
        validate(json.loads(args.calibration.read_text(encoding='utf-8-sig')),False)
        write_json(CONFIG,{'schema':'a7c2-lut-user-config/1','calibration':str(args.calibration.resolve()),'backup_root':str(args.backup_root.resolve())})
        print('Saved local calibration and backup location; no camera connection.');return 0
    if action=='import':
        parser.add_argument('source',type=Path);parser.add_argument('--name',required=True);parser.add_argument('--slot',type=int,default=1)
        parser.add_argument('--calibration',type=Path);parser.add_argument('--backup-dir',type=Path);parser.add_argument('--work-dir',type=Path)
        parser.add_argument('--write',action='store_true');parser.add_argument('--battery-percent',type=int);parser.add_argument('--zig')
        parser.add_argument('--input-space',help='For CUBE: sony-st-srgb, or a named input space with --bridge')
        parser.add_argument('--bridge',type=Path,help='CUBE mapping Sony ST sRGB into the reference CUBE input space')
        args=parser.parse_args(argv[1:]);config=settings()
        model=args.calibration or config.get('calibration') or DEFAULT_MODEL
        identifier=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
        folder=args.work_dir or Path.home()/'.a7c2-lut/jobs'/identifier
        backup=args.backup_dir or Path(config.get('backup_root',Path.home()/'.a7c2-lut/backups'))/identifier
        job=Job(folder,zig=args.zig)
        print('Import:',args.source,'→ custom',args.slot,'as',args.name,flush=True)
        print('Job:',folder,'\nBackup:',backup,flush=True)
        if Path(model).resolve()==DEFAULT_MODEL.resolve():print('Color mapping: shared one-scene approximation. Use --calibration for your own measured bridge; this does not reproduce the complete Adobe renderer.',flush=True)
        state=job.create(args.source,args.name,args.slot,model,backup,write=args.write,battery=args.battery_percent,input_space=args.input_space,bridge=args.bridge)
    else:
        parser.add_argument('job',type=Path)
        if action in ['install','restore','resume']:parser.add_argument('--battery-percent',type=int,required=True)
        if action=='verify':parser.add_argument('--accept-photos',action='store_true',help='Record your actual successful preview/new-photo/playback checks')
        args=parser.parse_args(argv[1:]);job=Job(args.job)
        if action=='install':state=job.install(args.battery_percent)
        elif action=='verify':state=job.verify(args.accept_photos)
        elif action=='restore':state=job.restore(args.battery_percent)
        elif action=='recover':state=job.recover()
        elif action=='resume':state=job.resume(args.battery_percent)
        else:raise ValueError('Unknown device operation')
    print(json.dumps({'phase':state['phase'],'job':str(job.root),'slot':state['slot'],'name':state['name']},ensure_ascii=False,indent=2))
    if state['phase'] in ['AWAITING_RELOAD','RESTORED_AWAITING_RELOAD']:
        print('All I/O ended. Disconnect every external power source, shut down normally, wait for the lamp, remove battery ≥1 minute, then restart. Test preview/new photos/playback, reconnect and run verify.')
    elif state['phase']=='PREFLIGHT_VERIFIED':print('Prepared and checked only. No firmware/name/settings writes. Run install with the real battery percentage to write.')
    return 0
