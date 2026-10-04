#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Final read-only audit for ÅkerFrö Rotation v1.1 candidate.

Summarizes:
- why released rotation fields fall outside BestMatch/D5,
- top-N churn under unchanged frozen BestMatch v0b policy,
- where the Staffanstorp discovery fields land.

No product files are modified.
"""
from __future__ import annotations
from pathlib import Path
import json
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
ROT=ROOT/"data"/"derived"/"akerfro_rotation_v1a"/"akerfro_rotation_v1a_fields.parquet"
IMPACT=ROOT/"work"/"akerfro_rotation_v1a"/"bestmatch_impact"
D0=ROOT/"work"/"akeraccess_v0a"/"skane_d0"/"skane_akeraccess_road_features_d0.parquet"
D0CFG=ROOT/"config"/"akeraccess_skane_d0.json"

def is_pasture(name:str,tokens:list[str])->bool:
    x=(name or "").strip().casefold()
    return any(t.casefold() in x for t in tokens)

def main()->int:
    for p in [ROT,D0CFG,IMPACT/"bestmatch_rotation_v1a_impact_summary.json",
              IMPACT/"bestmatch_rotation_v1a_fields.parquet",
              IMPACT/"topn_comparison.csv"]:
        if not p.exists():
            raise FileNotFoundError(p)

    rot=pd.read_parquet(ROT)
    imp=pd.read_parquet(IMPACT/"bestmatch_rotation_v1a_fields.parquet")
    cmp=pd.read_csv(IMPACT/"topn_comparison.csv")
    s=json.loads((IMPACT/"bestmatch_rotation_v1a_impact_summary.json").read_text(encoding="utf-8-sig"))
    cfg=json.loads(D0CFG.read_text(encoding="utf-8-sig"))

    rel=rot[rot["rotation_v1a_release_candidate"].fillna(False).astype(bool)].copy()
    rel["field_id"]=rel["current_field_id"].astype(str)
    in_d5=set(imp["field_id"].astype(str))
    rel["in_d5"]=rel["field_id"].isin(in_d5)

    area_col=None
    for c in ["field_area_ha","static__field_area_m2","current_area_m2"]:
        if c in rel.columns:
            area_col=c;break
    if area_col=="field_area_ha":
        rel["audit_area_ha"]=pd.to_numeric(rel[area_col],errors="coerce")
    elif area_col:
        rel["audit_area_ha"]=pd.to_numeric(rel[area_col],errors="coerce")/10000.0
    else:
        rel["audit_area_ha"]=pd.NA

    crop_col="crop_2025_name" if "crop_2025_name" in rel.columns else None
    tokens=list(cfg["pasture_name_tokens"])
    rel["audit_pasture_2025"]=(
        rel[crop_col].fillna("").astype(str).map(lambda x:is_pasture(x,tokens))
        if crop_col else False
    )
    rel["audit_d0_area_ok"]=pd.to_numeric(rel["audit_area_ha"],errors="coerce").ge(float(cfg["minimum_area_ha"]))
    rel["audit_expected_d0_eligible"]=rel["audit_d0_area_ok"] & ~rel["audit_pasture_2025"]

    missing=rel[~rel["in_d5"]].copy()
    def reason(r):
        if pd.notna(r["audit_area_ha"]) and not bool(r["audit_d0_area_ok"]):
            return "AREA_LT_1_HA"
        if bool(r["audit_pasture_2025"]):
            return "PASTURE_2025_EXCLUDED"
        return "UNEXPECTED_NOT_IN_D0_D5"
    if len(missing):
        missing["outside_d5_reason"]=missing.apply(reason,axis=1)

    print("="*112)
    print("ÅkerFrö Rotation v1.1 · FINAL READ-ONLY AUDIT")
    print("="*112)
    print(f"Released rotation fields: {len(rel):,}")
    print(f"Present in BestMatch/D5: {int(rel['in_d5'].sum()):,}")
    print(f"Outside BestMatch/D5: {len(missing):,}")
    if len(missing):
        print("\nOUTSIDE D5")
        show=["field_id","municipality","artkandidat_class_v1a","audit_area_ha","crop_2025_name","outside_d5_reason"]
        show=[c for c in show if c in missing.columns]
        print(missing[show].to_string(index=False,formatters={
            "audit_area_ha":lambda v:"NA" if pd.isna(v) else f"{float(v):.3f}"
        }))
        print("\nReason counts:")
        print(missing["outside_d5_reason"].value_counts().to_string())

    print("\nTOP-N IMPACT · UNCHANGED 50/25/25 POLICY")
    print("-"*112)
    showcmp=cmp.copy()
    if "old_area_ha" in showcmp and "new_area_ha" in showcmp:
        showcmp["area_delta_ha"]=showcmp["new_area_ha"]-showcmp["old_area_ha"]
    if "old_historical_positive_hits" in showcmp and "new_historical_positive_hits" in showcmp:
        showcmp["hit_delta"]=showcmp["new_historical_positive_hits"]-showcmp["old_historical_positive_hits"]
    cols=[c for c in [
        "top_n","new_rotation_v1a_entrants","old_rotation_v0b_exits",
        "old_area_ha","new_area_ha","area_delta_ha",
        "old_historical_positive_hits","new_historical_positive_hits","hit_delta"
    ] if c in showcmp.columns]
    print(showcmp[cols].to_string(index=False,formatters={
        "old_area_ha":lambda v:f"{float(v):.1f}",
        "new_area_ha":lambda v:f"{float(v):.1f}",
        "area_delta_ha":lambda v:f"{float(v):+.1f}",
    }))

    entrants=imp[imp["bestmatch_v1a_candidate"].fillna(False).astype(bool)
                 & ~imp["bestmatch_v0b_candidate"].fillna(False).astype(bool)].copy()
    entrants["bestmatch_v1a_rank_num"]=pd.to_numeric(entrants["bestmatch_v1a_rank"],errors="coerce")
    print("\nNEW v1.1 BESTMATCH ENTRANTS")
    print("-"*112)
    if len(entrants):
        ranks=entrants["bestmatch_v1a_rank_num"].dropna()
        print(f"Count: {len(entrants):,}")
        print(f"Rank min/median/max: {int(ranks.min())} / {float(ranks.median()):.1f} / {int(ranks.max())}")
        print(f"In top 200/500/800/1000: "
              f"{int((ranks<=200).sum())}/{int((ranks<=500).sum())}/{int((ranks<=800).sum())}/{int((ranks<=1000).sum())}")

    print("\nSTAFFANSTORP DISCOVERY CASE")
    print("-"*112)
    for fid in ["61723351559|2A","61723351559|2B","61723353349|94A"]:
        rr=rot[rot["current_field_id"].astype(str).eq(fid)]
        ii=imp[imp["field_id"].astype(str).eq(fid)]
        if rr.empty:
            print(f"{fid}: missing from Rotation v1.1")
            continue
        r=rr.iloc[0]
        text=f"{fid}: {r['artkandidat_class_v0a']} -> {r['artkandidat_class_v1a']} · {r['rotation_status_v1a']}"
        if not ii.empty:
            x=ii.iloc[0]
            if bool(x.get("bestmatch_v1a_candidate",False)):
                rank=pd.to_numeric(pd.Series([x.get("bestmatch_v1a_rank")]),errors="coerce").iloc[0]
                text+=f" · BestMatch v1.1 rank {int(rank) if pd.notna(rank) else 'NA'}"
            else:
                text+=" · outside v1.1 BestMatch candidate set"
        else:
            text+=" · outside D5 universe"
        print(text)

    unexpected=missing[missing.get("outside_d5_reason",pd.Series(dtype=str)).eq("UNEXPECTED_NOT_IN_D0_D5")] if len(missing) else missing
    print("\nAUDIT VERDICT")
    print("-"*112)
    if len(unexpected):
        print(f"ATTENTION: {len(unexpected)} released fields are unexpectedly absent from D0/D5 despite eligibility.")
        print("Do not freeze until investigated.")
        return 2
    print("PASS: every released field outside D5 is explained by the frozen D0 eligibility policy.")
    print("No frozen/model files changed.")
    print("="*112)
    print("AKERFRO ROTATION V1.1 FINAL AUDIT: PASS")
    print("="*112)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
