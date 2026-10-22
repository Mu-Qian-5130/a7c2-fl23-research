"""A7C II 2.01 electronic shutter sound CLI (experimental feature branch)."""
from pathlib import Path
import sys


def main(argv=None):
    sys.path.insert(0, str(Path(__file__).resolve().parent / 'src/shutter_sound'))
    from sound_cli import main as run
    return run(argv)


if __name__ == '__main__':
    raise SystemExit(main())
