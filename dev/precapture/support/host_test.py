"""Explicit host-only C model checks; importing never starts a process or device."""
import hashlib
import os
from pathlib import Path
import subprocess


def run_host_test(zig, output, source, inputs, *, name):
    output=Path(output);source=Path(source)
    output.mkdir(parents=True,exist_ok=False)
    binary=output/(name+('.exe' if os.name=='nt' else ''))
    command=[str(Path(zig).resolve()),'cc','-std=c11','-Wall','-Wextra','-Werror',
             '-I',str(source.parent.resolve()),str(source.resolve()),'-o',str(binary.resolve())]
    compiled=subprocess.run(command,capture_output=True,text=True,timeout=120)
    (output/'compile.log').write_text(compiled.stdout+compiled.stderr,encoding='utf-8')
    if compiled.returncode:
        raise RuntimeError('Host model build failed: '+compiled.stderr)
    tested=subprocess.run([str(binary.resolve())],capture_output=True,text=True,timeout=15)
    (output/'test.log').write_text(tested.stdout+tested.stderr,encoding='utf-8')
    if tested.returncode:
        raise RuntimeError('Host model contracts failed: '+tested.stdout+tested.stderr)
    return dict(camera_io=False,VM_started=False,command=command,
        compiler_returncode=compiled.returncode,test_returncode=tested.returncode,
        sources={Path(f).name:hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in inputs}),tested.stdout.strip()
