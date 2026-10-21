"""Run the host reset-mode watchdog contract; no camera or VM connector."""
import argparse
import json
from pathlib import Path
from support.host_test import run_host_test


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zig',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();src=Path(__file__).parent/'vm/cp_boot/watchdog'
    report,message=run_host_test(args.zig,args.output,src/'test_state.c',
                                (src/'state.h',src/'test_state.c'),name='watchdog-test')
    report.update(physical_watchdog_qualified=False,
        tested=['reset-and-release','remaining-count','initial-and-reload-TOP','valid-and-invalid-feed',
                'expiry','sticky-enable','unsupported-access-rejection'],
        limits=['Reset-mode model only; physical reset routing and TOP_INIT capability remain unqualified',
                'No native feeder-task lifetime, AP peer, capture, pixels, save or camera recovery is tested'])
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(message)


if __name__=='__main__':
    main()
