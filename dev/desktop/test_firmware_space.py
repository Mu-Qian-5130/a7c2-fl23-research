"""Capacity accounting uses real image geometry, not source file sums."""
import struct
import pytest
from desktopapp import firmwarespace


def ext_image(path,*,free=30,reserved=5):
    data=bytearray(4096)
    struct.pack_into('<7I',data,1024,100,100,reserved,free,40,1,0)
    data[1080:1082]=b'\x53\xef'
    path.write_bytes(data)


def test_ext_blocks_and_inodes_with_reserved_space(tmp_path):
    image=tmp_path/'usr.img';ext_image(image)
    result=firmwarespace.inspect(image)
    assert result['total_bytes']==102400 and result['free_bytes']==30720
    assert result['unreserved_free_bytes']==25600 and result['free_inodes']==40


def test_fat12_counts_free_clusters_instead_of_file_length(tmp_path):
    raw=bytearray(20*512);struct.pack_into('<H',raw,11,512);raw[13]=1
    struct.pack_into('<H',raw,14,1);raw[16]=1
    struct.pack_into('<H',raw,17,16);struct.pack_into('<H',raw,19,20)
    struct.pack_into('<H',raw,22,1);raw[54:59]=b'FAT12'
    raw[512:515]=bytes.fromhex('f8ffff');raw[515:517]=bytes.fromhex('ff0f')
    image=tmp_path/'cp.img';image.write_bytes(raw)
    result=firmwarespace.inspect(image)
    assert result['clusters']==17 and result['free_clusters']==16 and result['free_bytes']==8192


def test_unknown_images_do_not_receive_invented_capacity(tmp_path):
    image=tmp_path/'unknown.img';image.write_bytes(bytes(2048))
    with pytest.raises(ValueError):firmwarespace.inspect(image)
