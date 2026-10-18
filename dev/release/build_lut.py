"""Build one portable Python file; never include private jobs or input profiles."""
import argparse,base64,hashlib,io,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

BOOTSTRAP='''"""A7C II LUT importer. Run with Python 3.10+, then --help."""
import base64,hashlib,io,json,os,runpy,shutil,sys,tempfile,zipfile
PAYLOAD={payload!r}
def launch():
    if sys.version_info<(3,10):raise SystemExit('64-bit Python 3.10+ required')
    blob=base64.b64decode(PAYLOAD);archive=zipfile.ZipFile(io.BytesIO(blob))
    hashes=json.loads(archive.read('bundle-manifest.json'));key=hashlib.sha256(archive.read('bundle-manifest.json')).hexdigest()
    root=__import__('pathlib').Path.home()/'.a7c2-lut/runtime'/key;root.parent.mkdir(parents=True,exist_ok=True)
    if not root.exists():
        temporary=__import__('pathlib').Path(tempfile.mkdtemp(prefix=key+'.',dir=root.parent))
        try:
            for name,wanted in hashes.items():
                relative=__import__('pathlib').PurePosixPath(name)
                if relative.is_absolute() or '..' in relative.parts or ':' in name or chr(92) in name:raise ValueError('Invalid bundled path')
                data=archive.read(name)
                if hashlib.sha256(data).hexdigest()!=wanted:raise ValueError('Corrupt bundled file')
                target=temporary/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
            try:os.rename(temporary,root)
            except OSError:
                if not root.is_dir():raise
        finally:
            if temporary.exists():
                if temporary.resolve().parent!=root.parent.resolve() or not temporary.name.startswith(key+'.'):raise ValueError('Unexpected staging cleanup path')
                shutil.rmtree(temporary)
    for name,wanted in hashes.items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=wanted:raise ValueError('Cached tool changed; retain jobs and remove only runtime/'+key)
    sys.argv[0]=str(root/'lut.py');runpy.run_path(str(root/'lut.py'),run_name='__main__')
if __name__=='__main__':launch()
'''

def build(destination):
    sources=[ROOT/'lut.py',ROOT/'LICENSE']
    for folder in ['src/looks','src/fl23']:
        sources.extend(p for p in (ROOT/folder).rglob('*') if p.is_file()
            and not any(v in p.parts for v in ['__pycache__','tests','examples','zig-global','zig-local'])
            and p.suffix in ['.py','.json','.so','.c','.h','.txt'] )
    files={}
    for p in sources:
        name=p.relative_to(ROOT).as_posix()
        if '.private.' in name:raise ValueError('Private file in bundle')
        files[name]=p.read_bytes()
    manifest=json.dumps({n:hashlib.sha256(b).hexdigest() for n,b in sorted(files.items())},sort_keys=True).encode('ascii')
    payload=io.BytesIO()
    with zipfile.ZipFile(payload,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,data in sorted(dict(files,**{'bundle-manifest.json':manifest}).items()):
            info=zipfile.ZipInfo(name,(2026,10,18,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;z.writestr(info,data)
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(BOOTSTRAP.format(payload=base64.b64encode(payload.getvalue()).decode('ascii')),encoding='ascii',newline='\n')
    return {'file':destination.name,'bytes':destination.stat().st_size,'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'bundled_files':len(files),'camera_io':False}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=ROOT/'dist/lut.py')
    print(json.dumps(build(parser.parse_args().output),indent=2))
