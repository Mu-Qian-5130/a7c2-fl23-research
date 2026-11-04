"""Include SSH files; a small Wi-Fi event receiver controls the listener."""
import base64
import os
from pathlib import Path
import subprocess

from .paths import ROOT,write_json
from .actions.ssh import engine


BOOT = '''#!/bin/busybox sh
# Started by a Wi-Fi address event; stops with that network session.
set -eu
source=/usr/lib/a7c2-tools/ssh
session=/tmp_wbshd/a7c2-ssh-boot
test -d /tmp_wbshd || exit 0
test -x "$source/dropbear" && test -s "$source/hostkey" && test -s "$source/authorized_keys" || exit 0
test -n "${1:-}" || exit 0
umask 077
/bin/busybox mkdir -p "$session"
/bin/busybox cp "$source/dropbear" "$source/hostkey" "$source/authorized_keys" "$session/"
/bin/busybox chmod 700 "$session" "$session/dropbear"
/bin/busybox chmod 600 "$session/hostkey" "$session/authorized_keys"
cd "$session"
exec ./dropbear -F -p "$1:2222" -r "$session/hostkey" -D . -P "$session/dropbear.pid" -K 0 -I 0
'''


def build_wifi_receiver(output,zig=None):
    from looktool.nativebuild import zig_command
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy()
    cache=Path(os.environ.get('A7C2_ZIG_CACHE',output.parent/'zig-cache'))
    env['ZIG_GLOBAL_CACHE_DIR']=str(cache/'global')
    env['ZIG_LOCAL_CACHE_DIR']=str(cache/'local')
    command=zig_command(zig)+['cc','-target','aarch64-linux-musl','-Os','-s','-static',
        str(ROOT/'src/camera_api/wifi_ssh.c'),'-o',str(output)]
    done=subprocess.run(command,env=env,capture_output=True,text=True,timeout=180)
    if done.returncode:raise ValueError('Wi-Fi SSH receiver build failed: '+done.stderr[-2500:])
    return output


def prepare_boot(args,output,rootfs,current=None):
    from Cryptodome.PublicKey import ECC
    from .firmwarelocal import tools
    module=engine();public=module.public_key(Path(args['client_key']).read_bytes())
    assets=Path(args.get('artifacts') or ROOT/'desktop-assets/ssh')
    module.executable(assets/'dropbear')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    key=ECC.generate(curve='Ed25519');raw_public=key.public_key().export_key(format='raw')
    hostkey=b'\0\0\0\x0bssh-ed25519\0\0\0\x40'+key.seed+raw_public
    rows={}
    for name,raw,mode in (('dropbear',(assets/'dropbear').read_bytes(),0o755),('hostkey',hostkey,0o600),
                          ('authorized_keys',public,0o600),('boot.sh',BOOT.encode('ascii'),0o755)):
        path=output/name;path.write_bytes(raw)
        rows['/lib/a7c2-tools/ssh/'+name]=dict(source=str(path),mode=mode)
    receiver=build_wifi_receiver(output/'wifi-ssh',args.get('zig'))
    rows['/lib/a7c2-tools/ssh/wifi-ssh']=dict(source=str(receiver),mode=0o755)
    if current is not None:
        from .cameraapi import build
        command=build(current,output/'api',args.get('zig'))
        rows['/lib/a7c2-tools/ssh/a7c2-api']=dict(source=str(command),mode=0o755)
        entry=output/'a7c2-api.sh'
        entry.write_text('#!/bin/busybox sh\nexec /usr/lib/a7c2-tools/ssh/a7c2-api "$@"\n',encoding='ascii',newline='\n')
        rows['/bin/a7c2-api']=dict(source=str(entry),mode=0o755)
    _,_,ext2,_=tools();original=None
    with Path(rootfs).open('rb') as image:
        for entry in ext2.readExt2(image):
            if entry.path=='/sbin/init2':original=entry.contents.read();break
    marker=b'    /usr/bin/bootin.elf &'
    if original is None or original.count(marker)!=1:raise ValueError('Original C2 startup seam differs')
    addition=b'    /usr/lib/a7c2-tools/ssh/wifi-ssh </dev/null >/dev/null 2>&1 &\n'
    script=output/'init2';script.write_bytes(original.replace(marker,addition+marker))
    host_blob=b'\0\0\0\x0bssh-ed25519\0\0\0\x20'+raw_public
    write_json(output/'host-public.json',dict(algorithm='ssh-ed25519',public_key=base64.b64encode(host_blob).decode(),
        port=2222,persistent_startup=False,wifi_trigger=True,physical_boot_verified=False))
    (output/'dropbear-LICENSE.txt').write_bytes((assets/'dropbear-LICENSE.txt').read_bytes())
    return dict(usr=rows,rootfs={'/sbin/init2':dict(source=str(script),mode=0o755)})
