#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify ÅkerFrö Rotation v1.1 downstream candidate product."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_POLICY=ROOT/"config"/"akerfro_rotation_v1a.json"
DEFAULT_PRODUCT=ROOT/"data"/"derived"/"akerfro_rotation_v1a"/"akerfro_rotation_v1a_fields.parquet"

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--policy",default=str(DEFAULT_POLICY))
    ap.add_argument("--product",default=str(DEFAULT_PRODUCT))
    args=ap.parse_args()
    policy=json.loads(Path(args.policy).read_text(encoding="utf-8-sig"))
    p=Path(args.product)
    if not p.is_file(): raise FileNotFoundError(p)
    df=pd.read_parquet(p)
    a=policy["expected_anchors"]
    if len(df)!=int(a["population_fields"]): raise RuntimeError("population anchor mismatch")
    if df["current_field_id"].duplicated().any(): raise RuntimeError("duplicate current_field_id")

    changed=df["artkandidat_class_v0a"].astype(str).ne(df["artkandidat_class_v1a"].astype(str))
    if int(changed.sum())!=int(a["released_fields"]):
        raise RuntimeError(f"class changes expected {a['released_fields']}, got {int(changed.sum())}")
    bad=df.loc[changed & ~(
        df["artkandidat_class_v0a"].astype(str).eq("C_ROTATION_CAUTION")
        & df["artkandidat_class_v1a"].astype(str).isin(["A_STRONG_CANDIDATE","B_PHYSICAL_CANDIDATE"])
    )]
    if len(bad): raise RuntimeError("illegal v1.1 class transition outside C -> A/B")

    rel=df[df["rotation_v1a_release_candidate"].fillna(False).astype(bool)]
    if len(rel)!=int(a["released_fields"]): raise RuntimeError("release flag count mismatch")
    if not rel["rotation_status_v1a"].astype(str).eq("ROTATION_OK_BOUNDARY_SPILL").all():
        raise RuntimeError("released fields missing ROTATION_OK_BOUNDARY_SPILL")
    if not rel["all_recent_conservart_components_strict_spill"].fillna(False).astype(bool).all():
        raise RuntimeError("released field without all-components strict spill")
    if rel["rotation_v1a_recent_other_pea"].fillna(False).astype(bool).any():
        raise RuntimeError("released field still has recent OTHER_PEA")
    if rel["rotation_v1a_recent_faba"].fillna(False).astype(bool).any():
        raise RuntimeError("released field still has recent FABA")

    # Regression anchors from the Staffanstorp discovery case.
    by=df.set_index(df["current_field_id"].astype(str))
    expected={
        "61723351559|2A":("C_ROTATION_CAUTION","A_STRONG_CANDIDATE","ROTATION_OK_BOUNDARY_SPILL"),
        "61723351559|2B":("C_ROTATION_CAUTION","A_STRONG_CANDIDATE","ROTATION_OK_BOUNDARY_SPILL"),
        "61723353349|94A":("C_ROTATION_CAUTION","C_ROTATION_CAUTION","CAUTION_RECENT_CONSERVART"),
    }
    for fid,(old,new,status) in expected.items():
        if fid not in by.index: raise RuntimeError(f"regression anchor missing {fid}")
        r=by.loc[fid]
        if str(r["artkandidat_class_v0a"])!=old or str(r["artkandidat_class_v1a"])!=new or str(r["rotation_status_v1a"])!=status:
            raise RuntimeError(f"regression anchor failed {fid}")

    counts={str(k):int(v) for k,v in df["artkandidat_class_v1a"].value_counts().items()}
    if {k:counts.get(k,0) for k in a["v1a_class_counts"]}!=a["v1a_class_counts"]:
        raise RuntimeError(f"v1.1 class counts mismatch: {counts}")

    print("="*104)
    print("ÅkerFrö Rotation v1.1 · VERIFY")
    print("="*104)
    print(f"Fields: {len(df):,}")
    print(f"Class changes C -> A/B: {int(changed.sum()):,}")
    print(f"Released to A: {int(rel['artkandidat_class_v1a'].astype(str).eq('A_STRONG_CANDIDATE').sum()):,}")
    print(f"Released to B: {int(rel['artkandidat_class_v1a'].astype(str).eq('B_PHYSICAL_CANDIDATE').sum()):,}")
    print("Staffanstorp anchors: 2A PASS · 2B PASS · 94A PASS")
    print("Frozen v0a columns retained; v1.1 provenance explicit.")
    print("="*104)
    print("VERIFY_AKERFRO_ROTATION_V1A: PASS")
    print("="*104)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
