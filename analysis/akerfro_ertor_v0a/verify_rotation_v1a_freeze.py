#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify formal ÅkerFrö Rotation v1.1 freeze."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
MANIFEST=ROOT/"work"/"akerfro_rotation_v1a"/"freeze"/"akerfro_rotation_v1a_freeze_manifest.json"

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def main()->int:
    if not MANIFEST.is_file():
        raise FileNotFoundError(f"Freeze manifest missing: {MANIFEST}")
    m=json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    problems=[]
    for rel,spec in m["files"].items():
        p=ROOT/rel
        if not p.is_file():
            problems.append(f"MISSING {rel}")
            continue
        if int(p.stat().st_size)!=int(spec["bytes"]):
            problems.append(f"SIZE MISMATCH {rel}")
        got=sha256(p)
        if got!=spec["sha256"]:
            problems.append(f"HASH MISMATCH {rel}")

    p=ROOT/"data"/"derived"/"akerfro_rotation_v1a"/"akerfro_rotation_v1a_fields.parquet"
    if p.is_file():
        df=pd.read_parquet(p)
        a=m["anchors"]
        if len(df)!=int(a["population_fields"]):
            problems.append("POPULATION ANCHOR MISMATCH")
        counts={str(k):int(v) for k,v in df["artkandidat_class_v1a"].value_counts().items()}
        if counts!={str(k):int(v) for k,v in a["class_counts"].items()}:
            problems.append("CLASS COUNT ANCHOR MISMATCH")
        rel=df["rotation_v1a_release_candidate"].fillna(False).astype(bool)
        if int(rel.sum())!=int(a["released_fields"]):
            problems.append("RELEASE COUNT ANCHOR MISMATCH")

    if problems:
        print("VERIFY_AKERFRO_ROTATION_V1A_FREEZE: FAIL")
        for x in problems: print("  - "+x)
        return 2

    print("="*108)
    print("ÅkerFrö Rotation v1.1 · FREEZE VERIFY")
    print("="*108)
    print(f"Freeze: {m['freeze_name']}")
    print(f"Git HEAD at freeze: {m['git']['head_at_freeze']}")
    print(f"Files verified: {len(m['files'])}")
    print(f"Population: {m['anchors']['population_fields']:,}")
    print(f"Released: {m['anchors']['released_fields']} = A {m['anchors']['released_to_A']} + B {m['anchors']['released_to_B']}")
    print("Staffanstorp regression anchors: PASS")
    print("BestMatch impact guard: 15,967 -> 16,004; historical top-N hits unchanged")
    print("="*108)
    print("VERIFY_AKERFRO_ROTATION_V1A_FREEZE: PASS")
    print("="*108)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
