"""Run host non-LL eDMA byte/ownership contracts; no camera or VM connector."""
from pathlib import Path
from support.host_test import host_test_main


def main():
    src = Path(__file__).parent / 'vm/cp_boot/edma'
    host_test_main(src / 'test_state.c', (src / 'state.h', src / 'test_state.c'),
        name='edma-test', description=__doc__,
        metadata=dict(physical_PCIe_qualified=False,peer_is_native_AP=False,
        tested=['actual-read-and-write-bytes','separate-local-and-peer-namespaces','absent-peer-retained-RUN',
                'partial-copy-abort-without-DONE','IRQ-mask-and-ack','active-config-preservation','unsupported-rejection'],
        limits=['Non-LL contract only; link, ATU, physical routing and detailed abort syndromes remain unqualified',
                'STOP/cancellation and original native IRQ handlers are not verified',
                'No AP/CP message receipt, sensor exposure, RAW ownership, save or camera recovery is tested']))


if __name__=='__main__':main()
