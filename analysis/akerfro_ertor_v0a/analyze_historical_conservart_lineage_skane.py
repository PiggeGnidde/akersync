#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only Skåne analysis of historical CONSERVART polygon lineage.

Purpose:
- quantify C_ROTATION_CAUTION cases caused only by mixed/partial CONSERVART;
- distinguish plausible historical split/merge lineage from tiny boundary spill;
- avoid choosing a blind current-field percentage threshold.

No frozen/model files are modified.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
RECENT_YEARS={2021,2022,2023,2024,2025}

def roots():
    seen=set()
    for p in [ROOT.parent/"AkerSync-Minne",Path(r"C:\AkerSync-Minne")]:
        try:p=p.resolve()
        except OSError:continue
        if p.exists() and p not in seen:
            seen.add(p);yield p

def municipality_dirs():
    for root in roots():
        d=root/"data"/"derived"/"akerminne_v1a"/"skane"/"municipalities"
        if d.is_dir():
            yield from sorted(x for x in d.iterdir() if x.is_dir())

def find_c8():
    for p in [
        ROOT.parent/"AkerSync-AkerFro"/"data"/"derived"/"akerfro_ertor_v0a"/"artkandidat_v0a_fields.parquet",
        Path(r"C:\AkerSync-AkerFro\data\derived\akerfro_ertor_v0a\artkandidat_v0a_fields.parquet"),
    ]:
        if p.is_file():return p
    raise FileNotFoundError("artkandidat_v0a_fields.parquet not found")

def is_conservart_name(s:pd.Series)->pd.Series:
    return s.fillna("").astype(str).str.lower().str.contains("konserv",regex=False)

def main():
    c8_path=find_c8()
    c8=pd.read_parquet(c8_path)
    c8["current_field_id"]=c8["current_field_id"].astype(str)
    recent_clean=pd.to_numeric(c8["last_conservart_clean_year"],errors="coerce").isin(RECENT_YEARS)
    mixed_only=(
        c8["rotation_status"].astype(str).eq("CAUTION_RECENT_CONSERVART")
        & ~recent_clean
    )
    targets=set(c8.loc[mixed_only,"current_field_id"].astype(str))
    print("="*126)
    print("ÅkerFrö · HISTORICAL CONSERVART LINEAGE · SKÅNE READ-ONLY")
    print("="*126)
    print(f"Frozen C8: {c8_path}")
    print(f"Recent CONSERVART caution without clean recent target: {len(targets):,}")

    pieces=[]
    scanned=0
    for d in municipality_dirs():
        p=d/"akerminne_components.parquet"
        if not p.is_file():continue
        cols=[
            "municipality","history_year","current_field_id",
            "historical_field_id","historical_block_id","historical_skiftesbeteckning",
            "crop_name","intersection_m2","share_current","share_historical",
            "same_admin_key","is_current_primary","is_historical_primary","is_mutual_primary",
        ]
        try:q=pd.read_parquet(p,columns=cols)
        except Exception:continue
        scanned+=1
        y=pd.to_numeric(q["history_year"],errors="coerce")
        q=q[y.isin(RECENT_YEARS) & is_conservart_name(q["crop_name"])].copy()
        if len(q):pieces.append(q)
    if not pieces:raise RuntimeError("No recent CONSERVART components found")
    comp=pd.concat(pieces,ignore_index=True)
    comp["current_field_id"]=comp["current_field_id"].astype(str)
    comp["historical_field_id"]=comp["historical_field_id"].astype(str)
    comp["share_current"]=pd.to_numeric(comp["share_current"],errors="coerce").fillna(0.0)
    comp["share_historical"]=pd.to_numeric(comp["share_historical"],errors="coerce").fillna(0.0)
    comp["intersection_m2"]=pd.to_numeric(comp["intersection_m2"],errors="coerce").fillna(0.0)

    # For each historical polygon/year: which current field captures the largest share?
    key=["history_year","historical_field_id"]
    dom=(comp.sort_values(["history_year","historical_field_id","share_historical","intersection_m2"],
                          ascending=[True,True,False,False],kind="mergesort")
         .groupby(key,as_index=False).first()[key+["current_field_id","share_historical","intersection_m2"]]
         .rename(columns={
             "current_field_id":"dominant_current_field_id",
             "share_historical":"dominant_historical_share",
             "intersection_m2":"dominant_intersection_m2",
         }))
    x=comp.merge(dom,on=key,how="left",validate="many_to_one")
    x["is_dominant_current"]=x["current_field_id"].eq(x["dominant_current_field_id"])
    x["other_dominates_95"]=~x["is_dominant_current"] & x["dominant_historical_share"].ge(.95)
    x["other_dominates_99"]=~x["is_dominant_current"] & x["dominant_historical_share"].ge(.99)
    x["other_dominates_999"]=~x["is_dominant_current"] & x["dominant_historical_share"].ge(.999)

    tx=x[x["current_field_id"].isin(targets)].copy()
    if tx.empty:raise RuntimeError("No component lineage rows for mixed-only caution target fields")

    # One row per target field: retain strongest evidence by historical share, then area.
    best=(tx.sort_values(["current_field_id","share_historical","intersection_m2"],
                         ascending=[True,False,False],kind="mergesort")
          .groupby("current_field_id",as_index=False).first())
    best=best.merge(
        c8[["current_field_id","municipality","artkandidat_class","rotation_status"]],
        on="current_field_id",how="left",validate="one_to_one",suffixes=("","_c8")
    )

    print(f"Municipalities scanned: {scanned}")
    print(f"Recent CONSERVART component rows: {len(comp):,}")
    print(f"Mixed-only caution fields with lineage row: {len(best):,}")
    print()
    print("BOUNDARY-SPILL SENSITIVITY")
    print("-"*126)
    rows=[]
    for dom_thr in [.95,.99,.999]:
        for own_thr in [.0001,.001,.005,.01,.02,.05]:
            spill=(~best["is_dominant_current"]
                   & best["dominant_historical_share"].ge(dom_thr)
                   & best["share_historical"].lt(own_thr))
            cspill=spill & best["artkandidat_class"].astype(str).eq("C_ROTATION_CAUTION")
            rows.append({
                "other_field_dominant_share_min":dom_thr,
                "this_field_historical_share_max":own_thr,
                "lineage_spill_fields":int(spill.sum()),
                "C_fields_affected":int(cspill.sum()),
            })
    tab=pd.DataFrame(rows)
    print(tab.to_string(index=False,formatters={
        "other_field_dominant_share_min":lambda v:f"{100*v:.1f}%",
        "this_field_historical_share_max":lambda v:f"{100*v:.3f}%",
    }))

    obvious=(~best["is_dominant_current"]
             & best["dominant_historical_share"].ge(.999)
             & best["share_historical"].lt(.001))
    ambiguous=(~best["is_dominant_current"] & ~obvious)
    direct=best["is_dominant_current"]

    print()
    print("DESCRIPTIVE EVIDENCE CLASSES (NOT A NEW PRODUCT POLICY)")
    print("-"*126)
    print(f"Dominant/current lineage:                 {int(direct.sum()):,}")
    print(f"Obvious boundary spill candidate:         {int(obvious.sum()):,}  [other field >=99.9%, this field <0.1% hist polygon]")
    print(f"Other non-dominant / boundary ambiguous:  {int(ambiguous.sum()):,}")
    print()
    print("SMALLEST 40 NON-DOMINANT LINEAGE SHARES")
    show=best[~best["is_dominant_current"]].sort_values(
        ["share_historical","intersection_m2","current_field_id"],kind="mergesort"
    ).head(40).copy()
    cols=[
        "current_field_id","municipality_c8","artkandidat_class","history_year",
        "historical_field_id","intersection_m2","share_current","share_historical",
        "dominant_current_field_id","dominant_historical_share",
        "same_admin_key","is_current_primary","is_historical_primary","is_mutual_primary",
    ]
    cols=[c for c in cols if c in show.columns]
    print(show[cols].to_string(index=False,formatters={
        "intersection_m2":lambda v:f"{float(v):.4f}",
        "share_current":lambda v:f"{100*float(v):.6f}%",
        "share_historical":lambda v:f"{100*float(v):.6f}%",
        "dominant_historical_share":lambda v:f"{100*float(v):.6f}%",
    }))

    work=ROOT/"work"/"akerfro_ertor_v0a"/"historical_conservart_lineage"
    work.mkdir(parents=True,exist_ok=True)
    tab.to_csv(work/"lineage_spill_sensitivity.csv",index=False,encoding="utf-8-sig")
    best.to_csv(work/"mixed_only_lineage_best.csv",index=False,encoding="utf-8-sig")
    print()
    print("Saved:",work/"lineage_spill_sensitivity.csv")
    print("Saved:",work/"mixed_only_lineage_best.csv")
    print("No frozen/model files changed.")
    print("="*126)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
