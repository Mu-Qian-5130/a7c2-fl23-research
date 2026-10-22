"""Verify current Release bundles locally without camera access."""
import hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
VERSION='2.2-preview.1'
def sha(data):return hashlib.sha256(data).hexdigest()
def main():
    tools=ROOT/f'dist/a7c2-tools-{VERSION}.zip';profiles=ROOT/'dist/a7c2-dcp-profiles-2026-10-18.zip';standalone=ROOT/'dist/lut.py';recovery=ROOT/'dist/recovery.py'
    with zipfile.ZipFile(tools) as z:
        if z.testzip():raise ValueError('Tool ZIP corrupt')
        prefix=f'a7c2-tools-{VERSION}/src/fl23/';manifest=json.loads(z.read(prefix+'assets/manifest.json'))
        for name,h in manifest['files'].items():
            if sha(z.read(prefix+'assets/'+name))!=h:raise ValueError('Camera asset differs')
        if z.read(prefix+'transport.py')!=(ROOT/'src/fl23/transport.py').read_bytes().replace(b'\r\n',b'\n'):raise ValueError('Packaged transport differs from current source')
        if any('/Fix-USB-' in n or n.endswith('0.1.0.zip') for n in z.namelist()):raise ValueError('Old extra tools included')
        if any(f'a7c2-tools-{VERSION}/'+name not in z.namelist() for name in ('lut.py','recovery.py','FL23.cmd')):raise ValueError('FL23, LUT or Recovery entry missing')
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
        if len(text.splitlines())>100 or 'Fix-USB-Startup-v1.cmd' in text or '0.1.0' in text:raise ValueError('Homepage is not concise/current')
        if 'main' not in text or 'v1.0' not in text or 'v2.1' not in text:raise ValueError('Current source/release links missing')
    import ast,base64,io
    for entry in (standalone,recovery):
        tree=ast.parse(entry.read_text(encoding='ascii'))
        payload=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PAYLOAD' for t in n.targets))
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(payload))) as z:
            bundled=json.loads(z.read('bundle-manifest.json'))
            for name,h in bundled.items():
                if sha(z.read(name))!=h or z.read(name)!=(ROOT/name).read_bytes():raise ValueError('Standalone source differs: '+name)
    paths=[tools,standalone,recovery];lines=['{}  {}'.format(sha(p.read_bytes()),p.name) for p in paths]
    (ROOT/'dist/SHA256SUMS.txt').write_text('\n'.join(lines)+'\n',encoding='ascii')
    print(json.dumps({'one_latest_tools_bundle_verified':True,'DCP_originals_verified':18,'English_and_Simplified_Chinese_homepages_under_100_lines':True,'camera_assets_unchanged':True,'camera_io':False,'checksums':lines},indent=2))
if __name__=='__main__':main()
