"""Embed a repacked C2 updater into a copy of its acquired FAT12 partition.

No FAT formatting, allocation changes or device writes. The original file
lengths, both FATs, directory entries, kernel, slack and partition tail remain.
"""
from pathlib import Path
import argparse
import hashlib
import io
import json
import math
import re
import struct
import sys


def embed(source: bytes, replacement: bytes):
    u16=lambda p:struct.unpack_from('<H',source,p)[0]
    u32=lambda p:struct.unpack_from('<I',source,p)[0]
    ss,spc,reserved,nfat,root_entries,spf=u16(11),source[13],u16(14),source[16],u16(17),u16(22)
    total=u16(19) or u32(32)
    root_start=reserved+nfat*spf
    root_sectors=math.ceil(root_entries*32/ss)
    data_start=root_start+root_sectors
    count=(total-data_start)//spc
    if (ss,spc,nfat)!=(512,32,2) or count>=4085 or total*ss>len(source):
        raise ValueError('Expected the C2 FAT12 geometry with two FATs and 16 KiB clusters')
    fat=source[reserved*ss:(reserved+spf)*ss]
    if fat!=source[(reserved+spf)*ss:(reserved+2*spf)*ss]:
        raise ValueError('Original FAT copies differ')
    def chain(first):
        found=[];seen=set();cluster=first
        while True:
            if cluster in seen or not 2<=cluster<count+2:
                raise ValueError('Invalid original FAT chain')
            seen.add(cluster);found.append(cluster)
            p=cluster+cluster//2
            value=int.from_bytes(fat[p:p+2],'little')
            cluster=value>>4 if cluster&1 else value&0xfff
            if cluster>=0xff8:return found
    def position(c):return (data_start+(c-2)*spc)*ss
    def find(directory,name):
        for at in range(0,len(directory),32):
            item=directory[at:at+32]
            if item[0]==0:break
            if item[0]==0xe5 or item[11]==15:continue
            short=item[:8].decode('ascii').rstrip()
            ext=item[8:11].decode('ascii').rstrip()
            if (short+('.'+ext if ext else '')).lower()==name.lower():return item
        raise ValueError('Original FAT file missing: '+name)
    def contents(entry):
        data=b''.join(source[position(c):position(c)+spc*ss]
                      for c in chain(int.from_bytes(entry[26:28],'little')))
        return data[:int.from_bytes(entry[28:32],'little')]
    root=source[root_start*ss:(root_start+root_sectors)*ss]
    boot_entry=find(root,'boot')
    boot=b''.join(source[position(c):position(c)+spc*ss]
                  for c in chain(int.from_bytes(boot_entry[26:28],'little')))
    initrd_entry=find(boot,'initrd.img')
    kernel_entry=find(boot,'vmlinux.bin')
    p1_entry=find(root,'p1chksum')
    old_initrd=contents(initrd_entry)
    if len(replacement)>len(old_initrd):
        raise ValueError('Repacked initrd exceeds the original file allocation')
    replacement=replacement.ljust(len(old_initrd),b'\0')
    p1=contents(p1_entry)
    # Validate the complete boot checksum manifest before preserving it. Only
    # checking the entry we replace would carry an already-bad kernel record
    # into an apparently verified installation candidate.
    records={}
    for line in p1.splitlines():
        if not line:continue
        match=re.fullmatch(rb'([0-9a-f]{32})  \./boot/(vmlinux\.bin|initrd\.img)',line)
        if match is None or match[2] in records:
            raise ValueError('Original updater boot checksum layout differs')
        records[match[2]]=match[1].decode('ascii')
    if set(records)!={b'vmlinux.bin',b'initrd.img'}:
        raise ValueError('Original updater boot checksum records are incomplete')
    for name,data in ((b'vmlinux.bin',contents(kernel_entry)),(b'initrd.img',old_initrd)):
        if records[name]!=hashlib.md5(data).hexdigest():
            raise ValueError('Original '+name.decode('ascii')+' checksum record does not match its contents')
    matches=list(re.finditer(rb'([0-9a-f]{32})(  \./boot/initrd\.img)',p1))
    if len(matches)!=1 or matches[0][1].decode()!=hashlib.md5(old_initrd).hexdigest():
        raise ValueError('Original initrd checksum record does not match its contents')
    at=matches[0].start()
    p1=p1[:at]+hashlib.md5(replacement).hexdigest().encode()+p1[at+32:]
    candidate=bytearray(source);allowed=[]
    for entry,data in [(initrd_entry,replacement),(p1_entry,p1)]:
        if int.from_bytes(entry[28:32],'little')!=len(data):
            raise ValueError('Replacement changes a directory file size')
        done=0
        for cluster in chain(int.from_bytes(entry[26:28],'little')):
            at=position(cluster);size=min(spc*ss,len(data)-done)
            candidate[at:at+size]=data[done:done+size]
            allowed.append((at,at+size));done+=size
        if done!=len(data):raise ValueError('Original allocation is shorter than its file size')
    inverse=bytearray(candidate)
    for begin,end in allowed:inverse[begin:end]=source[begin:end]
    assert inverse==source
    return bytes(candidate),dict(camera_io=False,device_ready=False,
        original_fat_and_directories_preserved=True,partition_tail_preserved=True,
        exact_inverse_verified=True,changed_sectors=[at//512 for at in range(0,len(source),512)
            if source[at:at+512]!=candidate[at:at+512]])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--partition-image',type=Path,required=True)
    parser.add_argument('--initrd',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    original=args.partition_image.read_bytes()
    candidate,report=embed(original,args.initrd.read_bytes())
    # Independent pre-existing reader verifies the actual file contents.
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src/desktopapp/vendor'))
    from fwtool.archive import fat
    actual={e.path:e.contents.read() for e in fat.readFat(io.BytesIO(candidate))
            if e.path in ('/boot/initrd.img','/p1chksum')}
    assert actual['/boot/initrd.img'].startswith(args.initrd.read_bytes())
    with args.output.open('xb') as out:out.write(candidate)
    report.update(source_sha256=hashlib.sha256(original).hexdigest(),
                  candidate_sha256=hashlib.sha256(candidate).hexdigest())
    args.output.with_suffix('.private.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='changed_sectors'},indent=2))


if __name__=='__main__':main()
