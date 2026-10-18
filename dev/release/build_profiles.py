"""Package owner-provided original DCPs separately, retaining notices and hashes."""
import argparse,hashlib,json,struct,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
FUJI={'Astia','Bleach_Bypass','Classic_Chrome','Classic_Negative','Eterna','Nostalgic_Negative','Pro_Neg_Hi','Pro_Neg_Std','Provia','Reala_Ace','Velvia'}
RICOH={'Hard Monotone','Monotone','Negative Film','Positive Film','Soft Monotone','Standard','Vivid'}
def sha(data):return hashlib.sha256(data).hexdigest()
def metadata(raw):
    if raw[:2] not in [b'II',b'MM']:raise ValueError('Not a DCP TIFF')
    order='<' if raw[:2]==b'II' else '>';at=struct.unpack_from(order+'I',raw,4)[0];count=struct.unpack_from(order+'H',raw,at)[0];text={}
    for i in range(count):
        start=at+2+12*i;tag,kind,n,p=struct.unpack_from(order+'HHII',raw,start)
        if kind==2:
            value=raw[start+8:start+8+n] if n<=4 else raw[p:p+n]
            if len(value)!=n:raise ValueError('Truncated DCP metadata')
            text[str(tag)]=value.rstrip(b'\0').decode('utf-8',errors='replace')
    if text.get('50708')!='Sony ILCE-7CM2':raise ValueError('Unexpected DCP model')
    return text
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('fuji',type=Path);p.add_argument('ricoh',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    expected=[('Fuji-MTriton',a.fuji/f'Sony_ILCE-7CM2_{name}_MTriton.dcp','CC BY-NC-SA 4.0; see original README') for name in sorted(FUJI)]
    expected += [('Ricoh-GRIII',a.ricoh/f'Sony_ILCE-7CM2 RICOH GR III Camera {name} (GR Look, a7C2 WB).dcp','No separate redistribution license supplied; embedded copyright retained') for name in sorted(RICOH)]
    files={};rows=[]
    for family,path,license_note in expected:
        data=path.read_bytes();tags=metadata(data);name=family+'/'+path.name;files[name]=data
        rows.append({'file':name,'bytes':len(data),'sha256':sha(data),'profile_name':tags.get('50936'),'camera_model':tags.get('50708'),
            'embedded_copyright':tags.get('50942'),'license_note':license_note,'file_modified_by_this_repository':False})
    original=a.fuji/'README_Sony_A7CII_MTriton_DCP_CN_EN.txt'
    files['Fuji-MTriton/'+original.name]=original.read_bytes()
    for lang,name in [('en','README.md'),('zh-CN','README.zh-CN.md')]:
        text=(ROOT/f'docs/{lang}/profiles.md').read_text(encoding='utf-8')
        # A standalone attachment keeps local language/manifest links, without repository navigation.
        lines=text.splitlines();lines[2]='[English](README.md) | [简体中文](README.zh-CN.md)'
        text='\n'.join(lines)+'\n';text=text.replace('../profiles/manifest.json','manifest.json')
        files[name]=text.encode('utf-8')
    files['CC-BY-NC-SA-4.0.txt']=(ROOT/'docs/profiles/CC-BY-NC-SA-4.0.txt').read_bytes().replace(b'\r\n',b'\n')
    manifest={'date':'2026-10-18','model':'Sony ILCE-7CM2','original_DCP_count':len(rows),'file_bytes_unchanged':True,
        'provenance':'Original files supplied by repository owner; uploaded at their explicit request',
        'not_a_firmware_installer':True,'MIT_license_does_not_apply_to_profiles':True,'profiles':rows}
    text=(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n').encode();files['manifest.json']=text
    (ROOT/'docs/profiles/manifest.json').write_bytes(text)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(a.output,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,data in sorted(files.items()):
            info=zipfile.ZipInfo('a7c2-dcp-profiles/'+name,date_time=(2026,10,18,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;z.writestr(info,data)
    with zipfile.ZipFile(a.output) as z:
        if z.testzip():raise ValueError('Profile ZIP corrupt')
        for row in rows:
            if sha(z.read('a7c2-dcp-profiles/'+row['file']))!=row['sha256']:raise ValueError('Profile copy differs')
    print(json.dumps({'file':a.output.name,'DCP_files':len(rows),'bytes':a.output.stat().st_size,'sha256':sha(a.output.read_bytes()),'original_bytes_verified':True},indent=2))
if __name__=='__main__':main()
