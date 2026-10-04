#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only candidate test for ÅkerFrö rotation v1.1.

Question:
Among frozen C_ROTATION_CAUTION fields, how many would become A/B if we ignore
ONLY recent CONSERVART components that are provable boundary spill?

Strict candidate spill rule per component:
  - another current field captures >=99.9% of the historical CONSERVART polygon,
  - this current field captures <0.1% of that historical polygon,
  - not same_admin_key,
  - not historical-primary,
  - not mutual-primary.

A field is released from CONSERVART caution only when:
  - no recent clean CONSERVART exists,
  - ALL recent CONSERVART component rows are strict spill,
  - no recent clean OTHER_PEA exists,
  - no recent clean FABA_BEAN exists.

No frozen/model files are modified.
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
RECENT_MIN=2021
RECENT_MAX=2025
DOMINANT_MIN=0.999
THIS_MAX=0.001

def find_c8()->Path:
    candidates=[
        ROOT.parent/"AkerSync-AkerFro"/"data"/"derived"/"akerfro_ertor_v0a"/"artkandidat_v0a_fields.parquet",
        Path(r"C:\AkerSync-AkerFro\data\derived\akerfro_ertor_v0a\artkandidat_v0a_fields.parquet"),
    ]
    for p in candidates:
        if p.is_file():
            return p
    raise FileNotFoundError("artkandidat_v0a_fields.parquet not found")

def minne_dirs():
    candidates=[
        ROOT.parent/"AkerSync-Minne"/"data"/"derived"/"akerminne_v1a"/"skane"/"municipalities",
        Path(r"C:\AkerSync-Minne\data\derived\akerminne_v1a\skane\municipalities"),
    ]
    for d in candidates:
        if d.is_dir():
            yield from sorted(p for p in d.iterdir() if p.is_dir())
            return
    raise FileNotFoundError("ÅkerMinne Skåne municipalities directory not found")

def recent_year(s:pd.Series)->pd.Series:
    x=pd.to_numeric(s,errors="coerce")
    return x.between(RECENT_MIN,RECENT_MAX,inclusive="both").fillna(False).astype(bool)

def is_conservart(s:pd.Series)->pd.Series:
    return s.fillna("").astype(str).str.lower().str.contains("konserv",regex=False)

def main()->int:
    c8_path=find_c8()
    c8=pd.read_parquet(c8_path).copy()
    c8["current_field_id"]=c8["current_field_id"].astype(str)

    c_mask=c8["artkandidat_class"].astype(str).eq("C_ROTATION_CAUTION")
    cons_status=c8["rotation_status"].astype(str).eq("CAUTION_RECENT_CONSERVART")
    no_clean_cons=~recent_year(c8["last_conservart_clean_year"])
    target_ids=set(c8.loc[c_mask & cons_status & no_clean_cons,"current_field_id"])
    if not target_ids:
        raise RuntimeError("No C fields with mixed/partial-only CONSERVART caution found")

    # We must inspect all recent CONSERVART polygons, not just the prior 'best row',
    # because release is permitted only if every component row is strict spill.
    pieces=[]
    scanned=0
    for d in minne_dirs():
        p=d/"akerminne_components.parquet"
        if not p.is_file():
            continue
        cols=[
            "history_year","current_field_id","historical_field_id",
            "crop_name","intersection_m2","share_current","share_historical",
            "same_admin_key","is_current_primary","is_historical_primary","is_mutual_primary",
        ]
        q=pd.read_parquet(p,columns=cols)
        scanned+=1
        y=pd.to_numeric(q["history_year"],errors="coerce")
        q=q[y.between(RECENT_MIN,RECENT_MAX,inclusive="both") & is_conservart(q["crop_name"])].copy()
        if len(q):
            q["current_field_id"]=q["current_field_id"].astype(str)
            q["historical_field_id"]=q["historical_field_id"].astype(str)
            pieces.append(q)

    if not pieces:
        raise RuntimeError("No recent CONSERVART component rows found")
    all_cons=pd.concat(pieces,ignore_index=True)
    for col in ["share_historical","share_current","intersection_m2"]:
        all_cons[col]=pd.to_numeric(all_cons[col],errors="coerce").fillna(0.0)

    key=["history_year","historical_field_id"]
    dominant=(
        all_cons.sort_values(
            ["history_year","historical_field_id","share_historical","intersection_m2"],
            ascending=[True,True,False,False],kind="mergesort"
        )
        .groupby(key,as_index=False).first()
        [key+["current_field_id","share_historical","intersection_m2"]]
        .rename(columns={
            "current_field_id":"dominant_current_field_id",
            "share_historical":"dominant_historical_share",
            "intersection_m2":"dominant_intersection_m2",
        })
    )
    x=all_cons[all_cons["current_field_id"].isin(target_ids)].merge(
        dominant,on=key,how="left",validate="many_to_one"
    )
    if x.empty:
        raise RuntimeError("No lineage rows found for target C fields")

    def b(col):
        return x[col].fillna(False).astype(bool)

    x["strict_spill"]=(
        x["current_field_id"].ne(x["dominant_current_field_id"])
        & x["dominant_historical_share"].ge(DOMINANT_MIN)
        & x["share_historical"].lt(THIS_MAX)
        & ~b("same_admin_key")
        & ~b("is_historical_primary")
        & ~b("is_mutual_primary")
    )

    by_field=(
        x.groupby("current_field_id",as_index=False)
        .agg(
            component_rows=("historical_field_id","size"),
            all_components_strict_spill=("strict_spill","all"),
            any_component_strict_spill=("strict_spill","any"),
            max_this_historical_share=("share_historical","max"),
            max_intersection_m2=("intersection_m2","max"),
            min_dominant_historical_share=("dominant_historical_share","min"),
        )
    )

    cols=[
        "current_field_id","municipality","artkandidat_class","rotation_status",
        "last_conservart_clean_year","last_conservart_any_component_year",
        "last_other_pea_clean_year","last_faba_bean_clean_year",
        "predecessor_prior","crop_2025_name","artmatch_score",
    ]
    cols=[c for c in cols if c in c8.columns]
    out=c8.loc[c8["current_field_id"].isin(target_ids),cols].merge(
        by_field,on="current_field_id",how="left",validate="one_to_one"
    )

    out["recent_other_pea"]=recent_year(out["last_other_pea_clean_year"])
    out["recent_faba"]=recent_year(out["last_faba_bean_clean_year"])
    out["all_components_strict_spill"]=out["all_components_strict_spill"].fillna(False).astype(bool)

    out["release_candidate"]=(
        out["all_components_strict_spill"]
        & ~out["recent_other_pea"]
        & ~out["recent_faba"]
    )
    pred=out["predecessor_prior"].fillna("UNKNOWN").astype(str)
    out["v11_candidate_class"]=out["artkandidat_class"].astype(str)
    rel=out["release_candidate"]
    out.loc[rel & pred.eq("POSITIVE"),"v11_candidate_class"]="A_STRONG_CANDIDATE"
    out.loc[rel & ~pred.eq("POSITIVE"),"v11_candidate_class"]="B_PHYSICAL_CANDIDATE"

    released=out[out["release_candidate"]].copy()
    blocked_other=out[
        out["all_components_strict_spill"]
        & (out["recent_other_pea"] | out["recent_faba"])
    ].copy()
    nonspill=out[~out["all_components_strict_spill"]].copy()

    print("="*126)
    print("ÅkerFrö ROTATION v1.1 · STRICT BOUNDARY-SPILL RELEASE TEST · READ ONLY")
    print("="*126)
    print(f"Frozen C8: {c8_path}")
    print(f"Municipalities scanned: {scanned}")
    print(f"C fields with CONSERVART caution but no recent clean CONSERVART: {len(out):,}")
    print()
    print("STRICT SPILL RULE")
    print(f"  other current field captures >= {100*DOMINANT_MIN:.1f}% of historical CONSERVART polygon")
    print(f"  this field captures < {100*THIS_MAX:.1f}% of historical polygon")
    print("  same_admin_key = false; historical-primary = false; mutual-primary = false")
    print("  ALL recent CONSERVART component rows for the field must satisfy the rule")
    print()
    print("RESULT")
    print(f"  All recent CONSERVART components are strict spill: {int(out['all_components_strict_spill'].sum()):,}")
    print(f"  ...but still blocked by recent OTHER_PEA/FABA:       {len(blocked_other):,}")
    print(f"  Released from rotation caution:                     {len(released):,}")
    if len(released):
        counts=released["v11_candidate_class"].value_counts()
        print(f"    C -> A_STRONG_CANDIDATE:                          {int(counts.get('A_STRONG_CANDIDATE',0)):,}")
        print(f"    C -> B_PHYSICAL_CANDIDATE:                        {int(counts.get('B_PHYSICAL_CANDIDATE',0)):,}")
    print(f"  Remain C because lineage is not all strict spill:   {len(nonspill):,}")
    print()
    print("RELEASED FIELDS")
    show_cols=[
        "current_field_id","municipality","v11_candidate_class","predecessor_prior",
        "last_other_pea_clean_year","last_faba_bean_clean_year",
        "component_rows","max_this_historical_share","min_dominant_historical_share",
        "max_intersection_m2",
    ]
    show_cols=[c for c in show_cols if c in released.columns]
    if len(released):
        print(released[show_cols].sort_values(
            ["v11_candidate_class","municipality","current_field_id"],kind="mergesort"
        ).to_string(index=False,formatters={
            "max_this_historical_share":lambda v:f"{100*float(v):.6f}%",
            "min_dominant_historical_share":lambda v:f"{100*float(v):.6f}%",
            "max_intersection_m2":lambda v:f"{float(v):.3f}",
        }))
    else:
        print("  NONE")

    work=ROOT/"work"/"akerfro_ertor_v0a"/"rotation_v11_strict_spill_test"
    work.mkdir(parents=True,exist_ok=True)
    out.to_csv(work/"all_candidate_fields.csv",index=False,encoding="utf-8-sig")
    released.to_csv(work/"released_c_to_ab.csv",index=False,encoding="utf-8-sig")
    blocked_other.to_csv(work/"strict_spill_but_other_legume_blocks.csv",index=False,encoding="utf-8-sig")
    nonspill.to_csv(work/"remain_c_nonspill_lineage.csv",index=False,encoding="utf-8-sig")
    print()
    print("Saved:",work)
    print("No frozen/model files changed.")
    print("="*126)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
