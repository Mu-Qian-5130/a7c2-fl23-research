"""Exercise the actual AArch64 syscall worker under QEMU on isolated tmpfs.

Run as root in the Linux test VM, never on the camera. Only the compiled
mailbox/root paths and the test process image differ from the device worker.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import tempfile
import time


def run(qemu):
    assert os.geteuid()==0,'Run inside the Linux test VM as root'
    qemu=str(Path(qemu).resolve());source=Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix='a7c2-native-ssh-',dir='/dev/shm') as temporary, \
         tempfile.TemporaryDirectory(prefix='a7c2-native-ssh-build-') as build_dir:
        root=Path(temporary);build=Path(build_dir);mail=root/'mail';mail.mkdir()
        session=root/'a7c2-ssh-0123456789abcdef'
        # Keep executable code off /dev/shm, whose host mount may be noexec.
        harness=build/'harness';worker=build/'worker.so'
        (build/'harness.c').write_text('#include <dlfcn.h>\n#include <stdio.h>\nint main(int n,char**v){void*p=dlopen(v[1],RTLD_NOW);if(!p){puts(dlerror());return 2;}dlclose(p);return 0;}\n')
        subprocess.run(['aarch64-linux-gnu-gcc',str(build/'harness.c'),'-ldl','-o',str(harness)],check=True)
        payload=b'A7C2 payload under test\n'
        script=b'#!/bin/sh\numask 077\ncd "$1" || exit 1\nprintf "%s\\n" "$$" > dropbear.pid\n: > started\nexec /usr/bin/sleep 60\n'
        files=[('payload',payload,0o600),('script',script,0o700)]
        quote=lambda s:json.dumps(str(s))
        lines=['#define SSH_TMP_ROOT '+quote(root),'#define SSH_MAILBOX '+quote(mail),
            'static const char session_path[]='+quote(session)+';',
            'static const char session_name[]='+quote(session.name)+';',
            'static const char server_path[]="/usr/bin/sleep";',
            'static const char script_path[]='+quote(session/'script')+';',
            'static const char bind_ip[]="127.0.0.1";',
            'static const u32 file_count=2;']
        for i,(_,raw,_) in enumerate(files):lines.append('static const u8 hash_%d[]={%s};'%(i,','.join(map(str,sha256(raw).digest()))))
        lines.append('static const struct File files[]={'+','.join('{'+quote(name)+','+str(len(raw))+',hash_'+str(i)+','+str(mode)+'}' for i,(name,raw,mode) in enumerate(files))+'};')
        header=build/'manifest.h';header.write_text('\n'.join(lines))
        subprocess.run(['aarch64-linux-gnu-gcc','-shared','-fPIC','-Os','-ffreestanding','-fno-builtin',
            '-fno-stack-protector','-nostdlib','-Wl,--no-undefined','-Wl,-init,_init',
            '-I'+str(source.parents[1]/'src/fl23/native'),'-DPATCH_MANIFEST="'+str(header)+'"',
            str(source/'temporary.c'),'-o',str(worker)],check=True)
        cases=[]
        def call(mode,index=0,offset=0,chunk=None,expected=0):
            if chunk is not None:(mail/'resource.chunk').write_bytes(chunk)
            (mail/'libJit.so').write_bytes(b'test marker')
            (mail/'a7c2.install.request').write_bytes(struct.pack('<8sIIQII',b'A7SSH001',mode,index,offset,len(chunk or b''),0))
            done=subprocess.run([qemu,'-L','/usr/aarch64-linux-gnu',str(harness),str(worker)],capture_output=True,text=True,timeout=10)
            assert done.returncode==0,(done.stdout,done.stderr)
            raw=(mail/'a7c2.runtime.result').read_bytes()
            result=struct.unpack('<8sIIqqQ',raw[:40])
            assert result[:3]==(b'A7SSR001',1,mode),result
            assert result[3]==expected,(result,done.stderr[-4500:])
            assert not (mail/'libJit.so').exists()
            if mode==6 and not expected:
                lengths=struct.unpack_from('<7I',raw,40)
                assert len(raw)==68+sum(lengths) and lengths[0]==37
            cases.append(dict(mode=mode,status=result[3]))
            return result
        call(6) # /proc files have stat size zero but contain live read() data.
        assert not session.exists()
        call(0)
        call(0,expected=-17) # An existing session is not reset/replayed.
        call(1,0,0,payload[:7])
        call(1,0,0,payload,expected=-17)
        call(1,0,6,payload[7:],expected=-116)
        assert (session/'payload').read_bytes()==payload[:7]
        call(1,0,7,payload[7:]);call(1,1,0,script);call(2)
        (session/'payload').write_bytes(b'X'+payload[1:]);call(2,expected=-84)
        (session/'payload').write_bytes(payload);call(2)
        # A link cannot redirect a staged append outside the fixed session.
        outside=root/'outside';outside.write_bytes(payload)
        (session/'payload').unlink();(session/'payload').symlink_to(outside)
        call(1,0,len(payload),b'x',expected=-22) # size bound checked before opening
        call(2,expected=-40)
        assert outside.read_bytes()==payload
        (session/'payload').unlink();(session/'payload').write_bytes(payload);os.chmod(session/'payload',0o600)
        call(3)
        for attempt in range(50):
            if (session/'dropbear.pid').exists():break
            time.sleep(.02)
        pid=int((session/'dropbear.pid').read_text())
        try:
            status=call(4);assert status[4]==pid
            foreign=subprocess.Popen(['/usr/bin/sleep','60'])
            try:
                (session/'dropbear.pid').write_text(str(foreign.pid)+'\n')
                call(5,expected=-116)
                assert foreign.poll() is None
            finally:foreign.terminate();foreign.wait(timeout=5)
            (session/'dropbear.pid').write_text(str(pid)+'\n')
            call(3,expected=-17)
            call(1,0,0,payload,expected=-17)
            call(5)
            for attempt in range(50):
                if not Path('/proc/%d/exe'%pid).exists():break
                time.sleep(.02)
            assert not Path('/proc/%d/exe'%pid).exists()
        finally:
            if Path('/proc/%d/exe'%pid).exists():os.killpg(pid,signal.SIGTERM)
        return dict(camera_io=False,actual_aarch64_worker=True,exact_chunk_progress=True,
            corruption_rejected=True,symlink_rejected=True,existing_session_not_replayed=True,
            launch_status_stop='passed',native_test_cases=len(cases))


if __name__=='__main__':print(json.dumps(run(sys.argv[1]),indent=2))
