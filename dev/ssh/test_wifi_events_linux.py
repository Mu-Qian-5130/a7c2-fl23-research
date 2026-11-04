"""Original AArch64 receiver/Dropbear in an isolated Linux network namespace.

Run as root under `unshare --net`. All artifacts stay in the supplied directory.
The receiver source differs only in filesystem/busybox paths for this fixture.
"""
import json
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time


def run(folder,qemu):
    folder=Path(folder);qemu=str(qemu);rows=[]
    def command(*argv):return subprocess.run(argv,check=True,capture_output=True,text=True,timeout=10)
    def row(name,**values):rows.append(dict(name=name,**values));print(name,flush=True)
    def port(address):
        try:
            with socket.create_connection((address,2222),timeout=.15) as client:
                client.settimeout(.5);return client.recv(128).startswith(b'SSH-')
        except OSError:return False
    def wait_port(address,wanted):
        for _ in range(60):
            if port(address)==wanted:return
            time.sleep(.05)
        raise AssertionError('listener mismatch: '+address+' '+str(wanted))
    def children(pid):
        path=Path('/proc/%d/task/%d/children'%(pid,pid));return path.read_text().strip() if path.exists() else ''
    def ticks(pid):
        fields=Path('/proc/%d/stat'%pid).read_text().rsplit(')',1)[1].split();return int(fields[11])+int(fields[12])
    command('ip','link','set','lo','up')
    report=dict(camera_io=False,isolated_network_namespace=True,real_aarch64_dropbear=True,
                kernel_wifi_radio=False,physical_sleep_verified=False,cases=rows,passed=False)
    with (folder/'receiver.log').open('w') as log:
        watcher=subprocess.Popen([qemu,str(folder/'wifi-ssh.fixture')],stdout=log,stderr=log)
        try:
            time.sleep(.3);assert watcher.poll() is None and not children(watcher.pid);row('wifi-off-no-server')
            before=ticks(watcher.pid);time.sleep(.8);after=ticks(watcher.pid)
            assert after==before;row('idle-no-cpu-ticks',ticks=after-before)
            command('ip','link','add','ether-fixture','type','dummy');command('ip','link','set','ether-fixture','up')
            command('ip','addr','add','10.84.9.1/24','dev','ether-fixture');time.sleep(.15)
            assert not children(watcher.pid);row('ethernet-does-not-start-ssh')
            command('ip','link','add','wlan0','type','dummy');command('ip','link','set','wlan0','up');time.sleep(.15)
            assert not children(watcher.pid);row('wifi-without-address-no-server')
            command('ip','addr','add','10.84.0.1/24','dev','wlan0');wait_port('10.84.0.1',True);row('wifi-address-starts-ssh')
            assert not port('127.0.0.1') and not port('10.84.9.1');row('ssh-bound-to-wifi-only')
            duplicate=subprocess.run([qemu,str(folder/'wifi-ssh.fixture')],timeout=5)
            assert duplicate.returncode==1;row('duplicate-receiver-refused')
            command('ip','addr','del','10.84.0.1/24','dev','wlan0');wait_port('10.84.0.1',False);row('wifi-address-removed-stops-ssh')
            command('ip','addr','add','10.84.0.1/24','dev','wlan0');wait_port('10.84.0.1',True);row('wifi-reopen-starts-ssh')
            command('ip','link','set','wlan0','down');wait_port('10.84.0.1',False);row('wifi-link-down-stops-ssh')
            command('ip','link','set','wlan0','up');wait_port('10.84.0.1',True);row('wifi-link-up-starts-ssh')
            for _ in range(12):
                command('ip','addr','del','10.84.0.1/24','dev','wlan0')
                command('ip','addr','add','10.84.0.1/24','dev','wlan0')
            wait_port('10.84.0.1',True);row('rapid-wifi-address-toggle',cycles=12)
            command('ip','addr','del','10.84.0.1/24','dev','wlan0');command('ip','addr','add','10.84.1.1/24','dev','wlan0')
            wait_port('10.84.1.1',True);assert not port('10.84.0.1');row('wifi-address-change-rebinds-ssh')
            watcher.send_signal(signal.SIGTERM);assert watcher.wait(timeout=5)==0
            wait_port('10.84.1.1',False);row('receiver-stop-cleans-listener')
            watcher=subprocess.Popen([qemu,str(folder/'wifi-ssh.fixture')],stdout=log,stderr=log)
            wait_port('10.84.1.1',True);row('wifi-already-ready-at-receiver-start')
            before=ticks(watcher.pid);time.sleep(.8);after=ticks(watcher.pid)
            assert after==before;row('wifi-on-idle-no-receiver-cpu-ticks',ticks=after-before)
            command('ip','link','del','wlan0');wait_port('10.84.1.1',False);row('wifi-interface-removal-stops-ssh')
            watcher.send_signal(signal.SIGTERM);assert watcher.wait(timeout=5)==0;row('wifi-off-receiver-exits-on-signal')
            report['passed']=True
        except BaseException as exc:
            report['error']=type(exc).__name__+': '+str(exc)
            raise
        finally:
            if watcher.poll() is None:
                watcher.terminate()
                try:watcher.wait(timeout=5)
                except subprocess.TimeoutExpired:watcher.kill();watcher.wait()
            (folder/'result.private.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':print(json.dumps(run(*sys.argv[1:]),indent=2))
