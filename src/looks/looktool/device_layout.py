"""Reviewed full7-v4 code identity with independently variable checked tables.

The original exact-SHA adapter remains unchanged. This additional adapter
recognizes a pinned program layout and still binds every job to full hashes.
"""
import hashlib,struct,json
from pathlib import Path
from . import firmware,six

CODE_SHA='5434cd40a746fef421fbe6825ebbdc1d41aa5304a686a162bb56378a6e94c4b5'  # Filled from the known complete v4 private fixture during build.

def runtime():
    data=json.loads((Path(__file__).resolve().parents[1]/'assets/runtime-v1.json').read_text(encoding='utf-8'))
    if data['schema']!='a7c2-lut-runtime/1':raise ValueError('Unknown runtime patch schema')
    return data

def _ap_target(source,mask):
    asset=runtime();result=bytearray(source)
    result[0x35287f0:0x3528874]=bytes.fromhex(asset['ap_templates'][mask])
    result[0x1b5cd7c:0x1b5cd80]=bytes.fromhex(asset['title_branch'])
    result[0x4c7cf7c:0x4c7cf88]=bytes.fromhex(asset['map'])
    for i in range(6):
        if mask&(1<<i):struct.pack_into('<I',result,0x59896f0+i*0xb8,0x0200ab2c+i)
    return bytes(result)

def identify_ap(ap):
    digest=firmware.sha(ap)
    if digest==six.AP_SHA:return {'kind':'legacy-six','mask':63,'label_ids':list(__import__(__package__+'.resources',fromlist=['LABEL_IDS']).LABEL_IDS)}
    for spec in runtime()['ap_sources']:
        if len(ap)!=spec['bytes']:continue
        restored=bytearray(ap)
        for window in spec['restore']:
            at=window['offset'];raw=bytes.fromhex(window['hex']);restored[at:at+len(raw)]=raw
        if firmware.sha(restored)!=spec['sha256']:continue
        if digest==spec['sha256']:return {'kind':spec['kind'],'mask':0,'label_ids':list(range(0x0200ab2c,0x0200ab32)),'first_install':True}
        # Masks are checked against a complete rebuilt AP, not merely ignored.
        template=ap[0x35287f0:0x3528874].hex();templates=runtime()['ap_templates']
        if template not in templates:continue
        mask=templates.index(template)
        if mask and _ap_target(bytes(restored),mask)==ap:return {'kind':spec['kind']+'-lut','mask':mask,'label_ids':list(range(0x0200ab2c,0x0200ab32))}
    raise ValueError('Unsupported AP identity; no firmware/settings writes performed')

def code_hash(cp):
    start=six.TABLE_FILE+8;end=six.TABLE_FILE+32+6*six.TABLE_BYTES
    if len(cp)<end:raise ValueError('Truncated CP program')
    h=hashlib.sha256();h.update(cp[:start]);h.update(bytes(end-start));h.update(cp[end:]);return h.hexdigest()

def identify(ap,cp):
    a=identify_ap(ap);c=firmware.sha(cp);asset=runtime()
    if a['kind']=='legacy-six':
        if code_hash(cp)!=CODE_SHA:raise ValueError('Unsupported legacy CP code identity')
        six.read_tables(cp)
    elif a.get('first_install'):
        spec=next((s for s in asset['cp_sources'] if s['kind']==a['kind']),None)
        if spec is None or c!=spec['sha256']:raise ValueError('First import needs the exact matching stock/FL23 AP+CP pair')
    else:
        if code_hash(cp)!=asset['cp_code_sha256']:raise ValueError('Unsupported standalone CP code identity')
        six.read_tables(cp)
    return dict(a,layout='full7-v4' if a['kind']=='legacy-six' else 'standalone-v1',AP=firmware.sha(ap),CP=c,
        physical_first_install_tested=False if a['kind']!='legacy-six' else None)

def replace(ap,cp,replacements):
    identity=identify(ap,cp)
    if not replacements or any(type(s) is not int or s not in range(1,7) for s in replacements):raise ValueError('Select custom slots 1..6')
    result=bytearray(cp);spans=[];ap_result=ap;ap_spans=[]
    if identity.get('first_install'):
        spec=next(s for s in runtime()['cp_sources'] if s['kind']==identity['kind'])
        for w in spec['windows']:
            at=w['offset'];old,new=bytes.fromhex(w['before']),bytes.fromhex(w['after'])
            if cp[at:at+len(old)]!=old:raise ValueError('Bootstrap source window differs')
            result[at:at+len(new)]=new
        if firmware.sha(result)!=runtime()['cp_zero_tables_sha256']:raise ValueError('Canonical runtime differs')
    if identity['kind']!='legacy-six':
        source=bytearray(ap)
        spec=next(s for s in runtime()['ap_sources'] if identity['kind'].startswith(s['kind']))
        for w in spec['restore']:
            raw=bytes.fromhex(w['hex']);source[w['offset']:w['offset']+len(raw)]=raw
        mask=identity['mask']|sum(1<<(s-1) for s in replacements)
        ap_result=_ap_target(bytes(source),mask)
        ap_spans=[(w['offset'],len(bytes.fromhex(w['hex']))) for w in spec['restore']]
    for slot,raw in sorted(replacements.items()):
        six.decode(raw);at=six.TABLE_FILE+32+(slot-1)*six.TABLE_BYTES;check=six.TABLE_FILE+8+(slot-1)*4
        result[at:at+six.TABLE_BYTES]=raw;struct.pack_into('<I',result,check,six.fnv(raw));spans.extend([(at,six.TABLE_BYTES),(check,4)])
    if identity.get('first_install'):
        # Derive disjoint bounded windows including bootstrap and user data.
        spans=[];start=None;last=None
        for at,(a,b) in enumerate(zip(cp,result)):
            if a!=b:
                if start is None:start=at
                elif at-last>16 or at-start>=4096:spans.append((start,last-start+1));start=at
                last=at
        if start is not None:spans.append((start,last-start+1))
    after={'appFw.so':ap_result,'cpapp-b.bin':bytes(result)};before={'appFw.so':ap,'cpapp-b.bin':cp}
    regions={'appFw.so':ap_spans,'cpapp-b.bin':spans}
    f=firmware.transition(before,after,regions)
    r=firmware.transition(after,before,regions)
    identify(after['appFw.so'],after['cpapp-b.bin'])
    if firmware.apply(after,r)!=before:raise ValueError('Complete table inverse differs')
    return f,r,after
