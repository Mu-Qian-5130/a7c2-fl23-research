"""Execute the installer with the real AArch64 C worker against an image file.

Requires explicit local original partition/public-key fixtures. There is no USB,
camera, /dev target, network or flash passthrough. All writes stay in --workspace.
"""
import argparse
from contextlib import contextmanager
import json,os,shutil,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'src/looks')]
from desktopapp import trustworker,updaterimage
from desktopapp.trustinstall import Installer,STATE


class NativeFilePartition:
    camera_io=False

    def __init__(self,root,original,qemu):
        self.root=root;self.device=root/'vm-updater.img';self.device.write_bytes(original)
        self.qemu=qemu;self.cache={};self.boot_id='00000000-0000-0000-0000-000000000001'
        self.identity=dict(model='ILCE-7CM2',serial_sha256='synthetic-vm-body',usb_serial_sha256='synthetic-vm-usb')
        self.calls=0;self.writes=0;self.lose_response=False

    def prepare(self,job):pass

    @contextmanager
    def session(self,job,expected=None):
        if expected is not None and expected!=self.identity:raise ValueError('VM body mismatch')
        yield self

    def binary(self,mode,at,count,before=b'',after=b''):
        key=(mode,at,count,before,after)
        if key not in self.cache:
            folder=self.root/('native-%03d'%len(self.cache));folder.mkdir()
            config=folder/'trust.h'
            text=trustworker.header(mode,at,count,before,after)+'\n#define TRUST_VM 1\n'
            for name,path in [('TRUST_DEVICE',self.device),('TRUST_RESULT',self.root/'native.result'),('TRUST_CHUNK',self.root/'native.chunk')]:
                text+='#define '+name+' '+json.dumps(str(path))+'\n'
            config.write_text(text)
            output=folder/'worker'
            command=['aarch64-linux-gnu-gcc','-Os','-static','-DPATCH_MANIFEST="trust.h"','-I',str(folder),
                     str(ROOT/'src/camera_api/trust_partition.c'),'-o',str(output)]
            subprocess.run(command,check=True,capture_output=True)
            self.cache[key]=output
        return self.cache[key]

    def call(self,mode,at,count,before=b'',after=b''):
        binary=self.binary(mode,at,count,before,after)
        result=self.root/'native.result';result.unlink(missing_ok=True)
        done=subprocess.run([str(self.qemu),str(binary)],capture_output=True,timeout=30)
        self.calls+=1
        if not result.is_file():raise RuntimeError('Native VM worker has no result: '+done.stderr.decode(errors='replace'))
        parsed=trustworker.parse(result.read_bytes(),mode,at,count)
        if done.returncode:raise AssertionError('Native exit code differs')
        return parsed

    def read(self,job,at,count):
        self.call(0,at,count)
        return (self.root/'native.chunk').read_bytes()

    def prepare_writes(self,job,rows):
        for at,before,after in rows:self.binary(2,at,len(before),before,after)

    def write(self,job,index,at,before,after):
        result=self.call(2,at,len(before),before,after);self.writes+=1
        if self.lose_response:
            self.lose_response=False
            raise TimeoutError('Synthetic lost response after the native write completed')
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original',type=Path,required=True)
    parser.add_argument('--identity',type=Path,required=True)
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--qemu',type=Path,required=True)
    args=parser.parse_args();args.workspace.mkdir(parents=True,exist_ok=False)
    os.environ['A7C2_DISTRIBUTION_IDENTITY']=str(args.identity)
    original=args.original.read_bytes();backend=NativeFilePartition(args.workspace,original,args.qemu)
    result=Installer(args.workspace/'install',backend).run()
    candidate=backend.device.read_bytes()
    assert result['phase']=='AWAITING_RELOAD' and not result['camera_io'] and result['partition_readback_verified']
    assert candidate==(args.workspace/'install/candidate-updater.private.img').read_bytes()
    assert (args.workspace/'install/original-updater.private.img').read_bytes()==original
    assert (args.workspace/'install/original-updater-copy.private.img').read_bytes()==original
    first_writes=backend.writes
    # A failed preimage comparison must execute zero writes.
    at,before,after=next(updaterimage.spans(original,candidate))
    stopped=False
    try:backend.call(2,at,len(before),before,after)
    except ValueError:stopped=True
    assert stopped and backend.device.read_bytes()==candidate
    backend.boot_id='00000000-0000-0000-0000-000000000002'
    verified=Installer(args.workspace/'verify',backend).verify(args.workspace/'install')
    assert verified['phase']=='LOADED' and not verified['updater_boot_verified']
    restored=Installer(args.workspace/'restore',backend).run(source=args.workspace/'install')
    assert restored['original_trust_restored'] and backend.device.read_bytes()==original
    # Lose a result after a real native write: stop, retain backup, then run a
    # distinct explicit restore transaction based on freshly read current bytes.
    backend.lose_response=True;before_fault=backend.writes
    try:Installer(args.workspace/'lost-response',backend).run()
    except TimeoutError:pass
    else:raise AssertionError('Lost native result was swallowed')
    state=json.loads((args.workspace/'lost-response'/STATE).read_text())
    assert state['phase']=='NEEDS_REVIEW' and state['write_attempted']
    assert backend.writes==before_fault+1
    recovered=Installer(args.workspace/'recover-lost-response',backend).run(source=args.workspace/'lost-response')
    assert recovered['original_trust_restored'] and backend.device.read_bytes()==original
    report=dict(passed=True,camera_io=False,actual_aarch64_worker=True,native_calls=backend.calls,
        install_batches=first_writes,source_backup_preserved=True,full_readback=True,
        preimage_conflict_zero_writes=True,explicit_factory_trust_restore=True,
        lost_response_stopped_no_replay=True,interrupted_install_recovered=True,
        updater_boot_verified=False,compiled_native_binaries=len(backend.cache))
    (args.workspace/'result.private.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
