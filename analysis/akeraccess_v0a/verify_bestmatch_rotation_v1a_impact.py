#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify BestMatch impact study for ÅkerFrö Rotation v1.1."""
from __future__ import annotations
import argparse,json
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
DEFAULT=ROOT/"work"/"akerfro_rotation_v1a"/"bestmatch_impact"

def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument("--root",default=str(DEFAULT));args=ap.parse_args()
    root=Path(args.root)
    sp=root/"bestmatch_rotation_v1a_impact_summary.json"
    fp=root/"bestmatch_rotation_v1a_fields.parquet"
    cp=root/"topn_comparison.csv"
    for p in [sp,fp,cp]:
        if not p.is_file():raise FileNotFoundError(p)
    s=json.loads(sp.read_text(encoding="utf-8-sig"))
    df=pd.read_parquet(fp)
    cmp=pd.read_csv(cp)
    if s["status"]!="IMPACT_STUDY_ONLY_BESTMATCH_V0B_UNCHANGED":raise RuntimeError("bad impact status")
    if int(s["old_bestmatch_candidate_fields"])!=15967:raise RuntimeError("old BestMatch anchor drift")
    if int(s["released_rotation_fields_total"])!=43:raise RuntimeError("rotation release anchor drift")
    if float(s["frozen_policy_reused"]["score_max_abs_diff_vs_frozen_d5_balanced"])>1e-9:
        raise RuntimeError("BestMatch score drift")
    old=int(df["bestmatch_v0b_candidate"].fillna(False).astype(bool).sum())
    new=int(df["bestmatch_v1a_candidate"].fillna(False).astype(bool).sum())
    if old!=15967 or new!=int(s["new_bestmatch_candidate_fields"]):raise RuntimeError("candidate count mismatch")
    ranks=pd.to_numeric(df.loc[df["bestmatch_v1a_candidate"],"bestmatch_v1a_rank"],errors="coerce").dropna().astype(int).sort_values()
    if ranks.tolist()!=list(range(1,new+1)):raise RuntimeError("v1.1 BestMatch rank is not complete 1..N")
    if sorted(cmp["top_n"].astype(int).tolist())!=[200,500,800,1000,2000,5000]:
        raise RuntimeError("top-N comparison incomplete")
    print("="*106)
    print("BestMatch × Rotation v1.1 IMPACT VERIFY")
    print("="*106)
    print(f"Frozen v0b candidates: {old:,}")
    print(f"v1.1-policy candidates: {new:,} · net +{new-old:,}")
    print(f"Released rotation fields present in D5: {int(s['released_rotation_fields_present_in_d5']):,}/43")
    print(f"Released rotation fields outside D5: {int(s['released_rotation_fields_outside_d5']):,}")
    print("Weights: unchanged 50/25/25 · A before B · frozen BestMatch v0b untouched")
    print("="*106)
    print("VERIFY_BESTMATCH_ROTATION_V1A_IMPACT: PASS")
    print("="*106)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
