"""Run host GPIO register/input isolation contracts; no camera or VM connector."""
import argparse
import json
from pathlib import Path
from support.host_test import run_host_test


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zig',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();src=Path(__file__).parent/'vm/cp_boot/gpio'
    report,message=run_host_test(args.zig,args.output,src/'test_state.c',
                                (src/'state.h',src/'test_state.c'),name='gpio-test')
    report.update(physical_GPIO_qualified=False,
        tested=['direct-set-clear','strap-retention','input-output-isolation','undefined-input-rejection','unsupported-access-rejection'],
        limits=['No electrical pad/mux behavior, GPIO IRQ or inter-chip wiring is modeled',
                'No native peer-startup signal, AP/CP receipt, exposure, save or camera recovery is tested'])
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(message)


if __name__=='__main__':
    main()
