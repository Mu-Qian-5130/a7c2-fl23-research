"""Host-only SPI selector-bit checks; no VM or camera connector."""
from pathlib import Path
from support.host_test import host_test_main


def main():
    src = Path(__file__).parent / 'vm/cp_boot/spiclock'
    host_test_main(src / 'test_state.c', (src / 'state.h', src / 'test_state.c'),
        name='spi-select-test', description=__doc__,
        metadata=dict(physical_SPI_clock_qualified=False,
        limits=['Alias words and initial selection are explicit laboratory inputs',
                'No clock rate, physical readback, ready flag, sensor or IRQ is supplied',
                'No exposure, retained pixels, save/cancel or camera recovery is tested']))


if __name__=='__main__':main()
