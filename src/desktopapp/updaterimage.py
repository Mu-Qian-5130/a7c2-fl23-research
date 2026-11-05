"""Patch the C2 updater in its existing FAT/SquashFS allocations on the host."""
import importlib.util
import io
from pathlib import Path
import struct
import sys
import zlib
from .paths import ROOT

PARTITION_BYTES=25100288


def module(name):
    spec=importlib.util.spec_from_file_location('a7c2_'+name,ROOT/'dev/firmware'/ (name+'.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def archives():
    sys.path.insert(0,str(ROOT/'src/desktopapp/vendor'))
    from fwtool.archive import fat,squashfs
    return fat,squashfs


def partition_files(raw):
    fat,_=archives()
    return {f.path:f.contents.read() for f in fat.readFat(io.BytesIO(raw))
            if f.path in ('/boot/initrd.img','/p1chksum')}


def squash_files(raw):
    _,sq=archives()
    return {f.path:(f.mode,f.uid,f.gid,f.mtime,f.size,
        f.contents.read() if f.contents is not None else None) for f in sq.readSquashfs(io.BytesIO(raw))}


def fragment_map(raw,wanted):
    """Locate only existing fragment-backed files; no inode/table reconstruction."""
    _,s=archives();super=s.SquashfsSuper.unpack(raw[:s.SquashfsSuper.size])
    if super.magic!=b'hsqs' or super.compressionId!=1 or (super.versionMajor,super.versionMinor)!=(4,0):
        raise ValueError('Expected the C2 gzip SquashFS updater')
    def metadata(at,offset,size):
        data=bytearray()
        while len(data)<offset+size:
            header=int.from_bytes(raw[at:at+2],'little');at+=2
            encoded=raw[at:at+(header&0x7fff)];at+=len(encoded)
            data.extend(encoded if header&0x8000 else zlib.decompress(encoded))
        return bytes(data[offset:offset+size])
    per=8192//s.SquashfsFragmentBlockEntry.size
    fragments=[]
    for index in range((super.fragmentEntryCount+per-1)//per):
        at=struct.unpack_from('<Q',raw,super.fragmentTableStart+8*index)[0]
        data=metadata(at,0,min(per,super.fragmentEntryCount-index*per)*s.SquashfsFragmentBlockEntry.size)
        fragments += [s.SquashfsFragmentBlockEntry.unpack(data[n:n+s.SquashfsFragmentBlockEntry.size])
                      for n in range(0,len(data),s.SquashfsFragmentBlockEntry.size)]
    found={}
    def inode(block,offset,path=''):
        at=super.inodeTableStart+block
        header=s.SquashfsInodeHeader.unpack(metadata(at,offset,s.SquashfsInodeHeader.size))
        offset+=s.SquashfsInodeHeader.size
        if header.inodeType in (s.squashfsInodeTypeBasicDirectory,s.squashfsInodeTypeExtendedDirectory):
            kind=s.SquashfsBasicDirectoryInode if header.inodeType==s.squashfsInodeTypeBasicDirectory else s.SquashfsExtendedDirectoryInode
            value=kind.unpack(metadata(at,offset,kind.size))
            directory=io.BytesIO(metadata(super.directoryTableStart+value.dirBlockStart,value.blockOffset,value.fileSize-3))
            while data:=directory.read(s.SquashfsDirectoryHeader.size):
                row=s.SquashfsDirectoryHeader.unpack(data)
                for _ in range(row.count+1):
                    entry=s.SquashfsDirectoryEntry.unpack(directory.read(s.SquashfsDirectoryEntry.size))
                    name=directory.read(entry.nameSize+1).decode('ascii')
                    child=path+'/'+name
                    if child in wanted or any(p.startswith(child+'/') for p in wanted):inode(row.start,entry.offset,child)
        elif path in wanted:
            if header.inodeType not in (s.squashfsInodeTypeBasicFile,s.squashfsInodeTypeExtendedFile):
                raise ValueError('Updater target is not a regular file: '+path)
            kind=s.SquashfsBasicFileInode if header.inodeType==s.squashfsInodeTypeBasicFile else s.SquashfsExtendedFileInode
            value=kind.unpack(metadata(at,offset,kind.size))
            if not value.fileSize<super.blockSize or value.fragmentBlockIndex==0xffffffff:
                raise ValueError('Updater target is not in its supported fragment layout: '+path)
            fragment=fragments[value.fragmentBlockIndex]
            found[path]=dict(fragment=value.fragmentBlockIndex,offset=value.blockOffset,length=value.fileSize,
                start=fragment.start,stored=fragment.size&0xffffff,plain=bool(fragment.size&(1<<24)))
    inode((super.rootInodeRef>>16)&0xffffffff,super.rootInodeRef&0xffff)
    if set(found)!=set(wanted):raise ValueError('Updater public key or verification libraries are missing')
    return found


def compress_exact(data,size):
    """Fill the original encoded length with valid empty DEFLATE blocks.

    Bytes after a zlib stream are deliberately not used: Linux SquashFS requires
    the supplied input to be consumed. Empty stored blocks precede the stream's
    first data block, so the decoder consumes every byte without changing output.
    """
    for level in (9,8,7,6):
        for mem in (9,8,7,6,5,4):
            for strategy in (zlib.Z_DEFAULT_STRATEGY,zlib.Z_FILTERED,zlib.Z_FIXED):
                compressor=zlib.compressobj(level,zlib.DEFLATED,15,mem,strategy)
                encoded=compressor.compress(data)+compressor.flush()
                extra=size-len(encoded)
                if extra<0 or extra%5:continue
                packed=encoded[:2]+b'\0\0\0\xff\xff'*(extra//5)+encoded[2:]
                decoder=zlib.decompressobj();actual=decoder.decompress(packed)+decoder.flush()
                if actual!=data or not decoder.eof or decoder.unused_data:raise ValueError('Updater fragment roundtrip differs')
                return packed
    raise ValueError('更新器压缩块无法保留原分配长度，本次未生成安装镜像。')


def build(original,public):
    from Cryptodome.PublicKey import RSA
    if len(original)!=PARTITION_BYTES:raise ValueError('C2 updater partition size differs')
    key=RSA.import_key(public)
    if key.has_private() or key.size_in_bits()!=2048:raise ValueError('Only an RSA-2048 public key may enter the camera image')
    members=partition_files(original);initrd=members['/boot/initrd.img']
    before=squash_files(initrd);policy=module('trust_image')
    targets={'/etc/VerificationKey.pem',*('/usr/lib/'+n for n in policy.LIBRARIES)}
    mapping=fragment_map(initrd,targets)
    key_size=mapping['/etc/VerificationKey.pem']['length']
    if len(public)>key_size:raise ValueError('Application public key exceeds the existing updater key record')
    public=public+b'\n'*(key_size-len(public))
    changes={'/etc/VerificationKey.pem':public};libraries={}
    for name in policy.LIBRARIES:
        path='/usr/lib/'+name
        changes[path],libraries[name]=policy.pin_library(before[path][-1],public)
    fragments={}
    for path,payload in changes.items():
        row=mapping[path]
        if len(payload)!=row['length']:raise ValueError('Updater file length changed')
        index=row['fragment']
        if index not in fragments:
            encoded=initrd[row['start']:row['start']+row['stored']]
            fragments[index]=dict(row,data=bytearray(encoded if row['plain'] else zlib.decompress(encoded)))
        data=fragments[index]['data'];at=row['offset']
        if data[at:at+row['length']]!=before[path][-1]:raise ValueError('Updater fragment location differs')
        data[at:at+row['length']]=payload
    patched=bytearray(initrd)
    for row in fragments.values():
        packed=bytes(row['data']) if row['plain'] else compress_exact(bytes(row['data']),row['stored'])
        if len(packed)!=row['stored']:raise ValueError('Updater fragment allocation changed')
        patched[row['start']:row['start']+row['stored']]=packed
    after=squash_files(bytes(patched))
    if set(before)!=set(after):raise ValueError('Updater filesystem members changed')
    for path,value in before.items():
        expected=(*value[:-1],changes[path]) if path in changes else value
        if after[path]!=expected:raise ValueError('Updater member or metadata readback differs: '+path)
    candidate,report=module('embed_updater').embed(original,bytes(patched))
    if partition_files(candidate)['/boot/initrd.img']!=patched:raise ValueError('Updater FAT readback differs')
    report.update(schema='a7c2-trust-image/1',files=sorted(changes),libraries=libraries,
        compressed_blocks=len(fragments),filesystem_allocations_preserved=True,
        private_key_in_camera_files=False,installer_image_prepared=True,physical_tested=False,
        updater_boot_verified=False)
    return candidate,report


def spans(before,after,limit=16384):
    if len(before)!=PARTITION_BYTES or len(after)!=len(before):raise ValueError('Updater partition length differs')
    at=0
    while at<len(before):
        if before[at:at+512]==after[at:at+512]:at+=512;continue
        start=at;at+=512
        while at<len(before) and at-start<limit and before[at:at+512]!=after[at:at+512]:at+=512
        yield start,before[start:at],after[start:at]


def checksum_sectors(raw):
    """Locate the checksum file from this image, never from a fixed R5 offset."""
    ss=struct.unpack_from('<H',raw,11)[0];spc=raw[13]
    reserved=struct.unpack_from('<H',raw,14)[0];spf=struct.unpack_from('<H',raw,22)[0]
    entries=struct.unpack_from('<H',raw,17)[0];start=reserved+raw[16]*spf
    directory=raw[start*ss:start*ss+entries*32]
    row=next((directory[n:n+32] for n in range(0,len(directory),32)
              if directory[n:n+11]==b'P1CHKSUM   '),None)
    if row is None:raise ValueError('Updater checksum file not found')
    left=struct.unpack_from('<I',row,28)[0];cluster=struct.unpack_from('<H',row,26)[0]
    fat=raw[reserved*ss:(reserved+spf)*ss];data_start=start+(entries*32+ss-1)//ss
    result=set();seen=set()
    while left:
        if cluster in seen or not 2<=cluster<0xff8:raise ValueError('Updater checksum allocation differs')
        seen.add(cluster);sector=data_start+(cluster-2)*spc;count=min(left,spc*ss)
        result.update(range(sector,sector+(count+ss-1)//ss));left-=count
        word=int.from_bytes(fat[cluster+cluster//2:cluster+cluster//2+2],'little')
        cluster=(word>>4 if cluster&1 else word)&0xfff
    return result


def write_plan(original,current,target):
    checksums=checksum_sectors(original)
    rows=list(spans(current,target))
    return sorted(rows,key=lambda row:(any(s in checksums for s in range(row[0]//512,(row[0]+len(row[1]))//512)),row[0]))
