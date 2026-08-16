#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from common import load_config

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def main() -> int:
    cfg_path = ROOT / "config" / "local_paths.json"
    cfg = load_config(cfg_path)
    out = ROOT / cfg.get("build_dir", "data/derived")
    out.mkdir(parents=True, exist_ok=True)

    cmd = [
        PY,
        str(ROOT / "src" / "04_hydrology_region.py"),
        "--dem", str(cfg["dem_dir"]),
        "--blocks", str(cfg["blocks"]),
        "--out", str(out),
        "--work-dir", str(cfg["whitebox_work_dir"]),
    ]

    print("=" * 72)
    print("ÅkerSync · hydrologi · hela Skåne")
    print("=" * 72)
    print("Detta kör endast hydrologisteget, inte BUILD_ALL.")
    print("DEM:", cfg["dem_dir"])
    print("Block:", cfg["blocks"])
    print("Output:", out)
    print("Whitebox work-dir:", cfg["whitebox_work_dir"])
    print()
    print("Startar:")
    print(" ".join(cmd))
    print()

    return subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
