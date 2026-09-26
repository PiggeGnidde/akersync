#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "work/akerfro_ertor_v0a/operational_mvp_v0a_freeze/akerfro_operational_mvp_v0a_freeze_manifest.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if not MANIFEST.exists():
        raise FileNotFoundError(f"Freeze manifest missing: {MANIFEST}")
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))

    problems = []
    for rel, spec in m["files"].items():
        p = ROOT / rel
        if not p.exists():
            problems.append(f"MISSING {rel}")
            continue
        got = sha256(p)
        if got != spec["sha256"]:
            problems.append(f"HASH MISMATCH {rel}: {got} != {spec['sha256']}")
        if int(p.stat().st_size) != int(spec["bytes"]):
            problems.append(f"SIZE MISMATCH {rel}")

    c10 = ROOT / "data/derived/akerfro_ertor_v0a/artkandidat_v0a_operational_fields.parquet"
    if c10.exists():
        df = pd.read_parquet(c10)
        a = m["anchors"]
        if len(df) != int(a["population_fields"]):
            problems.append("POPULATION ANCHOR MISMATCH")
        classes = {str(k): int(v) for k, v in df["artkandidat_class"].value_counts().items()}
        if classes != {str(k): int(v) for k, v in a["class_counts"].items()}:
            problems.append("CLASS COUNT ANCHOR MISMATCH")
        bands = {str(k): int(v) for k, v in df["area_logistics_band"].value_counts().items()}
        if bands != {str(k): int(v) for k, v in a["operational_band_counts"].items()}:
            problems.append("OPERATIONAL BAND ANCHOR MISMATCH")

    if problems:
        print("ÅkerFrö operational MVP v0a FREEZE VERIFY: FAIL")
        for p in problems:
            print("  - " + p)
        return 2

    print("=" * 100)
    print("ÅkerFrö operational MVP v0a FREEZE VERIFY")
    print("=" * 100)
    print(f"Freeze: {m['freeze_name']}")
    print(f"Files verified: {len(m['files'])}")
    print(f"Population: {m['anchors']['population_fields']:,}")
    print(f"Git HEAD at freeze: {m['git']['head_at_freeze']}")
    print("=" * 100)
    print("VERIFY_AKERFRO_OPERATIONAL_MVP_V0A_FREEZE: PASS")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
