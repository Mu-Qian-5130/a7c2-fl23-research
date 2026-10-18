"""Build the current source-layout tools bundle; never include private camera files."""
import argparse,hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
VERSION='2.1'
def sha(data):return hashlib.sha256(data).hexdigest()
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/f'dist/a7c2-tools-{VERSION}.zip');args=parser.parse_args()
    files={}
    sources=[ROOT/name for name in ['README.md','README.zh-CN.md','LICENSE','AGENTS.md','FL23.cmd','lut.py']]
    for folder in ['src','docs','dev']:
        sources.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and not any(v in p.parts for v in ['__pycache__','.venv','private']))
    for source in sources:
        relative=source.relative_to(ROOT).as_posix()
        if '.private.' in source.name or source.suffix in ['.dcp','.cube','.ARW','.HIF','.npz','.npy','.pyc']:raise ValueError('Unexpected private/profile file')
        data=source.read_bytes()
        if not relative.startswith('src/fl23/assets/') and (source.suffix in ['.py','.md','.json','.txt','.ps1'] or source.name=='LICENSE'):data=data.replace(b'\r\n',b'\n')
        files[relative]=data
    if sha(files['src/fl23/transport.py'])!='a578ebfd0cffa0f715ec025ef7e661d239652ae8573cea3982a27c8c08f06ccb':raise ValueError('Reviewed startup fix missing')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(args.output,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,data in sorted(files.items()):
            info=zipfile.ZipInfo(f'a7c2-tools-{VERSION}/'+name,date_time=(2026,10,18,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;z.writestr(info,data)
    with zipfile.ZipFile(args.output) as z:
        if z.testzip():raise ValueError('Tools ZIP corrupt')
    print(json.dumps({'file':args.output.name,'bytes':args.output.stat().st_size,'sha256':sha(args.output.read_bytes()),'files':len(files),'camera_io':False},indent=2))
if __name__=='__main__':main()
