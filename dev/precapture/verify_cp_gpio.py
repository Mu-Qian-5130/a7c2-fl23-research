"""Run host GPIO register/input isolation contracts; no camera or VM connector."""
from pathlib import Path
from support.host_test import host_test_main


def main():
    src = Path(__file__).parent / 'vm/cp_boot/gpio'
    host_test_main(src / 'test_state.c', (src / 'state.h', src / 'test_state.c'),
        name='gpio-test', description=__doc__,
        metadata=dict(physical_GPIO_qualified=False,
        tested=['direct-set-clear','strap-retention','input-output-isolation','undefined-input-rejection','unsupported-access-rejection'],
        limits=['No electrical pad/mux behavior, GPIO IRQ or inter-chip wiring is modeled',
                'No native peer-startup signal, AP/CP receipt, exposure, save or camera recovery is tested']))


if __name__=='__main__':main()
