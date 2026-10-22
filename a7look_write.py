#!/usr/bin/env python3
"""Write a compiled A7Look using the shared selected-slot transaction CLI."""
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parent
runtime=ROOT/'compiler-runtime.local.json'
if runtime.exists():sys.path[:0]=json.loads(runtime.read_text(encoding='utf-8')).get('python_paths',[])
sys.path.insert(0,str(ROOT))
from lut import main

if __name__=='__main__':raise SystemExit(main())
