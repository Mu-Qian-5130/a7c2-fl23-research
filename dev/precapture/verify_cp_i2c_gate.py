"""Host-only I2C clock/reset contracts; no VM or camera connector."""
from pathlib import Path
from support.host_test import host_test_main


def main():
    src = Path(__file__).parent / 'vm/cp_boot/i2c'
    host_test_main(src / 'test_state.c', (src / 'state.h', src / 'test_state.c'),
        name='i2c-gate-test', description=__doc__,
        metadata=dict(physical_I2C_qualified=False,
        limits=['Only the clock/reset state is checked here; not FIFO, bytes or GIC',
                'No sensor, native peer, capture, camera boot or recovery is tested']))


if __name__=='__main__':main()
