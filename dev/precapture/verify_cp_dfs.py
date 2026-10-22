"""Host-only inferred DFS protocol contracts; no VM/camera connector."""
from pathlib import Path
from support.host_test import host_test_main


def main():
    src = Path(__file__).parent / 'vm/cp_boot/dfs'
    host_test_main(src / 'test_state.c', (src / 'state.h', src / 'test_state.c'),
        name='dfs-test', description=__doc__,
        metadata=dict(physical_DFS_qualified=False,register_roles_inferred=True,
        limits=['No clock rates, power effects, IRQ wiring or silicon timing is supplied',
                'Explicit actor completion is not native hardware or peer success',
                'No exposure, pixels, save/cancel or camera recovery is tested']))


if __name__=='__main__':main()
