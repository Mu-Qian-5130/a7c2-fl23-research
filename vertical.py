"""Experimental A7C II vertical shooting display; saved setting stays OFF."""
import argparse
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parent


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version='vertical-preview.1')
    commands = parser.add_subparsers(dest='command', required=True)
    descriptions = {
        'status': 'Read running/saved setting and portrait resource aliases',
        'enable': 'Add missing native-resource aliases and enable this running session',
        'disable': 'Turn off the running switch; keep resource aliases',
        'remove': 'Turn off the running switch and remove only the three exact aliases',
    }
    for name, description in descriptions.items():
        command = commands.add_parser(name, help=description)
        command.add_argument('--firmware-version', required=True, choices=['2.01'])
        command.add_argument('--work-dir', type=Path, default=Path('vertical-work'))
    args = parser.parse_args(argv)
    try:
        if sys.version_info < (3, 10) or struct.calcsize('P') != 8:
            raise ValueError('64-bit Python 3.10+ is required')
        sys.path[:0] = [str(ROOT / 'src/vertical'), str(ROOT / 'src/looks')]
        from verticaltool.device import execute
        result = execute(args.command, args.work_dir)
        print('Completed. Camera USB I/O has ended.')
        print('Running vertical display:', result['running'])
        print('Saved vertical display:', result['saved'])
        print('Portrait resource aliases:', result['alias_count'])
        print('Private report:', result['report'])
        if args.command == 'enable':
            print('Keep the camera ON, unplug USB and check both portrait directions.')
            print('The switch is RAM-only; after a reload, check status and enable again if needed.')
        return 0
    except KeyboardInterrupt:
        print('Interrupted. Preserve the work folder; inspect the outcome before another write.', file=sys.stderr)
        return 130
    except Exception as exc:
        print('Stopped: ' + str(exc), file=sys.stderr)
        print('Preserve the work folder. Do not blindly repeat an interrupted operation.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
