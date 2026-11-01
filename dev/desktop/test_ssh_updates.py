"""SSH publication preserves preimages, verifies bytes and stops unknown results."""
import json
import shlex
from pathlib import Path

import pytest

from desktopapp import sshupdates


class Connection:
    def __init__(self,files,fail_publish=False):
        self.files=dict(files);self.commands=[];self.fail_publish=fail_publish
        self.boot='00000000-0000-0000-0000-000000000001'
    def read(self,path,missing=False):
        if path=='/proc/sys/kernel/random/boot_id':return self.boot.encode()+b'\n'
        if path=='/proc/self/mounts':return b'device /usr ext2 ro 0 0\ndevice /cp vfat ro 0 0\n'
        return self.files.get(path,b'') if missing else self.files[path]
    def execute(self,command,data=None):
        self.commands.append(command)
        if data is not None:self.files[shlex.split(command)[-1]]=data
        elif command.startswith('cat '):return self.files[shlex.split(command)[1]]
        elif command.startswith('mv -f '):
            parts=shlex.split(command)
            if self.fail_publish:raise TimeoutError('lost publication response')
            self.files[parts[3]]=self.files.pop(parts[2])
        return b''


def test_publish_reads_full_preimage_and_committed_bytes_then_requires_new_boot(tmp_path):
    source=tmp_path/'baseline';source.mkdir()
    (source/'baseline.private.json').write_text('{}');(source/'cpapp-b.bin').write_bytes(b'old CP')
    folder=tmp_path/'update'
    sshupdates.save_package({'/cp/cpapp-b.bin':(b'old CP',b'new CP')},folder,'looks',source_baseline=source)
    connection=Connection({'/cp/cpapp-b.bin':b'old CP'})
    result=sshupdates.apply(folder,connection)
    assert result['phase']=='AWAITING_RELOAD'
    assert connection.files['/cp/cpapp-b.bin']==b'new CP'
    assert 'mount -o remount,ro /cp' in connection.commands
    with pytest.raises(ValueError,match='冷启动'):sshupdates.verify_reload(folder,connection)
    connection.boot='00000000-0000-0000-0000-000000000002'
    result=sshupdates.verify_reload(folder,connection)
    assert result['phase']=='LOADED' and not result['physical_photo_verified']
    assert Path(result['next_baseline'],'cpapp-b.bin').read_bytes()==b'new CP'


def test_preimage_conflict_stops_before_remount_or_upload(tmp_path):
    folder=tmp_path/'update'
    sshupdates.save_package({'/cp/cpapp-b.bin':(b'expected',b'new')},folder,'looks',source_baseline=tmp_path/'baseline')
    connection=Connection({'/cp/cpapp-b.bin':b'another edit'})
    with pytest.raises(ValueError,match='基线不一致'):sshupdates.apply(folder,connection)
    assert not connection.commands
    assert json.loads((folder/'update.private.json').read_text(encoding='utf-8'))['phase']=='NEEDS_REVIEW'


def test_unknown_publication_is_not_replayed(tmp_path):
    folder=tmp_path/'update'
    sshupdates.save_package({'/cp/cpapp-b.bin':(b'old',b'new')},folder,'looks',source_baseline=tmp_path/'baseline')
    connection=Connection({'/cp/cpapp-b.bin':b'old'},fail_publish=True)
    with pytest.raises(TimeoutError):sshupdates.apply(folder,connection)
    before=list(connection.commands)
    with pytest.raises(ValueError,match='replay'):sshupdates.apply(folder,connection)
    assert connection.commands==before
    assert sum(c.startswith('mv -f') for c in before)==1


def test_audio_data_is_committed_before_referencing_csv(tmp_path):
    folder=tmp_path/'update'
    sshupdates.save_package({'/usr/share/avsystemsound/custom.txt':(None,b'new CSV'),
                            '/usr/share/avsystemsound/custom-shutter.bin':(None,b'new audio')},
                           folder,'sound',source_baseline=tmp_path/'baseline')
    connection=Connection({})
    sshupdates.apply(folder,connection)
    publishes=[c for c in connection.commands if c.startswith('mv -f')]
    assert 'custom-shutter.bin' in publishes[0] and 'custom.txt' in publishes[1]


def test_version_restore_requires_exact_native_version_file_and_is_explicit(tmp_path):
    connection=Connection({'/setting/updater/dat4':b'\x01\x03'})
    folder=tmp_path/'version'
    result=sshupdates.prepare_version_restore(connection,folder)
    assert result['phase']=='PREPARED' and not connection.commands
    assert (folder/result['rows'][0]['after']).read_bytes()==b'\0\x02'
    sshupdates.apply(folder,connection)
    assert connection.files['/setting/updater/dat4']==b'\0\x02'
    connection.boot='00000000-0000-0000-0000-000000000002'
    verified=sshupdates.verify_reload(folder,connection)
    assert verified['phase']=='LOADED' and not verified['physical_official_upgrade_verified']
    with pytest.raises(ValueError,match='当前更新器版本不是'):
        sshupdates.prepare_version_restore(connection,tmp_path/'incorrect-version')


def test_matching_sound_switch_does_not_remount_or_request_reload(tmp_path):
    folder=tmp_path/'same'
    sshupdates.save_package({},folder,'sound-switch',source_baseline=tmp_path/'baseline')
    connection=Connection({})
    result=sshupdates.apply(folder,connection)
    assert result['phase']=='LOADED' and not connection.commands
