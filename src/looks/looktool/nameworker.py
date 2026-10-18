"""Prepare and verify the separate, atomic, job-pinned name transaction."""
import json,re,struct
from pathlib import Path
from . import firmware,resources
from .nativebuild import ROOT,compile_worker

REPORT=struct.Struct('<8sIIII7q6I32s')

def filenames():
    names=json.loads((ROOT/'src/looks/assets/resource-files.json').read_text(encoding='utf-8'))
    if len(names)!=68 or len(set(names))!=68 or any(not re.fullmatch(r'string_[a-z]+_(horizontal|vertical)\.uxc',n) for n in names):raise ValueError('Resource allowlist differs')
    return names

def prepare(sources,names,ap,job_id,out,zig=None,*,target_ap=None,label_ids=resources.LABEL_IDS):
    if set(sources)!=set(filenames()):raise ValueError('All 68 complete resource sources are required')
    if not re.fullmatch(r'[a-f0-9]{16}',job_id):raise ValueError('Invalid resource transaction ID')
    out=Path(out);out.mkdir(parents=True,exist_ok=True);target={};specs=[];pointers=[]
    q=lambda s:json.dumps(s,ensure_ascii=True)
    cbytes=lambda b:'{'+','.join(map(str,b))+'}'
    for filename in filenames():
        raw=sources[filename];parsed=resources.decode(raw)
        if parsed['count'] not in [2860,2866] or parsed['group']!=5:raise ValueError('Unsupported resource source layout')
        changed,plan=resources.rename(raw,names,label_ids)
        if resources.inverse(changed,plan)!=raw:raise ValueError('Resource inverse differs')
        target[filename]=changed;pointers.append([parsed['entries'].get(rid,{}).get('pointer',65535) for rid in label_ids])
        specs.append({'file':filename,'before_bytes':len(raw),'after_bytes':len(changed),'before_sha256':firmware.sha(raw),'after_sha256':firmware.sha(changed),'inverse':plan})
    lines=['static const struct Asset assets[]={'+','.join('{'+q(s['file'])+','+str(s['before_bytes'])+','+cbytes(bytes.fromhex(s['before_sha256']))+','+cbytes(bytes.fromhex(s['after_sha256']))+'}' for s in specs)+'};',
        'static const u32 asset_count='+str(len(specs))+';',
        'static const u32 after_sizes[]={'+','.join(str(s['after_bytes']) for s in specs)+'};',
        'static const u32 old_counts[]={'+','.join(str(s['inverse']['before_count']) for s in specs)+'};',
        'static const u32 label_ids[]={'+','.join(str(rid)+'U' for rid in label_ids)+'};',
        'static const unsigned short old_pointers[68][6]={'+','.join('{'+','.join(map(str,row))+'}' for row in pointers)+'};',
        'static const u8 names[6][64]={'+','.join(cbytes(names.get(slot,'ST').encode('utf-8')+b'\0') for slot in range(1,7))+'};',
        'static const u32 selected_mask='+str(sum(1<<(slot-1) for slot in names))+';',
        'static const char backup_prefix[]='+q('/usr/share/app/.a7c2-lut-'+job_id+'-')+';',
        # Pinned official 2.01 filesystem ownership, retained by prior atomic
        # installers. Root is the worker's euid, not the files' owner.
        'static const u32 original_uid=57285,original_gid=1000;',
        'static const u64 ap_size='+str(len(ap))+'UL;',
        'static const u8 ap_plain_hash[32]='+cbytes(bytes.fromhex(firmware.sha(ap)))+';',
        'static const u8 ap_named_hash[32]='+cbytes(bytes.fromhex(firmware.sha(target_ap if target_ap is not None else ap)))+';']
    header=out/'names.private.h';header.write_text('\n'.join(lines)+'\n',encoding='ascii',newline='\n')
    destination=out/'names.so';build=compile_worker(ROOT/'src/looks/native/names.c',header,destination,zig)
    build.update(path=str(destination),AP=firmware.sha(ap),target_AP=firmware.sha(target_ap if target_ap is not None else ap),count=len(specs),files=specs,job_id=job_id)
    return target,build

def validate(raw,mode,build):
    if len(raw)!=REPORT.size or mode not in (0,1,2,3):raise ValueError('Invalid name result ABI')
    values=REPORT.unpack(raw)
    count=build['count']
    if not 1<=count<=68 or len(build['files'])!=count:raise ValueError('Invalid pinned resource count')
    expected_ap=build.get('target_AP',build['AP']) if mode==3 else build['AP']
    if values[:5]!=(b'A7NMR001',1,mode,9,count) or any(values[i] for i in [5,6,7,8,9,10,17]) or values[18].hex()!=expected_ap:
        raise ValueError('Native name transaction incomplete; inspect existing result without replay')
    if values[11]<=0 or any(n>count for n in values[12:17]):raise ValueError('Native name PID/count bounds differ')
    if mode==0 and any(values[12:17]):raise ValueError('Read-only name preflight reported a write')
    if mode==1 and (values[12:15]!=(count,count,count) or any(values[15:17])):raise ValueError('Native name commit counts differ')
    if mode==2 and any(values[13:15]):raise ValueError('Name restoration reported a forward commit')
    if mode==3 and any(values[12:16]):raise ValueError('Name cleanup reported resource writes')
    return {'native_verified':True,'mode':mode,'files':count,'restored':values[15]}
