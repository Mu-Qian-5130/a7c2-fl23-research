"""Run temporary SSH inside the isolated Sony-kernel/AP firmware VM.

Run with the VM lab's Linux Python. Uses a separately generated cpio image,
guest loopback networking and serial control; no host NIC or device passthrough.
The production syscall worker and session script are tested unchanged.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import runpy
import time
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis',type=Path,required=True)
    parser.add_argument('--initramfs',type=Path,required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    parser.add_argument('--runs-dir',type=Path,
                        help='Keep new VM logs and latest-run pointer in this directory')
    parser.add_argument('--extended',action='store_true',help='Also check original version reader and independent SSH boot script')
    parser.add_argument('--skip-menu-snapshots',action='store_true',help='Scope this run to Linux/SSH/version behavior, without claiming AP menu acceptance')
    parser.add_argument('--extended-only',action='store_true',help='Test only the new boot service and native VersionFile; retain the independent full temporary-SSH run')
    args=parser.parse_args()
    analysis=args.analysis.resolve();sys.path.insert(0,str(analysis))
    import menu_live
    profile=runpy.run_path(str(analysis/'start-menu.py'))
    env=profile['profile_environment'](os.environ)
    env.update(MENU_CONTROL_FD='3',MENU_SETTLE_SECONDS='8')
    env['SKIP_REBUILD']='1'
    os.environ.clear();os.environ.update(env)

    def scenario(proc,out,descriptor):
        del descriptor
        report=dict(schema='a7c2-ssh-firmware-vm/1',real_camera_io=False,
                    physical_wifi_verified=False,persistent_startup=False,
                    original_kernel_guest=True,guest_loopback_only=True,
                    production_worker_unchanged=True,run=str(out),steps=[],completed=False)
        monitor=menu_live.FirmwareMonitor(out/'console.log')
        def command(name,shell,timeout=45):
            print('SSH_VM_STEP '+name,flush=True)
            data=menu_live.serial_command(proc,out/'console.log',shell,timeout=timeout,monitor=monitor)
            (out/(name+'.serial.txt')).write_bytes(data)
            report['steps'].append(dict(name=name,completed=True))
            return data
        try:
            command('baseline',
                'echo SSH_VM_KERNEL; /bin/busybox uname -a; '
                'echo SSH_VM_AP; /bin/busybox pidof im.elf; '
                'test -x /simulation/ssh-vm/harness; '
                '/bin/busybox mkdir -p /tmp/jiritsu /tmp_wbshd /dev/pts; '
                '/bin/busybox mount | /bin/busybox grep -q "on /tmp_wbshd type tmpfs" || /bin/busybox mount -t tmpfs none /tmp_wbshd; '
                '/bin/busybox mount | /bin/busybox grep -q "on /dev/pts type devpts" || /bin/busybox mount -t devpts devpts /dev/pts; '
                '/bin/busybox ifconfig lo 127.0.0.1 up')
            before_accounts=command('accounts-before','/simulation/ssh-vm/harness accounts')
            match=re.search(rb'\nSSH_ACCOUNT_SHA256=([a-f0-9]{64})',before_accounts)
            if not match:raise ValueError('Missing factory account fixture hash')
            account_digest=match[1]
            if args.extended_only:
                version=command('native-version-roundtrip','/simulation/ssh-vm/version-probe')
                if b'A7C2_NATIVE_VERSION_ROUNDTRIP_OK' not in version:raise ValueError('Original updater version roundtrip did not complete')
                report['native_version_roundtrip_verified']=True
                command('firmware-ssh-start','/bin/busybox sh /usr/lib/a7c2-tools/ssh/boot.sh >/tmp/ssh-boot.log 2>&1 & /bin/busybox sleep 1')
                client='/simulation/ssh-vm/dbclient -T -y -i /simulation/ssh-vm/clientkey -p 2222 root@127.0.0.1 '
                response=command('firmware-ssh-login',client+'"printf A7C2_FIRMWARE_BOOT_SSH_OK"')
                if b'A7C2_FIRMWARE_BOOT_SSH_OK' not in response:raise ValueError('Firmware SSH did not accept its selected key')
                command('firmware-ssh-stop','/bin/busybox kill $(/bin/busybox cat /tmp_wbshd/a7c2-ssh-boot/dropbear.pid); /bin/busybox sleep 1')
                command('firmware-ssh-stopped','! /bin/busybox grep -q "00000000:08AE .* 0A" /proc/net/tcp')
                after_accounts=command('accounts-after','/simulation/ssh-vm/harness accounts')
                if not re.search(rb'\nSSH_ACCOUNT_SHA256='+account_digest,after_accounts):raise ValueError('Factory account fixture changed')
                report.update(completed=True,firmware_ssh_boot_script_verified=True,
                    boot_script_executed_manually=True,automatic_cold_boot_verified=False,
                    production_worker_exercised=False,ap_menu_before_after_exported=False,
                    factory_account_file_unchanged=True,listener_stopped=True)
                return
            if not args.skip_menu_snapshots:
                baseline=command('menu-before','/simulation/headless-osd-export')
                picture=menu_live.snapshot_message(baseline)
                (out/'ssh-menu-before.png').write_bytes(base64.b64decode(picture['png']))
            command('native-snapshot','/simulation/ssh-vm/harness 6 0 0 0 0')
            command('create-session','/simulation/ssh-vm/harness 0 0 0 0 0')
            manifest=json.loads((args.initramfs.parent/'payload-layout.json').read_text())
            report['session_path']=manifest['session_path']
            for index,row in enumerate(manifest['files']):
                for at in range(0,row['bytes'],65536):
                    count=min(65536,row['bytes']-at)
                    command('upload-%d-%06d'%(index,at),
                        '/bin/busybox dd if=/simulation/ssh-vm/'+row['name']+
                        ' of=/tmp/jiritsu/resource.chunk bs=65536 skip='+str(at//65536)+' count=1 2>/dev/null; '+
                        '/simulation/ssh-vm/harness 1 %d %d %d 0'%(index,at,count))
            command('verify-all','/simulation/ssh-vm/harness 2 0 0 0 0')
            command('launch','/simulation/ssh-vm/harness 3 0 0 0 0')
            command('status','/bin/busybox sleep 1; /simulation/ssh-vm/harness 4 0 0 0 0')
            command('duplicate-launch-rejected','/simulation/ssh-vm/harness 3 0 0 0 -17')
            client='/simulation/ssh-vm/dbclient -T -y -i /simulation/ssh-vm/clientkey -p 2222 root@127.0.0.1 '
            response=command('ssh-command',client+
                "\"printf 'A7C2_FIRMWARE_SSH_OK\\n' && /bin/busybox uname -m && /bin/busybox grep '^Uid:' /proc/self/status && /bin/busybox cat /proc/sys/kernel/random/boot_id\"",timeout=60)
            clean=menu_live.clean_console(response)
            if not re.search(rb'\nA7C2_FIRMWARE_SSH_OK\naarch64\nUid:\s+0\s+0\s+0\s+0\n[a-f0-9-]{36}\n',clean):
                raise ValueError('Missing complete SSH command/architecture/uid/boot response')
            report['ssh_command_verified']=True
            pty=command('ssh-pty','/simulation/ssh-vm/dbclient -t -y -i /simulation/ssh-vm/clientkey -p 2222 root@127.0.0.1 '
                        '"test -t 0 && printf A7C2_FIRMWARE_PTY_OK"',timeout=60)
            if b'A7C2_FIRMWARE_PTY_OK' not in pty:raise ValueError('PTY marker missing')
            report['pty_verified']=True
            command('stop','/simulation/ssh-vm/harness 5 0 0 0 0; /bin/busybox sleep 1')
            command('listener-gone',
                '! /bin/busybox grep -q "00000000:08AE .* 0A" /proc/net/tcp')
            command('session-records',
                '/bin/busybox cat '+manifest['session_path']+'/session.log; '
                '/simulation/ssh-vm/harness 4 0 0 0 -2')
            after_accounts=command('accounts-after','/simulation/ssh-vm/harness accounts')
            if not re.search(rb'\nSSH_ACCOUNT_SHA256='+account_digest,after_accounts):
                raise ValueError('Global account file changed during test')
            report['factory_account_file_unchanged']=True
            if not args.skip_menu_snapshots:
                after=command('menu-after','/simulation/headless-osd-export')
                picture=menu_live.snapshot_message(after)
                (out/'ssh-menu-after.png').write_bytes(base64.b64decode(picture['png']))
            if args.extended:
                version=command('native-version-roundtrip','/simulation/ssh-vm/version-probe')
                if b'A7C2_NATIVE_VERSION_ROUNDTRIP_OK' not in version:raise ValueError('Original updater version roundtrip did not complete')
                report['native_version_roundtrip_verified']=True
                command('firmware-ssh-start','/bin/busybox sh /usr/lib/a7c2-tools/ssh/boot.sh >/tmp/ssh-boot.log 2>&1 & /bin/busybox sleep 1')
                response=command('firmware-ssh-login',client+'"printf A7C2_FIRMWARE_BOOT_SSH_OK"')
                if b'A7C2_FIRMWARE_BOOT_SSH_OK' not in response:raise ValueError('Firmware boot SSH did not accept its selected key')
                command('firmware-ssh-stop','/bin/busybox kill $(/bin/busybox cat /tmp_wbshd/a7c2-ssh-boot/dropbear.pid); /bin/busybox sleep 1')
                command('firmware-ssh-stopped','! /bin/busybox grep -q "00000000:08AE .* 0A" /proc/net/tcp')
                report['firmware_ssh_boot_script_verified']=True
            report.update(completed=True,listener_stopped=True,ap_menu_before_after_exported=not args.skip_menu_snapshots)
        except BaseException as exc:
            report['error']=type(exc).__name__+': '+str(exc)
            try:command('failure-evidence','/bin/busybox cat /tmp_wbshd/a7c2-ssh-*/session.log; /bin/busybox cat /proc/net/tcp')
            except BaseException:pass
            raise
        finally:
            report['finished_at']=time.time()
            (out/'ssh-firmware-vm.json').write_text(json.dumps(report,indent=2)+'\n')
            args.receipt.parent.mkdir(parents=True,exist_ok=True)
            args.receipt.write_text(json.dumps(report,indent=2)+'\n')
            print('SSH_FIRMWARE_VM_RUN '+str(out),flush=True)

    menu_live.run_live=scenario
    sys.argv=[str(analysis/'qemu-menu-probe.py'),'--initramfs','--initramfs-file',str(args.initramfs),
              '--sony-timers','--load-ipc','--seed-backup','--load-dmm','--load-power','--load-kikilog',
              '--no-cp-updater','--capid-service','--sa-address-service','--hdmi-format-service',
              '--hdmi-photo-service','--dmm-service','--software-gpe','--firmware-identity',
              '--display-info-service','--seed-power-on','--menu-target','--bootin','--observe']
    probe=analysis/'qemu-menu-probe.py'
    if args.runs_dir:
        runs=args.runs_dir.resolve();runs.mkdir(parents=True,exist_ok=True)
        code=probe.read_text()
        replacements={"runs = base / 'menu-runs'":'runs = Path('+repr(str(runs))+')',
                      "(base / 'latest-menu-run.txt')":"(runs / 'latest-menu-run.txt')"}
        for before,after in replacements.items():
            if code.count(before)!=1:raise ValueError('VM output-path seam differs: '+before)
            code=code.replace(before,after)
        exec(compile(code,str(probe),'exec'),dict(__name__='__main__',__file__=str(probe)))
    else:
        runpy.run_path(str(probe),run_name='__main__')


if __name__=='__main__':main()
