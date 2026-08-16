#!/usr/bin/env python3
from pathlib import Path
import subprocess,sys

ROOT=Path(__file__).resolve().parents[1]
PY=sys.executable
GEOM=ROOT/"data/derived/geometry_v1a_skiften.csv"


def run(args):
    r=subprocess.run(args,cwd=ROOT)
    if r.returncode!=0:
        raise SystemExit(r.returncode)


# Geometry V1a is now part of the ÅkerSync field-information UI. Recompute only
# when its derived CSV is missing; otherwise web-only remains a quick rebuild.
if not GEOM.exists():
    run([PY,"src/09_geometry_v1a.py"])
run([PY,"src/07_build_web.py"])
run([PY,"src/07b_enhance_web_geometry_mobile.py"])
print("KLART: dist/index.html · Geometry V1a + mobil/GPS UI")
