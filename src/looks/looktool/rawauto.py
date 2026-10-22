"""Install a Lightroom watcher and route its new-photo jobs. No USB."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import uuid
from . import rawprofiles,rawidentity


def lua_string(value):
    return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('\n','\\n').replace('\r','\\r')+'"'


def install(exiftool, *, root=None, modules=None, interval=5, copy_exiftool=True):
    source=Path(__file__).resolve().parents[3]
    root=Path(root) if root else Path.home()/'.a7look/auto-profile'
    runtime=root/'runtime';(runtime/'src/looks/looktool').mkdir(parents=True,exist_ok=True)
    for name in ('__init__','rawprofiles','rawidentity','rawauto'):
        shutil.copy2(source/'src/looks/looktool'/(name+'.py'),runtime/'src/looks/looktool'/(name+'.py'))
    shutil.copy2(source/'raw_auto.py',runtime/'raw_auto.py')
    exiftool=Path(exiftool).resolve()
    if not exiftool.is_file():raise ValueError('ExifTool executable not found')
    if copy_exiftool and sys.platform=='win32' and (exiftool.parent/'exiftool_files').is_dir():
        local=runtime/'exiftool';local.mkdir(exist_ok=True)
        shutil.copy2(exiftool,local/exiftool.name)
        shutil.copytree(exiftool.parent/'exiftool_files',local/'exiftool_files',dirs_exist_ok=True)
        exiftool=local/exiftool.name
    if modules is None:
        if sys.platform=='win32':
            import os
            modules=Path(os.environ['APPDATA'])/'Adobe/Lightroom/Modules'
        elif sys.platform=='darwin':modules=Path.home()/'Library/Application Support/Adobe/Lightroom/Modules'
        else:raise ValueError('Lightroom Classic requires Windows or macOS')
    plugin=Path(modules)/'A7LookAuto.lrplugin';plugin.mkdir(parents=True,exist_ok=True)
    for path in (source/'plugins/A7LookAuto.lrplugin').glob('*.lua'):shutil.copy2(path,plugin/path.name)
    settings=dict(schema='a7c2-LR-auto-settings/1',library=str(root/'library'),registry=str(root/'registry'),
        adobe_profiles=str(rawprofiles.adobe_profile_directory()),python=sys.executable,
        exiftool=str(exiftool),worker=str(runtime/'raw_auto.py'),work_root=str(root/'jobs'),
        install_id=uuid.uuid4().hex,interval=interval,log=str(root/'plugin.log'),status=str(root/'plugin-status.txt'))
    rawprofiles.write_json(root/'settings.json',settings)
    rawprofiles.write_json(root/'plugin-settings.json',settings)
    fields=['return {']+[f'    {key} = {value if isinstance(value,int) else lua_string(value)},' for key,value in
        dict(settings=str(root/'plugin-settings.json'),python=sys.executable,worker=str(runtime/'raw_auto.py'),
             work_root=str(root/'jobs'),interval=interval,install_id=settings['install_id'],
             log=settings['log'],status=settings['status']).items()]+['}']
    (plugin/'Config.lua').write_text('\n'.join(fields)+'\n',encoding='utf-8')
    return dict(plugin=str(plugin),settings=str(root/'settings.json'),install_id=settings['install_id'],
        camera_io=False,next_step='Enable A7Look Auto Profiles in Lightroom Plug-in Manager once')


def worker(job,settings_file):
    job=Path(job);settings=json.loads(Path(settings_file).read_text(encoding='utf-8'))
    requests=[]
    for line in (job/'files.tsv').read_text(encoding='utf-8').splitlines():
        identifier,encoded=line.split('\t');requests.append((identifier,bytes.fromhex(encoded).decode('utf-8')))
    files=[Path(path) for _,path in requests]
    rows=rawprofiles.plan(files,rawprofiles.Registry(settings['registry']),settings['exiftool'])
    if settings.get('allowed_roots'):
        roots=[Path(path).resolve() for path in settings['allowed_roots']]
        for row in rows:
            if not any(Path(row['file']).resolve().is_relative_to(root) for root in roots):
                row.update(action='skip',reason='outside_private_test_scope')
    lookup={str(Path(path).resolve()).casefold() if sys.platform=='win32' else str(Path(path).resolve()):identifier for identifier,path in requests}
    rawprofiles.install_profiles(rows,settings['adobe_profiles'])
    output=[]
    for row in rows:
        key=str(Path(row['file']).resolve());key=key.casefold() if sys.platform=='win32' else key
        identifier=lookup[key]
        output.append('\t'.join((identifier,'apply' if row['action']=='profile' else 'skip',
            row.get('profile','').encode().hex(),str(row.get('look_id') or row.get('binding_id') or '').encode().hex(),
            row.get('reason','').encode().hex())))
    temporary=job/'result.tsv.new';temporary.write_text('\n'.join(output)+'\n',encoding='utf-8')
    temporary.replace(job/'result.tsv')
    rawprofiles.write_json(job/'routing.json',dict(camera_io=False,photos=rows))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    setup=commands.add_parser('install');setup.add_argument('--exiftool',type=Path)
    setup.add_argument('--data-root',type=Path);setup.add_argument('--modules',type=Path)
    setup.add_argument('--interval',type=int,default=5)
    run=commands.add_parser('worker');run.add_argument('--job',type=Path,required=True);run.add_argument('--settings',type=Path,required=True)
    attach=commands.add_parser('attach-source');attach.add_argument('look',type=Path);attach.add_argument('--dcp',type=Path,required=True);attach.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.command=='install':
        tool=args.exiftool or shutil.which('exiftool')
        if not tool:parser.error('Provide --exiftool or install ExifTool on PATH')
        print(json.dumps(install(tool,root=args.data_root,modules=args.modules,interval=args.interval),ensure_ascii=False,indent=2))
    elif args.command=='worker':worker(args.job,args.settings)
    elif args.command=='attach-source':
        if args.output.exists():raise ValueError('Choose a new output file')
        document=json.loads(args.look.read_text(encoding='utf-8-sig'))
        if document.get('schema')!='a7c2-creative-look/1':raise ValueError('Expected an A7Look file')
        document['raw_profile']=rawidentity.descriptor(args.dcp,document.get('name'))
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x',encoding='utf-8') as stream:json.dump(document,stream,ensure_ascii=False,indent=2)
        print('Added portable source DCP and version; camera color parameters unchanged.')
    return 0


if __name__=='__main__':raise SystemExit(main())
