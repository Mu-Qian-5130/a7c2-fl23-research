"""Run host non-LL eDMA byte/ownership contracts; no camera or VM connector."""
import argparse
import json
from pathlib import Path
from support.host_test import run_host_test


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zig',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();src=Path(__file__).parent/'vm/cp_boot/edma'
    report,message=run_host_test(args.zig,args.output,src/'test_state.c',
                                (src/'state.h',src/'test_state.c'),name='edma-test')
    report.update(physical_PCIe_qualified=False,peer_is_native_AP=False,
        tested=['actual-read-and-write-bytes','separate-local-and-peer-namespaces','absent-peer-retained-RUN',
                'partial-copy-abort-without-DONE','IRQ-mask-and-ack','active-config-preservation','unsupported-rejection'],
        limits=['Non-LL contract only; link, ATU, physical routing and detailed abort syndromes remain unqualified',
                'STOP/cancellation and original native IRQ handlers are not verified',
                'No AP/CP message receipt, sensor exposure, RAW ownership, save or camera recovery is tested'])
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(message)


if __name__=='__main__':
    main()
