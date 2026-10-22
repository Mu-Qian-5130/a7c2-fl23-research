#!/usr/bin/env python3
"""Identify A7C II RAW custom slots and apply their source DCP at import."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent/'src/looks'))
from looktool.rawimportcli import main

if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,RuntimeError,TimeoutError) as exc:
        print('Stopped: '+str(exc),file=sys.stderr)
        raise SystemExit(2)
