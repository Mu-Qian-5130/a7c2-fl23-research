import hashlib
import struct
import pytest
from desktopapp.updaterimage import module


def fixture():
    raw=bytearray(25100288)
    struct.pack_into('<H',raw,11,512);raw[13]=32;struct.pack_into('<H',raw,14,1)
    raw[16]=2;struct.pack_into('<H',raw,17,512);struct.pack_into('<H',raw,19,38864);struct.pack_into('<H',raw,22,32)
    fat=bytearray(32*512);fat[:3]=b'\xf8\xff\xff'
    for cluster in range(2,6):
        at=cluster+cluster//2;word=int.from_bytes(fat[at:at+2],'little')
        word=(word&15)|(0xfff<<4)if cluster&1 else(word&0xf000)|0xfff
        fat[at:at+2]=word.to_bytes(2,'little')
    raw[512:512+len(fat)]=fat;raw[512+len(fat):512+2*len(fat)]=fat
    root=65*512;data=97*512
    def entry(at,name,cluster,size,kind=0):
        raw[at:at+11]=name;raw[at+11]=kind;struct.pack_into('<H',raw,at+26,cluster);struct.pack_into('<I',raw,at+28,size)
    initrd=b'original updater RAM disk'*20;kernel=b'original updater kernel'*20
    manifest=hashlib.md5(kernel).hexdigest().encode()+b'  ./boot/vmlinux.bin\n'+hashlib.md5(initrd).hexdigest().encode()+b'  ./boot/initrd.img\n'
    entry(root,b'BOOT       ',2,0,16);entry(root+32,b'P1CHKSUM   ',5,len(manifest))
    entry(data,b'INITRD  IMG',3,len(initrd));entry(data+32,b'VMLINUX BIN',4,len(kernel))
    offsets={'initrd':data+16384,'kernel':data+2*16384,'manifest':data+3*16384}
    for key,payload in [('initrd',initrd),('kernel',kernel),('manifest',manifest)]:raw[offsets[key]:offsets[key]+len(payload)]=payload
    return bytes(raw),offsets,initrd,kernel,manifest


def test_valid_manifest_keeps_kernel_geometry_and_tail():
    source,at,initrd,kernel,manifest=fixture();replacement=b'N'*len(initrd)
    result,report=module('embed_updater').embed(source,replacement)
    assert result[at['kernel']:at['kernel']+len(kernel)]==kernel
    assert result[:97*512]==source[:97*512]
    assert result[38864*512:]==source[38864*512:]
    wanted=manifest.replace(hashlib.md5(initrd).hexdigest().encode(),hashlib.md5(replacement).hexdigest().encode())
    assert result[at['manifest']:at['manifest']+len(wanted)]==wanted
    assert report['exact_inverse_verified']


@pytest.mark.parametrize('which',['kernel','initrd','manifest'])
def test_corrupt_existing_boot_file_or_checksum_is_rejected(which):
    source,at,initrd,_,_=fixture();raw=bytearray(source);raw[at[which]]^=1
    with pytest.raises(ValueError,match='checksum'):
        module('embed_updater').embed(bytes(raw),b'N'*len(initrd))


@pytest.mark.parametrize('kind',['unknown','missing','duplicate'])
def test_invalid_manifest_record_set_is_rejected(kind):
    source,at,initrd,kernel,manifest=fixture();raw=bytearray(source)
    lines=manifest.splitlines(keepends=True)
    changed={'unknown':manifest.replace(b'vmlinux.bin',b'initrdx.img'),
             'missing':lines[1],
             'duplicate':lines[1]*2}[kind]
    raw[at['manifest']:at['manifest']+len(changed)]=changed
    struct.pack_into('<I',raw,65*512+32+28,len(changed))
    with pytest.raises(ValueError,match='checksum'):
        module('embed_updater').embed(bytes(raw),b'N'*len(initrd))
