"""Require exact preservation of TAR headers, padding, and trailing bytes."""
import io
import tarfile

import pytest
from desktopapp import firmwarearchive


def archive_bytes():
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w',format=tarfile.GNU_FORMAT)as archive:
        for name,payload in [('wbi',b'WBI2'+bytes(range(256))*2),('untouched',b'keep-this-file')]:
            member=tarfile.TarInfo(name);member.size=len(payload)
            member.uid=123;member.gid=456;member.mode=0o6754;member.mtime=1700000000
            member.uname='original-owner';member.gname='original-group'
            archive.addfile(member,io.BytesIO(payload))
    return stream.getvalue()+b'original trailing bytes retained exactly\xff'


def test_overlay_preserves_noncanonical_archive_bytes(tmp_path):
    original=archive_bytes()
    with tarfile.open(fileobj=io.BytesIO(original),mode='r:')as archive:
        member=archive.getmember('wbi');payload=archive.extractfile(member).read()
    revised=b'WBI3'+payload[4:]
    path=tmp_path/'wbi';path.write_bytes(revised);output=tmp_path/'result.tar'
    report=firmwarearchive.replace_members(io.BytesIO(original),{'wbi':path},output)
    expected=bytearray(original);expected[member.offset_data:member.offset_data+member.size]=revised
    assert output.read_bytes()==expected
    assert report['original_headers_padding_trailer_preserved']
    assert report['changed_members']==['wbi']


@pytest.mark.parametrize('name,payload',[('missing',b'none'),('wbi',b'changed-length')])
def test_invalid_overlay_stops_before_creating_output(tmp_path,name,payload):
    path=tmp_path/'replacement';path.write_bytes(payload);output=tmp_path/'output.tar'
    with pytest.raises(ValueError):firmwarearchive.replace_members(io.BytesIO(archive_bytes()),{name:path},output)
    assert not output.exists()
