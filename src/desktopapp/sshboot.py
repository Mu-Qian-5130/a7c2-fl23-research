"""Prepare an independent opt-in SSH boot service inside a local firmware copy."""
import base64
from pathlib import Path

from .paths import ROOT,write_json
from .actions.ssh import engine


BOOT = '''#!/bin/busybox sh
# Independent debug service; absence or failure never blocks the camera boot.
set -eu
source=/usr/lib/a7c2-tools/ssh
session=/tmp_wbshd/a7c2-ssh-boot
test -d /tmp_wbshd || exit 0
test -x "$source/dropbear" && test -s "$source/hostkey" && test -s "$source/authorized_keys" || exit 0
umask 077
/bin/busybox mkdir "$session" 2>/dev/null || exit 0
/bin/busybox cp "$source/dropbear" "$source/hostkey" "$source/authorized_keys" "$session/"
/bin/busybox chmod 700 "$session" "$session/dropbear"
/bin/busybox chmod 600 "$session/hostkey" "$session/authorized_keys"
cd "$session"
exec ./dropbear -F -p 0.0.0.0:2222 -r "$session/hostkey" -D . -P "$session/dropbear.pid" -K 30 -I 600
'''


def prepare_boot(args,output,rootfs):
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
    _,_,ext2,_=tools();original=None
    with Path(rootfs).open('rb') as image:
        for entry in ext2.readExt2(image):
            if entry.path=='/sbin/init2':original=entry.contents.read();break
    marker=b'    /usr/bin/bootin.elf &'
    if original is None or original.count(marker)!=1:raise ValueError('Original C2 startup seam differs')
    addition=b'    /bin/busybox sh /usr/lib/a7c2-tools/ssh/boot.sh </dev/null >/dev/null 2>&1 &\n'
    script=output/'init2';script.write_bytes(original.replace(marker,addition+marker))
    host_blob=b'\0\0\0\x0bssh-ed25519\0\0\0\x20'+raw_public
    write_json(output/'host-public.json',dict(algorithm='ssh-ed25519',public_key=base64.b64encode(host_blob).decode(),
        port=2222,persistent_startup=True,physical_boot_verified=False))
    (output/'dropbear-LICENSE.txt').write_bytes((assets/'dropbear-LICENSE.txt').read_bytes())
    return dict(usr=rows,rootfs={'/sbin/init2':dict(source=str(script),mode=0o755)})
