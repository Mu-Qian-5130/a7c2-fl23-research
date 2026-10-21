"""Build/run only the host counter contract; never connects to a camera or VM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zig',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    src=Path(__file__).parent/'vm/cp_boot/gptimer'
    args.output.mkdir(parents=True,exist_ok=False)
    binary=args.output/('counter-test.exe' if os.name=='nt' else 'counter-test')
    command=[str(args.zig.resolve()),'cc','-std=c11','-Wall','-Wextra','-Werror',
             '-I',str(src.resolve()),str((src/'counter_test.c').resolve()),
             '-o',str(binary.resolve())]
    compiled=subprocess.run(command,capture_output=True,text=True,timeout=120)
    (args.output/'compile.log').write_text(compiled.stdout+compiled.stderr,encoding='utf-8')
    if compiled.returncode:
        raise RuntimeError('Host counter build failed: '+compiled.stderr)
    tested=subprocess.run([str(binary.resolve())],capture_output=True,text=True,timeout=15)
    (args.output/'test.log').write_text(tested.stdout+tested.stderr,encoding='utf-8')
    if tested.returncode:
        raise RuntimeError('Host counter contracts failed: '+tested.stdout+tested.stderr)
    report=dict(camera_io=False,VM_started=False,physical_timer_qualified=False,
        command=command,compiler_returncode=compiled.returncode,test_returncode=tested.returncode,
        sources={f.name:hashlib.sha256(f.read_bytes()).hexdigest()
                 for f in (src/'counter.h',src/'counter_test.c')},
        tested=['elapsed-count','stopped-count','compare-before-and-at-deadline',
                'IRQ-clear','32bit-wrap','actual-divider-rate','unsupported-access-rejection'],
        limits=['mode2 behavior and4MHz input are explicit laboratory inferences',
                'No native timer ISR, AP peer, sensor, pixels, saving or camera recovery is tested'])
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(tested.stdout.strip())


if __name__=='__main__':
    main()
