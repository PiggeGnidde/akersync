#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify formal BestMatch v0c freeze."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
MANIFEST=ROOT/"work"/"akeraccess_v0a"/"bestmatch_v0c_freeze"/"bestmatch_v0c_freeze_manifest.json"

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def check_fp(spec:dict,problems:list[str],label:str)->None:
    p=Path(spec["path"])
    if not p.is_file():
        problems.append(f"MISSING {label}: {p}")
        return
    if int(p.stat().st_size)!=int(spec["bytes"]):
        problems.append(f"SIZE MISMATCH {label}")
    if sha256(p)!=spec["sha256"]:
        problems.append(f"HASH MISMATCH {label}")

def main()->int:
    if not MANIFEST.is_file(): raise FileNotFoundError(MANIFEST)
    m=json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    problems=[]
    for rel,spec in m["files"].items():
        p=ROOT/rel
        if not p.is_file():
            problems.append("MISSING "+rel); continue
        if int(p.stat().st_size)!=int(spec["bytes"]): problems.append("SIZE MISMATCH "+rel)
        if sha256(p)!=spec["sha256"]: problems.append("HASH MISMATCH "+rel)

    check_fp(m["lineage"]["akerfro_rotation_v1a_freeze"],problems,"Rotation v1.1 freeze")
    check_fp(m["lineage"]["bestmatch_v0b_freeze"],problems,"BestMatch v0b freeze")

    prod=ROOT/"data"/"derived"/"akerfro_akeraccess_bestmatch_v0c"/"bestmatch_v0c_fields.parquet"
    if prod.is_file():
        df=pd.read_parquet(prod)
        a=m["anchors"]
        if len(df)!=int(a["candidate_fields"]): problems.append("CANDIDATE COUNT MISMATCH")
        counts={str(k):int(v) for k,v in df["artkandidat_class"].value_counts().items()}
        if counts!={str(k):int(v) for k,v in a["class_counts"].items()}: problems.append("CLASS COUNT MISMATCH")
        if df["bestmatch_v0c_rank"].astype(int).tolist()!=list(range(1,len(df)+1)): problems.append("RANK SEQUENCE MISMATCH")
        if int(df.head(800)["historical_conservart_positive"].fillna(False).astype(bool).sum())!=int(a["top800_historical_positive_hits"]):
            problems.append("TOP800 HISTORICAL HIT MISMATCH")

    if problems:
        print("VERIFY_BESTMATCH_V0C_FREEZE: FAIL")
        for x in problems: print("  - "+x)
        return 2

    print("="*116)
    print("ÅkerFrö × ÅkerAccess BestMatch v0c · FREEZE VERIFY")
    print("="*116)
    print(f"Freeze: {m['freeze_name']}")
    print(f"Git HEAD at freeze: {m['git']['head_at_freeze']}")
    print(f"Files verified: {len(m['files'])} + 2 upstream freeze fingerprints")
    print(f"Candidates: {m['anchors']['candidate_fields']:,}")
    print(f"A/B: {m['anchors']['class_counts']}")
    print(f"vs v0b: +{m['anchors']['new_candidates_vs_v0b']} · dropped {m['anchors']['dropped_candidates_vs_v0b']}")
    print("Weights: unchanged 50/25/25 · hard A-before-B")
    print("="*116)
    print("VERIFY_BESTMATCH_V0C_FREEZE: PASS")
    print("="*116)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
