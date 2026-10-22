"""Byte-based current -> initial rollback workers, without source SHA gates."""
import json
from pathlib import Path
from . import checkpoint, nameworker, resources, worker
from .nativebuild import ROOT, compile_worker

def differences(before,after):
    if len(before)!=len(after):raise ValueError('Checkpoint program length differs; cannot restore in place')
    # Skip unchanged pages in C; inspect bytes only in differing pages.
    for base in range(0,len(before),4096):
        a,b=before[base:base+4096],after[base:base+4096]
        if a==b:continue
        changed=[i for i,(x,y) in enumerate(zip(a,b)) if x!=y]
        start=end=changed[0]
        for at in changed[1:]:
            if at-end>16:
                yield base+start,a[start:end+1],b[start:end+1]
                start=at
            end=at
        yield base+start,a[start:end+1],b[start:end+1]

def build_programs(current,target,out,zig=None,*,checkpoint_namespace=True,
                   payload_limit=18000,require_single=False,window_priority=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    groups=[];group=[];size=0;all_spans=[]
    if not 1<=payload_limit<=48000:raise ValueError('Native payload limit must be 1..48000')
    # CP first, as in the existing project installer. No firmware hashes.
    for chip,name in [(1,'cpapp-b.bin'),(0,'appFw.so')]:
        for at,old,new in differences(current[name],target[name]):
            all_spans.append((chip,at,old,new))
    if window_priority is not None:all_spans.sort(key=window_priority)
    if require_single and sum(2*len(old) for _,_,old,_ in all_spans)>payload_limit:
        raise ValueError('Experimental CP edits must fit a single native execution')
    for chip,at,old,new in all_spans:
        if group and size+2*len(old)>payload_limit:
            groups.append(group);group=[];size=0
        group.append((chip,at,old,new));size+=2*len(old)
    if group:groups.append(group)
    result=[]
    for number,spans in enumerate(groups):
        rows=[];lines=['#define BYTE_WINDOWS_ONLY 1']
        if checkpoint_namespace:lines.extend([
            '#define INSTALL_REQUEST "/tmp/jiritsu/checkpoint.program.request"',
            '#define INSTALL_RESULT "/tmp/jiritsu/checkpoint.program.result"'])
        for i,(chip,at,old,new) in enumerate(spans):
            lines.extend([f'static const u8 old_{i}[]='+cbytes(old)+';',f'static const u8 new_{i}[]='+cbytes(new)+';'])
            rows.append('{'+f'{at}UL,{len(old)},{chip},old_{i},new_{i}'+'}')
        lines.extend(['static const struct Window windows[]={'+','.join(rows)+'};',
            f'static const u32 window_count={len(rows)};',
            'static const u64 file_sizes[]={'+','.join(str(len(current[n]))+'UL' for n in worker.NAMES)+'};'])
        header=out/f'program-{number}.private.h';header.write_text('\n'.join(lines)+'\n',encoding='ascii')
        path=out/f'program-{number}.so'
        compile_worker(ROOT/'src/fl23/native/installer.c',header,path,zig,fingerprints=False)
        result.append({'path':str(path),'windows':len(rows),'sizes':[len(current[n]) for n in worker.NAMES]})
    return result

def cbytes(data):return '{'+','.join(map(str,data))+'}'

def build_names(current,target,out,identifier,zig=None,*,defer_busy_readonly=False):
    files=[];plans=[]
    for name in nameworker.filenames():
        a,b=target['resources/'+name],current['resources/'+name]
        if a==b:continue
        files.append(name);plans.append(checkpoint.name_inverse(a,b))
    if not files:return None
    q=json.dumps
    lines=['#define CHECKPOINT_BYTES 1', '#define CHECKPOINT_STREAM_RESTORE 1',
        '#define NAMES_REQUEST "/tmp/jiritsu/checkpoint.names.request"',
        '#define NAMES_RESULT "/tmp/jiritsu/checkpoint.names.result"',
        'static const struct Asset assets[]={'+','.join('{'+q(n)+','+str(p['before_bytes'])+',{0},{0}}' for n,p in zip(files,plans))+'};',
        f'static const u32 asset_count={len(files)};',
        'static const u32 after_sizes[]={'+','.join(str(p['after_bytes']) for p in plans)+'};',
        'static const u32 old_counts[]={'+','.join(str(p['before_count']) for p in plans)+'};',
        'static const u32 label_ids[]={'+','.join(str(r)+'U' for r in resources.LABEL_IDS)+'};',
        'static const unsigned short old_pointers[68][6]={'+','.join(cbytes([c['before_pointer'] for c in p['changes']]) for p in plans)+'};',
        'static const u8 names[6][64]={{0}};',
        'static const u32 selected_mask=63;',
        'static const char backup_prefix[]='+q('/usr/share/app/.a7c2-checkpoint-'+identifier+'-')+';',
        'static const u32 original_uid=57285,original_gid=1000;']
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    header=out/'names.private.h';header.write_text('\n'.join(lines)+'\n',encoding='ascii')
    path=out/'names.so';compile_worker(ROOT/'src/looks/native/names.c',header,path,zig,fingerprints=False)
    return {'path':str(path),'count':len(files),'files':files,'defer_busy_readonly':defer_busy_readonly}

def build_purge(out,identifier,zig=None):
    """Mode-5-only names worker: remove backups left by earlier project jobs."""
    files=nameworker.filenames();q=json.dumps
    lines=['#define CHECKPOINT_BYTES 1','#define CHECKPOINT_STREAM_RESTORE 1','#define NAMES_PURGE 1',
        '#define NAMES_REQUEST "/tmp/jiritsu/checkpoint.names.request"',
        '#define NAMES_RESULT "/tmp/jiritsu/checkpoint.names.result"',
        'static const struct Asset assets[]={'+','.join('{'+q(n)+',0,{0},{0}}' for n in files)+'};',
        f'static const u32 asset_count={len(files)};',
        'static const u32 after_sizes[68]={0};','static const u32 old_counts[68]={0};',
        'static const u32 label_ids[]={'+','.join(str(r)+'U' for r in resources.LABEL_IDS)+'};',
        'static const unsigned short old_pointers[68][6]={{0}};',
        'static const u8 names[6][64]={{0}};','static const u32 selected_mask=0;',
        'static const char backup_prefix[]='+q('/usr/share/app/.a7c2-checkpoint-'+identifier+'-')+';',
        'static const u32 original_uid=57285,original_gid=1000;']
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    header=out/'names.private.h';header.write_text('\n'.join(lines)+'\n',encoding='ascii')
    path=out/'purge.so';compile_worker(ROOT/'src/looks/native/names.c',header,path,zig,fingerprints=False)
    return {'path':str(path),'count':len(files),'purge':True}

def purge_report(raw,build):
    if len(raw)!=nameworker.REPORT.size:raise ValueError('Incomplete backup cleanup report')
    v=nameworker.REPORT.unpack(raw)
    if (v[:5]!=(b'A7NMR001',1,5,9,build['count']) or any(v[i] for i in (5,6,7,8,9,10,17))
        or v[11]<=0 or any(v[13:16]) or v[16]>v[12]):
        raise ValueError('旧任务名称备份清理未完成，相机名称文件没有改动；请完整断电重开后再点恢复。'
                         'Backup cleanup incomplete: '+repr(v[:18]))
    return {'mode':5,'matched':v[12],'removed':v[16]}

def names_completed_mount_busy(raw,mode,build):
    if len(raw)!=nameworker.REPORT.size or mode!=2:return False
    v=nameworker.REPORT.unpack(raw)
    return (v[:5]==(b'A7NMR001',1,2,9,build['count']) and v[5]==v[8]==-16
        and all(v[i]==0 for i in (6,7,9,10,13,14,17)) and v[11]>0
        and v[15]==build['count'] and v[12]<=build['count'] and v[16]<=build['count'])

def program_report(raw,mode,build):
    if len(raw)!=240:raise ValueError('Incomplete checkpoint program report')
    v=worker.REPORT.unpack_from(raw)
    if (v[:4]!=(b'A7IRP001',1,mode,9) or any(v[i] for i in range(5,11))
        or v[4]!=(build['windows'] if mode else 0) or list(v[14:16])!=build['sizes']
        or any(v[i]<=0 for i in (11,12,13))):
        raise ValueError('Checkpoint program operation incomplete: '+repr(v))
    return {'mode':mode,'windows':v[4]}

REBOOT='请完整断电重开（拔 USB、关机、取下电池至少 1 分钟后装回开机），再接回 USB 点同一个恢复按钮。'


def names_failure_detail(v,mode,build,raw):
    """User guidance for a failed name operation; the native report stays appended."""
    if v[5]==-28 and mode==2:
        return ('相机 /usr 分区的临时空间用完了：已恢复 %d/%d 个名称文件，程序和已恢复的部分保持不变，'
                '相机可以正常开机使用。旧文件占用的空间要断电后才释放。' % (v[15],build['count']) + REBOOT +
                '只会处理剩下的部分。')
    if v[5]==-28:
        return '写入前检查发现相机 /usr 分区临时空间不足，本次没有写入。' + REBOOT
    if v[5]==-30 and v[3]==1:
        return ('相机 /usr 分区仍处于可写挂载，通常是上一次操作后还没有完整断电重开；本次没有写入。' + REBOOT)
    if names_completed_mount_busy(raw,mode,build):
        return '名称内容已完成，但只读挂载忙碌；需要完成设置与重新加载准备后再重开核对。'
    return ''


def names_report(raw,mode,build):
    if build.get('defer_busy_readonly') and names_completed_mount_busy(raw,mode,build):
        return {'mode':mode,'restored':build['count'],'readonly_verified':False,'readonly_deferred_busy':True}
    if len(raw)!=nameworker.REPORT.size:raise ValueError('Incomplete checkpoint names report')
    v=nameworker.REPORT.unpack(raw)
    if (v[:5]!=(b'A7NMR001',1,mode,9,build['count']) or any(v[i] for i in (5,6,7,8,9,10,17))
        or v[11]<=0 or any(n>build['count'] for n in v[12:17])
        or (mode==4 and any(v[12:17])) or (mode==2 and any(v[13:15]))):
        raise ValueError(names_failure_detail(v,mode,build,raw) + 'Checkpoint name operation incomplete: '+repr(v[:18]))
    return {'mode':mode,'restored':v[15]}
