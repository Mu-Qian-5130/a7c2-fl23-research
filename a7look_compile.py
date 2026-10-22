#!/usr/bin/env python3
"""Compile a supplied DCP/CUBE into a four-stage A7C II .a7look, offline."""
from pathlib import Path
import json
import sys

root=Path(__file__).resolve().parent
runtime=root/'compiler-runtime.local.json'
if runtime.exists():
    sys.path[:0]=json.loads(runtime.read_text(encoding='utf-8')).get('python_paths',[])
sys.path.insert(0,str(root/'src/looks'))
from looktool.compilelook import main

if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ImportError,ValueError,RuntimeError,TimeoutError) as exc:
        print('Stopped: '+str(exc),file=sys.stderr)
        raise SystemExit(2)
