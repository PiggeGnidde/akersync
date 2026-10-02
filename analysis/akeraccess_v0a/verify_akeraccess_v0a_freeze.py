#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
MANIFEST=ROOT/"work"/"akeraccess_v0a"/"freeze_v0a"/"akeraccess_v0a_freeze_manifest.json"


def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def main()->int:
    if not MANIFEST.exists():
        raise FileNotFoundError(f"Freeze manifest missing: {MANIFEST}")
    m=json.loads(MANIFEST.read_text(encoding="utf-8"))
    problems=[]
    for rel,spec in m["files"].items():
        p=ROOT/rel
        if not p.exists():
            problems.append("MISSING "+rel)
            continue
        if sha256(p)!=spec["sha256"]:
            problems.append("HASH MISMATCH "+rel)
        if int(p.stat().st_size)!=int(spec["bytes"]):
            problems.append("SIZE MISMATCH "+rel)

    prod=ROOT/"data"/"derived"/"akeraccess_v0a"/"akeraccess_v0a_fields.parquet"
    if prod.exists():
        d=pd.read_parquet(prod)
        a=m["anchors"]
        if len(d)!=int(a["population_fields"]):
            problems.append("PRODUCT POPULATION ANCHOR MISMATCH")
        if d["field_id"].astype(str).duplicated().any():
            problems.append("PRODUCT FIELD_ID DUPLICATE")
        n=int(pd.to_numeric(d["akeraccess_score_v0a"],errors="coerce").notna().sum())
        if n!=int(a["scored_fields"]):
            problems.append("PRODUCT SCORE COVERAGE ANCHOR MISMATCH")

    if problems:
        print("ÅkerAccess v0a FREEZE VERIFY: FAIL")
        for p in problems:
            print("  - "+p)
        return 2

    print("="*108)
    print("ÅkerAccess v0a FREEZE VERIFY")
    print("="*108)
    print(f"Freeze: {m['freeze_name']}")
    print(f"Files verified: {len(m['files'])}")
    print(f"Population: {m['anchors']['population_fields']:,}")
    print(f"Git HEAD at freeze: {m['git']['head_at_freeze']}")
    print("="*108)
    print("VERIFY_AKERACCESS_V0A_FREEZE: PASS")
    print("="*108)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
