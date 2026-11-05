"""Mount the exact installed SquashFS with the original C2 kernel in QEMU.

The diagnostic root, loop image and VM output are confined to a new workspace.
The existing Sony-register QEMU profile is supplied explicitly. No camera I/O.
"""
import argparse,json,os,shutil,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from desktopapp.updaterimage import partition_files


START='''#!/bin/sh
ulimit -c 0
mount -t proc proc /proc
mount -t tmpfs none /tmp
mount -t tmpfs none /dev
mkdir /tmp/installed
for n in 0 1 2 3 4 5 6 7; do mknod /dev/loop$n b 7 $n; done
mount -t squashfs -o loop,ro /diagnostics/installed.img /tmp/installed || exit 30
echo C2_EXACT_INSTALLED_SQUASHFS_MOUNTED
uname -a
export LD_LIBRARY_PATH=/tmp/installed/lib:/tmp/installed/usr/lib
for lib in libsdfileinputupdaterapi.so libseninputupdaterapi.so libupdaterapi.so libuudfileinputupdaterapi.so; do
 for case in valid tampered_payload wrong_signature factory_key changed_encoding missing_key; do
  data=/diagnostics/payload.bin; sig=/diagnostics/payload.sig; key=/tmp/installed/etc/VerificationKey.pem
  case "$case" in
   tampered_payload) data=/diagnostics/tampered.bin;;
   wrong_signature) sig=/diagnostics/wrong.sig;;
   factory_key) key=/diagnostics/factory.pem;;
   changed_encoding) key=/diagnostics/encoding.pem;;
   missing_key) key=/diagnostics/missing.pem;;
  esac
  /diagnostics/harness "/tmp/installed/usr/lib/$lib" "$data" "$sig" "$key" 0000000000000000000000000000000000000000
  echo "C2_EXACT_CASE $lib $case rc=$?"
 done
done
echo C2_EXACT_INSTALLED_MATRIX_DONE
exec /bin/sh
'''

PRODUCTION='''
mkdir /tmp/jiritsu
cp /diagnostics/updater.original /tmp/native.updater
/diagnostics/guest-helper setup || exit 31
ln -s /dev/loop1 /dev/nflasha1
mkdir /tmp/alias-mount
mount -t vfat -o ro /dev/loop1 /tmp/alias-mount || exit 34
LD_PRELOAD=/diagnostics/production/write-000/trust.so /bin/true
echo "C2_PRODUCTION_MOUNT_GUARD $(/diagnostics/guest-helper hex /tmp/jiritsu/a7c2.trust.result)"
umount /tmp/alias-mount || exit 35
/diagnostics/guest-helper setup || exit 36
for worker in /diagnostics/production/read-*/trust.so; do
 rm -f /tmp/jiritsu/a7c2.trust.result
 LD_PRELOAD="$worker" /bin/true
 echo "C2_PRODUCTION_REPORT $worker $(/diagnostics/guest-helper hex /tmp/jiritsu/a7c2.trust.result)"
 cat /tmp/jiritsu/a7c2.trust.chunk >> /tmp/native.backup
 rm /tmp/jiritsu/a7c2.trust.chunk
done
/diagnostics/guest-helper compare /tmp/native.backup /diagnostics/updater.original || exit 32
echo C2_PRODUCTION_BACKUP_MATCHES
for worker in /diagnostics/production/write-*/trust.so; do
 rm -f /tmp/jiritsu/a7c2.trust.result
 LD_PRELOAD="$worker" /bin/true
 echo "C2_PRODUCTION_REPORT $worker $(/diagnostics/guest-helper hex /tmp/jiritsu/a7c2.trust.result)"
done
sync
/diagnostics/guest-helper compare /tmp/native.updater /diagnostics/updater.candidate || exit 33
echo C2_PRODUCTION_FULL_READBACK_MATCHES
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('image','stock-initrd','profile','fixtures','harness','board','workspace'):
        parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--production-workers',type=Path)
    parser.add_argument('--original',type=Path)
    args=parser.parse_args();args.workspace.mkdir(parents=True,exist_ok=False)
    disk=args.workspace/'work.ext4';mount=args.workspace/'mounted';mount.mkdir()
    with disk.open('xb') as stream:stream.truncate(2*1024**3)
    subprocess.run(['mkfs.ext4','-q','-F',str(disk)],check=True)
    subprocess.run(['mount','-o','loop',str(disk),str(mount)],check=True)
    try:
        root=mount/'root'
        subprocess.run(['unsquashfs','-no-progress','-d',str(root),str(args.stock_initrd)],check=True,capture_output=True)
        diagnostic=root/'diagnostics';diagnostic.mkdir()
        (diagnostic/'installed.img').write_bytes(partition_files(args.image.read_bytes())['/boot/initrd.img'])
        for name in ('payload.bin','tampered.bin','payload.sig','wrong.sig','factory.pem','encoding.pem'):
            shutil.copyfile(args.fixtures/name,diagnostic/name)
        shutil.copyfile(args.harness,diagnostic/'harness');(diagnostic/'harness').chmod(0o755)
        start=START
        if args.production_workers:
            if not args.original:raise ValueError('--original is required for production workers')
            production=diagnostic/'production';production.mkdir()
            for worker in args.production_workers.glob('workers/*/trust.so'):
                folder=production/worker.parent.name;folder.mkdir();shutil.copyfile(worker,folder/'trust.so')
            shutil.copyfile(args.original,diagnostic/'updater.original')
            shutil.copyfile(args.image,diagnostic/'updater.candidate')
            subprocess.run(['aarch64-linux-gnu-gcc','-Os','-static',str(ROOT/'dev/firmware/native/test_trust_loop.c'),
                '-o',str(diagnostic/'guest-helper')],check=True,capture_output=True)
            start=start.replace('echo C2_EXACT_INSTALLED_SQUASHFS_MOUNTED',PRODUCTION+'\necho C2_EXACT_INSTALLED_SQUASHFS_MOUNTED')
        (diagnostic/'start.sh').write_text(start);(diagnostic/'start.sh').chmod(0o755)
        probe=args.workspace/'diagnostic.squashfs'
        subprocess.run(['mksquashfs',str(root),str(probe),'-noappend','-comp','gzip','-b','131072',
            '-processors','2','-no-progress'],check=True,capture_output=True)
        profile=args.workspace/'profile.sh'
        text=args.profile.read_text()
        old='output_dir="/mnt/e/CodexData/c2-owner-trust-20261103/linux-work/system-updater7-$ram_mb"'
        assert text.count(old)==1
        profile.write_text(text.replace(old,'output_dir="'+str(mount/'output')+'-$ram_mb"'))
        # The profile uses an unprivileged, isolated QEMU process with no disk or network passthrough.
        subprocess.run(['chown','-R','leonard:leonard',str(mount)],check=True)
        environment=dict(os.environ,TMPDIR='/mnt/e/CodexData/tmp',SONY_TIMER_MODEL='1',
            QEMU_TIMEOUT_SECONDS='90',QEMU_TRACE_FLAGS='guest_errors,unimp',
            QEMU_SYSTEM_DIR='/home/leonard/a7c2-vm-lab/a7c2-re/report/2026-10-17-qemu-native-camera/runtime/sources/qemu-11.1.2/build-sony-ui')
        process=subprocess.run(['runuser','-u','leonard','--','env',*[k+'='+environment[k] for k in
            ('TMPDIR','SONY_TIMER_MODEL','QEMU_TIMEOUT_SECONDS','QEMU_TRACE_FLAGS','QEMU_SYSTEM_DIR')],
            'bash',str(profile),'4096',str(args.board),'1','1',str(probe)],capture_output=True,text=True,timeout=150)
        (args.workspace/'serial.log').write_text(process.stdout+'\n'+process.stderr)
        rows=[line for line in process.stdout.splitlines() if line.startswith('C2_EXACT_CASE ')]
        passed=len(rows)==24 and 'C2_EXACT_INSTALLED_MATRIX_DONE' in process.stdout
        for line in rows:
            parts=line.split();passed=passed and parts[-1]==('rc=0' if parts[2]=='valid' else 'rc=1')
        native=[line for line in process.stdout.splitlines() if line.startswith('C2_PRODUCTION_REPORT ')]
        if args.production_workers:
            from desktopapp.trustworker import REPORT,parse
            passed=passed and len(native)==39 and 'C2_PRODUCTION_FULL_READBACK_MATCHES' in process.stdout
            for line in native:
                raw=bytes.fromhex(line.split()[-1]);value=REPORT.unpack(raw)
                parse(raw,value[2],value[5],value[6])
            guard=[line for line in process.stdout.splitlines() if line.startswith('C2_PRODUCTION_MOUNT_GUARD ')]
            passed=passed and len(guard)==1
            if guard:
                result=REPORT.unpack(bytes.fromhex(guard[0].split()[-1]))
                passed=passed and result[4]==0 and result[8]==0 and result[9]==-16
        report=dict(passed=passed,camera_io=False,exact_candidate_mounted=True if rows else False,
            original_kernel=True,diagnostic_init=True,full_updater_boot=False,cases=rows,exit_code=process.returncode,
            production_reports=len(native),production_full_readback='C2_PRODUCTION_FULL_READBACK_MATCHES' in process.stdout)
        (args.workspace/'result.private.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2),flush=True)
        return 0 if passed else 1
    finally:
        subprocess.run(['sync'],check=True)
        subprocess.run(['umount',str(mount)],check=True)


if __name__=='__main__':raise SystemExit(main())
