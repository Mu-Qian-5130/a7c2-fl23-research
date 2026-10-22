"""Host-only sparse request-state checks; no VM or camera connector."""
from pathlib import Path
from support.host_test import host_test_main


def main():
    src = Path(__file__).parent / 'vm/cp_boot/request_words'
    host_test_main(src / 'test_state.c', (src / 'state.h', src / 'test_state.c'),
        name='request-word-test', description=__doc__,
        metadata=dict(physical_hardware_qualified=False,
        limits=['Logical latches model requested bits; physical command effects and readback remain unqualified',
                'No clocks, reset completion, IRQ, readiness, pixels, save/cancel or recovery is supplied']))


if __name__=='__main__':main()
