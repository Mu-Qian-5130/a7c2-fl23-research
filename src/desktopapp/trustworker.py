"""Compile/invoke the small temporary updater worker, with recorded outcomes."""
import json
from pathlib import Path
import struct
from .paths import ROOT

REPORT=struct.Struct('<8sIIIIQQQQqqqq')


def header(mode,offset,count,before=b'',after=b''):
    if mode not in (0,1,2) or count<=0 or count%512 or offset%512 or offset<0 or offset+count>25100288:
        raise ValueError('Invalid C2 updater partition range')
    if mode==0 and count>1048576:raise ValueError('Updater read chunk exceeds 1 MiB')
    if mode and (len(before)!=count or len(after)!=count or count>16384):raise ValueError('Invalid updater byte window')
    values=lambda data:'{'+','.join(str(x) for x in (data or b'\0'))+'}'
    return (f'#define TRUST_MODE {mode}\n#define TRUST_OFFSET {offset}UL\n#define TRUST_COUNT {count}UL\n'+
        'static const unsigned char trust_before[]='+values(before)+';\n'+
        'static const unsigned char trust_after[]='+values(after)+';\n')


def build(folder,mode,offset,count,before=b'',after=b'',zig=None):
    from looktool.nativebuild import compile_worker
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    config=folder/'trust.private.h';config.write_text(header(mode,offset,count,before,after),encoding='ascii')
    path=folder/'trust.so'
    compile_worker(ROOT/'src/camera_api/trust_partition.c',config,path,zig,fingerprints=False)
    return path


def parse(raw,mode,offset,count):
    if len(raw)!=REPORT.size:raise ValueError('Incomplete updater installer result; retain the job')
    row=REPORT.unpack(raw)
    if row[:3]!=(b'A7TRST01',1,mode) or row[5:8]!=(offset,count,25100288):
        raise ValueError('Updater installer result identity differs')
    result=dict(mode=mode,phase=row[3],writes=row[4],offset=row[5],count=row[6],capacity=row[7],
        completed=row[8],status=row[9],euid=row[10],close_status=row[11],sync_status=row[12])
    if result['phase']!=9 or any(result[k] for k in ('status','euid','close_status','sync_status')):
        raise ValueError('更新器操作未完成，请保留原始结果，不重复执行：'+json.dumps(result))
    if (mode in (0,2) and result['completed']!=count) or (mode!=2 and result['writes']):
        raise ValueError('Updater byte count/write outcome differs')
    return result


def invoke(camera,folder,mode,offset,count,before,after,record,save_raw,zig=None):
    from looktool.devicesession import invoke as native
    path=build(folder,mode,offset,count,before,after,zig);payload=[]
    def decode(raw):
        result=parse(raw,mode,offset,count)
        if mode==0:
            chunk=camera.temp_read('a7c2.trust.chunk')
            if len(chunk)!=count:raise ValueError('Updater backup chunk is incomplete')
            payload.append(chunk)
        return result
    result=native(camera,path.read_bytes(),stage='a7c2.trust.staged.so',request=None,result='a7c2.trust.result',
        contents=None,mode=mode,decode=decode,record=record,save_raw=save_raw,
        extras=('a7c2.trust.chunk',) if mode==0 else ())
    return payload[0] if mode==0 else result
