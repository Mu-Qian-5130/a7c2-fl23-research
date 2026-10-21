"""Host-only sparse request-state checks; no VM or camera connector."""
import argparse
import json
from pathlib import Path
from support.host_test import run_host_test


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zig',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();src=Path(__file__).parent/'vm/cp_boot/request_words'
    report,message=run_host_test(args.zig,args.output,src/'test_state.c',
        (src/'state.h',src/'test_state.c'),name='request-word-test')
    report.update(physical_hardware_qualified=False,
        limits=['Logical latches model requested bits; physical command effects and readback remain unqualified',
                'No clocks, reset completion, IRQ, readiness, pixels, save/cancel or recovery is supplied'])
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(message)


if __name__=='__main__':main()
