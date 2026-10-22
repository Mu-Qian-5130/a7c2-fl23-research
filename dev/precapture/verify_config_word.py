"""Host-only one-word fixture contracts; no VM, USB or firmware input."""
from pathlib import Path
from support.host_test import host_test_main


def main():
    src = Path(__file__).parent / 'vm/cp_boot/config_rmw'
    host_test_main(src / 'test_state.c', (src / 'state.h', src / 'test_state.c'),
        name='configuration-word-test', description=__doc__,
        metadata=dict(physical_hardware_qualified=False,
        limits=['Initial words are explicit test inputs, not physical reset values',
                'Only bit14 changes; no hardware acceptance, readiness, IRQ or capture is supplied']))


if __name__=='__main__':main()
