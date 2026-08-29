#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(script: str) -> None:
    print(f"\n>>> {script}", flush=True)
    result = subprocess.run([sys.executable, script], cwd=ROOT)
    if result.returncode:
        raise SystemExit(result.returncode)


def main() -> int:
    print("=" * 96)
    print("ÅkerPass WEB FAS 0 · frozen class 1–10 + SKO reference context")
    print("=" * 96)
    print("Steg 1–4 kör och verifierar legacy ÅkerPass MVP v1.1 oförändrat.")
    print("Steg 5–7 lägger endast på fryst ÅkerPrestation phase 0-referenskontext.")

    run("src/40_build_akervarde_public_index.py")
    run("src/41_build_akerpass_public_data.py")
    run("src/42_build_akerpass_frontend.py")
    run("src/43_verify_akerpass_web_v1.py")

    run("src/41b_enrich_akerpass_phase0_web.py")
    run("src/42b_patch_akerpass_frontend_phase0.py")
    run("src/43b_verify_akerpass_web_phase0.py")

    print("\n" + "=" * 96)
    print("ÅKERPASS WEB FAS 0: PASS")
    print("=" * 96)
    print("dist/index.html innehåller nu klass 1–10 + dominant SKO i Historik / referens.")
    print("Ingen ÅkerScore-, ÅkerVärde- eller ÅkerDrift-modell har ändrats.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
