"""Rebuild the four small freestanding ARM64 workers, without camera access."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/looks'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zig')
    args = parser.parse_args()
    from looktool.nativebuild import compile_worker
    native = ROOT / 'src/vertical/native'
    for name in ('vertical_probe', 'vertical_enable_ram', 'vertical_disable_ram', 'aliases'):
        result = compile_worker(native / (name + '.c'), native / 'vertical_probe.c',
            ROOT / 'src/vertical/assets' / (name + '.so'), args.zig, fingerprints=False)
        print(name + '.so:', result['bytes'], 'bytes')


if __name__ == '__main__':
    main()
