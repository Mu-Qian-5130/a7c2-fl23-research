"""Build/run only the host counter contract; never connects to a camera or VM."""
from pathlib import Path
from support.host_test import host_test_main


def main():
    src = Path(__file__).parent / 'vm/cp_boot/gptimer'
    host_test_main(src / 'counter_test.c', (src / 'counter.h', src / 'counter_test.c'),
        name='counter-test', description=__doc__,
        metadata=dict(physical_timer_qualified=False,
        tested=['elapsed-count','stopped-count','compare-before-and-at-deadline',
                'IRQ-clear','32bit-wrap','actual-divider-rate','unsupported-access-rejection'],
        limits=['mode2 behavior and4MHz input are explicit laboratory inferences',
                'No native timer ISR, AP peer, sensor, pixels, saving or camera recovery is tested']))


if __name__=='__main__':main()
