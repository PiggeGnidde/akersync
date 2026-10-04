#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify canonical BestMatch v0c candidate product before formal freeze."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_POLICY=ROOT/"config"/"akerfro_akeraccess_bestmatch_v0c_freeze.json"
DEFAULT_PRODUCT=ROOT/"data"/"derived"/"akerfro_akeraccess_bestmatch_v0c"/"bestmatch_v0c_fields.parquet"
DEFAULT_SUMMARY=ROOT/"data"/"derived"/"akerfro_akeraccess_bestmatch_v0c"/"bestmatch_v0c_summary.json"

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--policy",default=str(DEFAULT_POLICY))
    ap.add_argument("--product",default=str(DEFAULT_PRODUCT))
    ap.add_argument("--summary",default=str(DEFAULT_SUMMARY))
    args=ap.parse_args()

    policy=json.loads(Path(args.policy).read_text(encoding="utf-8-sig"))
    p=Path(args.product); sp=Path(args.summary)
    for x in [p,sp]:
        if not x.is_file(): raise FileNotFoundError(x)
    df=pd.read_parquet(p)
    s=json.loads(sp.read_text(encoding="utf-8-sig"))

    n=int(policy["expected_candidate_fields"])
    if len(df)!=n: raise RuntimeError(f"candidate count {len(df)} != {n}")
    if df["field_id"].astype(str).duplicated().any(): raise RuntimeError("duplicate field_id")
    counts={str(k):int(v) for k,v in df["artkandidat_class"].value_counts().items()}
    if counts!={str(k):int(v) for k,v in policy["expected_class_counts"].items()}:
        raise RuntimeError(f"class count mismatch: {counts}")
    if df["bestmatch_v0c_rank"].astype(int).tolist()!=list(range(1,n+1)):
        raise RuntimeError("rank sequence is not 1..N")
    n_a=int(policy["expected_class_counts"]["A_STRONG_CANDIDATE"])
    if not df.iloc[:n_a]["artkandidat_class"].eq("A_STRONG_CANDIDATE").all():
        raise RuntimeError("A tier contract failed")
    if not df.iloc[n_a:]["artkandidat_class"].eq("B_PHYSICAL_CANDIDATE").all():
        raise RuntimeError("B tier contract failed")
    if float(s["score_identity_max_abs_diff_vs_frozen_d5_balanced"])>1e-9:
        raise RuntimeError("50/25/25 score identity failed")
    if int(s["vs_v0b"]["new_candidates"])!=37 or int(s["vs_v0b"]["dropped_candidates"])!=0:
        raise RuntimeError("v0b set regression failed")
    if int(s["vs_v0b"]["new_A"])!=26 or int(s["vs_v0b"]["new_B"])!=11:
        raise RuntimeError("new A/B split regression failed")
    if int(s["top800"]["historical_positive_hits"])!=37:
        raise RuntimeError("top800 historical hit anchor failed")

    print("="*108)
    print("ÅkerFrö × ÅkerAccess BestMatch v0c · VERIFY")
    print("="*108)
    print(f"Candidates: {len(df):,} · A {counts['A_STRONG_CANDIDATE']:,} / B {counts['B_PHYSICAL_CANDIDATE']:,}")
    print("vs frozen v0b: +37 candidates · 0 dropped · new A/B = 26/11")
    print("Weights: unchanged 50/25/25 · hard A-before-B")
    print("Top-N historical-positive anchors: unchanged")
    print("="*108)
    print("VERIFY_BESTMATCH_V0C: PASS")
    print("="*108)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
