#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
MANIFEST=ROOT/"work"/"akeraccess_v0a"/"bestmatch_v0b_freeze"/"bestmatch_v0b_freeze_manifest.json"


def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def main()->int:
    if not MANIFEST.exists():
        raise FileNotFoundError(f"Manifest missing: {MANIFEST}")
    m=json.loads(MANIFEST.read_text(encoding="utf-8"))
    problems=[]

    for rel,spec in m["files"].items():
        p=ROOT/rel
        if not p.exists():
            problems.append("MISSING "+rel)
            continue
        if p.stat().st_size!=int(spec["bytes"]):
            problems.append("SIZE MISMATCH "+rel)
        if sha256(p)!=spec["sha256"]:
            problems.append("HASH MISMATCH "+rel)

    c10=Path(m["lineage"]["akerfro_c10"]["path"])
    if not c10.exists():
        problems.append("MISSING EXTERNAL C10 "+str(c10))
    else:
        if c10.stat().st_size!=int(m["lineage"]["akerfro_c10"]["bytes"]):
            problems.append("EXTERNAL C10 SIZE MISMATCH")
        if sha256(c10)!=m["lineage"]["akerfro_c10"]["sha256"]:
            problems.append("EXTERNAL C10 HASH MISMATCH")

    prod=ROOT/"data/derived/akerfro_akeraccess_bestmatch_v0b/bestmatch_v0b_fields.parquet"
    if prod.exists():
        d=pd.read_parquet(prod)
        a=m["anchors"]
        if len(d)!=int(a["candidate_fields"]):
            problems.append("PRODUCT CANDIDATE COUNT MISMATCH")
        if int(d.head(800)["historical_conservart_positive"].sum())!=int(a["top800_historical_positive_hits"]):
            problems.append("TOP800 HISTORICAL HIT ANCHOR MISMATCH")
        if not d["bestmatch_v0b_rank"].astype(int).tolist()==list(range(1,len(d)+1)):
            problems.append("PRODUCT RANK SEQUENCE MISMATCH")

    if problems:
        print("BestMatch v0b FREEZE VERIFY: FAIL")
        for p in problems:
            print("  - "+p)
        return 2

    print("="*114)
    print("ÅkerFrö × ÅkerAccess BestMatch v0b FREEZE VERIFY")
    print("="*114)
    print(f"Freeze: {m['freeze_name']}")
    print(f"Files verified: {len(m['files'])} + external C10")
    print(f"Candidates: {m['anchors']['candidate_fields']:,}")
    print(f"Git HEAD at freeze: {m['git']['head_at_freeze']}")
    print("="*114)
    print("VERIFY_BESTMATCH_V0B_FREEZE: PASS")
    print("="*114)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
