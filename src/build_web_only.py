#!/usr/bin/env python3
from pathlib import Path
import subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
raise SystemExit(subprocess.run([sys.executable,"src/07_build_web.py"],cwd=ROOT).returncode)
