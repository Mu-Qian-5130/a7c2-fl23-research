"""Build/run only the host counter contract; never connects to a camera or VM."""
import argparse
import json
from pathlib import Path
from support.host_test import run_host_test


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zig',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    src=Path(__file__).parent/'vm/cp_boot/gptimer'
    report,message=run_host_test(args.zig,args.output,src/'counter_test.c',
                                (src/'counter.h',src/'counter_test.c'),name='counter-test')
    report.update(physical_timer_qualified=False,
        tested=['elapsed-count','stopped-count','compare-before-and-at-deadline',
                'IRQ-clear','32bit-wrap','actual-divider-rate','unsupported-access-rejection'],
        limits=['mode2 behavior and4MHz input are explicit laboratory inferences',
                'No native timer ISR, AP peer, sensor, pixels, saving or camera recovery is tested'])
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(message)


if __name__=='__main__':
    main()
