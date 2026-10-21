"""Host-only I2C clock/reset contracts; no VM or camera connector."""
import argparse
import json
from pathlib import Path
from support.host_test import run_host_test


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zig',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();src=Path(__file__).parent/'vm/cp_boot/i2c'
    report,message=run_host_test(args.zig,args.output,src/'test_state.c',
                                (src/'state.h',src/'test_state.c'),name='i2c-gate-test')
    report.update(physical_I2C_qualified=False,
        limits=['Only the clock/reset state is checked here; not FIFO, bytes or GIC',
                'No sensor, native peer, capture, camera boot or recovery is tested'])
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(message)


if __name__=='__main__':
    main()
