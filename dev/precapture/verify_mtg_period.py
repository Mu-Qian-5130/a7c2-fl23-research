"""Host-only write-first period-word contracts; no timing or camera access."""
from pathlib import Path
from support.host_test import host_test_main


def main():
    root=Path(__file__).parent/'vm/cp_boot'
    host_test_main(root/'mtg_period/test_state.c',
        (root/'mtg_period/test_state.c',root/'config_rmw/state.h'),
        name='mtg-period-test',description=__doc__,
        metadata=dict(physical_timing_qualified=False,
            limits=['An unwritten word is undefined and cannot be read or partially updated',
                    'Full writes define separate software-requested words, never timing edges/IRQ/exposure']))


if __name__=='__main__':main()
