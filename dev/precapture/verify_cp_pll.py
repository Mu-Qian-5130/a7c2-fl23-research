"""Host-only inferred PLL state checks; no VM or camera connector."""
from pathlib import Path
from support.host_test import host_test_main


def main():
    src = Path(__file__).parent / 'vm/cp_boot/pll'
    host_test_main(src / 'test_state.c', (src / 'state.h', src / 'test_state.c'),
        name='pll-test', description=__doc__,
        metadata=dict(physical_PLL_qualified=False,
        limits=['Configuration/control/response roles and initial values are inferred laboratory semantics',
                'Fixture LOCK does not prove oscillator frequency, physical timing or valid coefficients',
                'No native peer, exposure, pixels, save/cancel or camera restoration is tested']))


if __name__=='__main__':main()
