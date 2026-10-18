"""Verify current Release bundles locally without camera access."""
import hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def sha(data):return hashlib.sha256(data).hexdigest()
def main():
    tools=ROOT/'dist/a7c2-tools-2.1.zip';profiles=ROOT/'dist/a7c2-dcp-profiles-2026-10-18.zip';standalone=ROOT/'dist/lut.py'
    with zipfile.ZipFile(tools) as z:
        if z.testzip():raise ValueError('Tool ZIP corrupt')
        prefix='a7c2-tools-2.1/src/fl23/';manifest=json.loads(z.read(prefix+'assets/manifest.json'))
        for name,h in manifest['files'].items():
            if sha(z.read(prefix+'assets/'+name))!=h:raise ValueError('Camera asset differs')
        if sha(z.read(prefix+'transport.py'))!='a578ebfd0cffa0f715ec025ef7e661d239652ae8573cea3982a27c8c08f06ccb':raise ValueError('Integrated startup fix differs')
        if any('/Fix-USB-' in n or n.endswith('0.1.0.zip') for n in z.namelist()):raise ValueError('Old extra tools included')
        if 'a7c2-tools-2.1/lut.py' not in z.namelist() or 'a7c2-tools-2.1/FL23.cmd' not in z.namelist():raise ValueError('FL23 and LUT entries missing')
        if any(n.endswith('/Custom-LUT.cmd') or '/src/looks/gui.py' in n for n in z.namelist()):raise ValueError('Retired LUT launcher/GUI included')
    with zipfile.ZipFile(profiles) as z:
        if z.testzip():raise ValueError('DCP ZIP corrupt')
        manifest=json.loads(z.read('a7c2-dcp-profiles/manifest.json'))
        rows=manifest['profiles']
        if len(rows)!=18 or sum(r['file'].startswith('Fuji-') for r in rows)!=11:raise ValueError('Profile count differs')
        for row in rows:
            data=z.read('a7c2-dcp-profiles/'+row['file'])
            if sha(data)!=row['sha256'] or len(data)!=row['bytes']:raise ValueError('Profile bytes differ')
        if json.loads((ROOT/'docs/profiles/manifest.json').read_text(encoding='utf-8'))!=manifest:raise ValueError('Published profile manifest differs')
    for lang in ['','zh-CN']:
        name='README'+('.'+lang if lang else '')+'.md';text=(ROOT/name).read_text(encoding='utf-8')
        if len(text.splitlines())>30 or 'Fix-USB-Startup-v1.cmd' in text or '0.1.0' in text:raise ValueError('Homepage is not concise/current')
        if 'releases/download/v2.1-preview.1/a7c2-tools-2.1.zip' not in text:raise ValueError('Current tools link missing')
    import ast,base64,io
    tree=ast.parse(standalone.read_text(encoding='ascii'))
    payload=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PAYLOAD' for t in n.targets))
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(payload))) as z:
        bundled=json.loads(z.read('bundle-manifest.json'))
        for name,h in bundled.items():
            if sha(z.read(name))!=h or z.read(name)!=(ROOT/name).read_bytes():raise ValueError('Standalone source differs: '+name)
    paths=[tools,standalone,profiles];lines=['{}  {}'.format(sha(p.read_bytes()),p.name) for p in paths]
    (ROOT/'dist/SHA256SUMS.txt').write_text('\n'.join(lines)+'\n',encoding='ascii')
    print(json.dumps({'one_latest_tools_bundle_verified':True,'DCP_originals_verified':18,'English_and_Simplified_Chinese_homepages_under_30_lines':True,'camera_assets_unchanged':True,'camera_io':False,'checksums':lines},indent=2))
if __name__=='__main__':main()
