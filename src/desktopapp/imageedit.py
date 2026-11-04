"""Edit copies of firmware filesystem images; never opens block devices."""
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

from .paths import ROOT,write_json


def linux_path(path):
    path=Path(path).resolve()
    if sys.platform=='win32':return '/mnt/'+path.drive[0].lower()+path.as_posix()[2:]
    return str(path)


def fat_cp(image,replacement):
    """Replace the same-length CP file along its existing FAT12 chain."""
    payload=Path(replacement).read_bytes()
    with Path(image).open('r+b') as stream:
        head=stream.read(512)
        if head[54:59]!=b'FAT12':raise ValueError('Expected original FAT12 CP image')
        sector=struct.unpack_from('<H',head,11)[0];cluster_bytes=sector*head[13]
        fat_at=sector*struct.unpack_from('<H',head,14)[0]
        fat_size=sector*struct.unpack_from('<H',head,22)[0]
        root_at=fat_at+head[16]*fat_size;root_size=32*struct.unpack_from('<H',head,17)[0]
        data_at=root_at+((root_size+sector-1)//sector)*sector
        stream.seek(fat_at);table=stream.read(fat_size)
        stream.seek(root_at);directory=stream.read(root_size);entry=None
        for at in range(0,len(directory),32):
            row=directory[at:at+32]
            if row[:11]==b'CPAPP-B BIN':entry=row;break
        if entry is None:raise ValueError('CPAPP-B.BIN missing from original CP image')
        cluster=struct.unpack_from('<H',entry,26)[0];size=struct.unpack_from('<I',entry,28)[0]
        if size!=len(payload):raise ValueError('CP image update must retain original file size')
        seen=set();done=0
        while 2<=cluster<0xff8:
            if cluster in seen:raise ValueError('Cyclic CP FAT chain')
            seen.add(cluster);count=min(cluster_bytes,size-done)
            if count<=0:raise ValueError('CP FAT chain exceeds original file size')
            stream.seek(data_at+(cluster-2)*cluster_bytes);stream.write(payload[done:done+count]);done+=count
            at=cluster*3//2;word=int.from_bytes(table[at:at+2],'little')
            cluster=(word>>4 if cluster&1 else word)&0xfff
        if done!=size:raise ValueError('Incomplete original CP FAT chain')
        stream.flush();os.fsync(stream.fileno())


def edit_images(originals,files,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    result={}
    for role,rows in files.items():
        source=Path(originals)/(role+'.img');dest=output/(role+'.img')
        if not rows:result[role]=source;continue
        shutil.copyfile(source,dest);result[role]=dest
        if role=='cp':
            if set(rows)!={'/cpapp-b.bin'}:raise ValueError('Unexpected CP image file')
            fat_cp(dest,rows['/cpapp-b.bin']['source'])
        else:
            plan=output/(role+'-edits.private.json')
            write_json(plan,dict(image=linux_path(dest),files={p:(dict(delete=True) if row.get('delete') else
                dict(row,source=linux_path(row['source']))) for p,row in rows.items()}))
            helper=ROOT/'dev/firmware/edit_ext2.py'
            command=(['wsl','-d',os.environ.get('A7C2_WSL_DISTRO','Ubuntu-22.04'),'--','python3',linux_path(helper),linux_path(plan)]
                     if sys.platform=='win32' else [sys.executable,str(helper),str(plan)])
            if sys.platform!='win32' and getattr(sys,'frozen',False):
                python=shutil.which('python3')
                if not python or not shutil.which('debugfs') or not shutil.which('e2fsck'):
                    raise ValueError('本地映像构建需要 Linux Python 与 e2fsprogs；Windows 使用 WSL。当前 macOS 包未提供该构建环境。')
                command=[python,str(helper),str(plan)]
            done=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=300)
            (output/(role+'-debugfs.log')).write_text(done.stdout+'\n'+done.stderr,encoding='utf-8')
            if done.returncode:raise ValueError('Offline image edit failed: '+done.stderr[-2000:])
        # Independent reader must find every requested file with exact bytes.
        from .firmwarelocal import tools,stream_bytes
        _,_,ext2,fat=tools()
        found=set()
        with dest.open('rb') as image:
            for entry in (fat.readFat if role=='cp' else ext2.readExt2)(image):
                if entry.path in rows:
                    if rows[entry.path].get('delete'):raise ValueError('Deleted resource remains in edited image: '+entry.path)
                    try:actual=stream_bytes(entry.contents)
                    except Exception as exc:raise ValueError('Edited image readback failed: '+entry.path) from exc
                    if actual!=Path(rows[entry.path]['source']).read_bytes():
                        raise ValueError('Edited image readback differs: '+entry.path)
                    found.add(entry.path)
        if found!={name for name,row in rows.items() if not row.get('delete')}:raise ValueError('Edited image is missing requested files')
    return result
