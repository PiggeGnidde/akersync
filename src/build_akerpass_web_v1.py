#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(script: str) -> None:
    result = subprocess.run([sys.executable, script], cwd=ROOT)
    if result.returncode:
        raise SystemExit(result.returncode)


def main() -> int:
    print("=" * 96)
    print("ÅkerPass MVP UI V1 · public index → kommunfiler → frontend → QA")
    print("=" * 96)
    run("src/40_build_akervarde_public_index.py")
    run("src/41_build_akerpass_public_data.py")
    run("src/42_build_akerpass_frontend.py")
    run("src/43_verify_akerpass_web_v1.py")
    print("KLART: dist/index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
