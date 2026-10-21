"""Host-only SPI selector-bit checks; no VM or camera connector."""
import argparse
import json
from pathlib import Path
from support.host_test import run_host_test


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zig',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();src=Path(__file__).parent/'vm/cp_boot/spiclock'
    report,message=run_host_test(args.zig,args.output,src/'test_state.c',
        (src/'state.h',src/'test_state.c'),name='spi-select-test')
    report.update(physical_SPI_clock_qualified=False,
        limits=['Alias words and initial selection are explicit laboratory inputs',
                'No clock rate, physical readback, ready flag, sensor or IRQ is supplied',
                'No exposure, retained pixels, save/cancel or camera recovery is tested'])
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(message)


if __name__=='__main__':main()
