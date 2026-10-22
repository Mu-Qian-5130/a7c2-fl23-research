#!/usr/bin/env python3
"""Install the once-configured Lightroom automatic profile companion."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent/'src/looks'))
from looktool.rawauto import main

if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,RuntimeError) as error:
        print('Stopped: '+str(error),file=sys.stderr);raise SystemExit(2)
