"""Host-only inferred DFS protocol contracts; no VM/camera connector."""
import argparse
import json
from pathlib import Path
from support.host_test import run_host_test


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zig',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();src=Path(__file__).parent/'vm/cp_boot/dfs'
    report,message=run_host_test(args.zig,args.output,src/'test_state.c',
        (src/'state.h',src/'test_state.c'),name='dfs-test')
    report.update(physical_DFS_qualified=False,register_roles_inferred=True,
        limits=['No clock rates, power effects, IRQ wiring or silicon timing is supplied',
                'Explicit actor completion is not native hardware or peer success',
                'No exposure, pixels, save/cancel or camera recovery is tested'])
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(message)


if __name__=='__main__':main()
