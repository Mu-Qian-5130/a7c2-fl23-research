"""Host-only MTG selector storage; no timing, IRQ, VM or camera connector."""
from pathlib import Path
from support.host_test import host_test_main


def main():
    root=Path(__file__).parent/'vm/cp_boot'
    host_test_main(root/'mtg_select/test_state.c',
        (root/'mtg_select/test_state.c',root/'config_rmw/state.h'),
        name='mtg-selector-test',description=__doc__,
        metadata=dict(physical_hardware_qualified=False,
            limits=['Only two-bit requested selection is stored under explicit initial words',
                    'No timing edges, frequency, IRQ, sensor, pixels or capture is supplied']))


if __name__=='__main__':main()
