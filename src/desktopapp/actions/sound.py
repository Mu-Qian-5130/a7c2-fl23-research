"""Shared sound CLI adapter; conversion/volume remain host-only actions."""
import json
from pathlib import Path
import sys
import math
import uuid
from ..paths import ROOT

def run(action,args):
    sys.path.insert(0, str(ROOT / 'src/shutter_sound'))
    if action=='sound_generate':
        from native_codec import write_wav
        from sound_cli import import_audio
        duration=float(args.get('duration',.08));frequency=float(args.get('frequency',880))
        if not math.isfinite(duration) or not .01<=duration<=2 or frequency not in (660,880):
            raise ValueError('请选择示例音效和 0.01–2 秒的长度。')
        root=Path(args['workspace']);root.mkdir(parents=True,exist_ok=True)
        source=root/('generated-'+uuid.uuid4().hex+'.private.wav')
        count=round(duration*24000)
        samples=[round(12000*math.sin(2*math.pi*frequency*i/24000)*
            min(1,i/120,(count-1-i)/120)*math.exp(-4*i/count)) for i in range(count)]
        write_wav(source,samples,24000)
        return dict(import_audio(root,None,source,duration=duration,peak=.4),workspace=str(root))
    if action=='sound_install' and 'sound_target' in args:
        from targeted_sound import run as save_targeted
        return save_targeted(args)
    from sound_cli import main
    command = action.removeprefix('sound_').replace('_', '-')
    argv = [command]
    if command == 'import':
        argv += [args['source'], '--start', str(args.get('start', 0)),
                 '--duration', str(args.get('duration', .5)),
                 '--peak', str(args.get('peak', .4))]
    elif command == 'volume':
        argv += ['--reset'] if args.get('reset') else ['--decibels',str(args['decibels'])]
    elif command=='compile-install':
        argv += ['--ap',args['ap'],'--cp',args['cp'],'--native-bin',args['native_bin']]
    argv += ['--workspace', args['workspace']]
    if command in ('on','install','audition') and args.get('backup'):
        argv += ['--backup-copy',args['backup']]
    if command == 'on':
        argv += ['--firmware', args['firmware']]
    if command in ('on', 'install'):
        if not args.get('power_confirmed') and args.get('battery') is None:
            raise ValueError('Confirm power (or give the battery percentage) before a sound write')
        argv += ['--power-confirmed'] if args.get('power_confirmed') else ['--battery-percent', str(args['battery'])]
    elif command == 'confirm':
        argv += ['--result', args.get('result', 'correct')]
    elif command == 'verify' and args.get('accepted'):
        argv += ['--heard-correct']
    outcome, stopped = {}, []
    code = main(argv, report=outcome.update, failure=stopped.append)
    if code:
        # Show the backend's own reason; the generic text hid e.g. a silent clip.
        raise RuntimeError(stopped[-1] if stopped else 'Sound operation stopped; see the complete backend log above.')
    return dict(outcome, workspace=args['workspace'], command=command, exit_code=code)


def has_conversion(workspace):
    """Whether a converted clip is selected; read locally before any USB access."""
    sys.path.insert(0, str(ROOT / 'src/shutter_sound'))
    from sound_cli import selected_conversion
    root = Path(workspace)
    state_file = root / 'sound.private.json'
    state = json.loads(state_file.read_text(encoding='utf-8')) if state_file.is_file() else {}
    conversion = selected_conversion(root, state)
    return bool(conversion) and (Path(conversion) / 'custom-native.private.bin').is_file()


def converted_file(workspace,name='custom-native.private.bin'):
    """Use the same selected, volume-adjusted conversion for both transports."""
    sys.path.insert(0,str(ROOT/'src/shutter_sound'))
    from sound_cli import selected_conversion
    root=Path(workspace)
    state={}
    if not (root/'conversion.private.json').is_file() and (root/'sound.private.json').is_file():
        state=json.loads((root/'sound.private.json').read_text(encoding='utf-8'))
    folder=selected_conversion(root,state)
    if not folder or not (Path(folder)/name).is_file():
        raise ValueError('请先导入并转换片段，或生成示例音效。')
    return Path(folder)/name
