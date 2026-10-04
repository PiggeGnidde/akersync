#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only sensitivity analysis for ÅkerFrö CONSERVART component materiality.

Tests how many C_ROTATION_CAUTION fields are caused only by tiny mixed/partial
CONSERVART overlaps, using frozen products only. No model/product files changed.
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
CANDIDATE_YEAR=2026
GAP=6
RECENT_MIN=CANDIDATE_YEAR-GAP+1  # 2021
RECENT_MAX=2025
THRESHOLDS=[0.0,0.001,0.005,0.01,0.02,0.05]

def roots():
    seen=set()
    for p in [ROOT, ROOT.parent/"AkerSync-AkerFro", Path(r"C:\AkerSync-AkerFro"), Path(r"C:\AkerSync-AkerAccess")]:
        try:p=p.resolve()
        except OSError:continue
        if p.exists() and p not in seen:
            seen.add(p);yield p

def find(rel:Path):
    for r in roots():
        p=r/rel
        if p.is_file(): return p
    return None

def main():
    c8=find(Path("data/derived/akerfro_ertor_v0a/artkandidat_v0a_fields.parquet"))
    mixed=find(Path("data/derived/akerfro_ertor_v0a/pea_mixed_or_complex_target_field_years.parquet"))
    if not c8 or not mixed:
        raise FileNotFoundError(f"Missing frozen inputs: C8={c8}, mixed={mixed}")

    f=pd.read_parquet(c8).copy()
    m=pd.read_parquet(mixed).copy()

    m["history_year"]=pd.to_numeric(m["history_year"],errors="coerce")
    m["target_crop_share_current"]=pd.to_numeric(m["target_crop_share_current"],errors="coerce")
    m["target_crop_area_m2"]=pd.to_numeric(m["target_crop_area_m2"],errors="coerce")
    mr=m[m["history_year"].between(RECENT_MIN,RECENT_MAX)].copy()

    agg=(mr.groupby("current_field_id",as_index=False)
         .agg(max_recent_mixed_share=("target_crop_share_current","max"),
              max_recent_mixed_area_m2=("target_crop_area_m2","max"),
              recent_mixed_rows=("history_year","size"),
              recent_mixed_latest_year=("history_year","max")))
    f=f.merge(agg,on="current_field_id",how="left",validate="one_to_one")
    for c in ["max_recent_mixed_share","max_recent_mixed_area_m2"]:
        f[c]=pd.to_numeric(f[c],errors="coerce").fillna(0.0)

    def recent_clean(col):
        x=pd.to_numeric(f[col],errors="coerce")
        return x.ge(RECENT_MIN)&x.le(RECENT_MAX)

    # Force plain bool Series. Parquet nullable dtypes can otherwise yield
    # object arrays containing pd.NA, which NumPy refuses as boolean indices.
    clean_target=recent_clean("last_conservart_clean_year").fillna(False).astype(bool)
    other_pea=recent_clean("last_other_pea_clean_year").fillna(False).astype(bool)
    faba=recent_clean("last_faba_bean_clean_year").fillna(False).astype(bool)
    original_c=f["artkandidat_class"].astype(str).eq("C_ROTATION_CAUTION").fillna(False).astype(bool)
    original_cons=f["rotation_status"].astype(str).eq("CAUTION_RECENT_CONSERVART").fillna(False).astype(bool)
    high=(f["artmatch_high"].fillna(False).astype(bool)
          if "artmatch_high" in f
          else f["artkandidat_class"].astype(str).isin(["A_STRONG_CANDIDATE","B_PHYSICAL_CANDIDATE","C_ROTATION_CAUTION"]).fillna(False).astype(bool))
    positive_pred=f["predecessor_prior"].astype(str).eq("POSITIVE").fillna(False).astype(bool)

    print("="*118)
    print("ÅkerFrö ROTATION COMPONENT MATERIALITY · READ-ONLY SKÅNE SENSITIVITY")
    print("="*118)
    print(f"Frozen C8: {c8}")
    print(f"Mixed/partial target components: {mixed}")
    print(f"Recent window: {RECENT_MIN}-{RECENT_MAX} · fields: {len(f):,}")
    print(f"Original C_ROTATION_CAUTION: {int(original_c.sum()):,}")
    print(f"Original CAUTION_RECENT_CONSERVART: {int(original_cons.sum()):,}")
    print()

    rows=[]
    for t in THRESHOLDS:
        mixed_material=(f["max_recent_mixed_share"].gt(0) if t==0 else f["max_recent_mixed_share"].ge(t)).fillna(False).astype(bool)
        target_recent=(clean_target|mixed_material).fillna(False).astype(bool)
        rotation_ok=(~(target_recent|other_pea|faba)).fillna(False).astype(bool)
        # Match frozen C8 precedence: conservart first, then other pea, then faba.
        status=np.full(len(f),"ROTATION_OK",dtype=object)
        status[faba.to_numpy(dtype=bool)]="CAUTION_RECENT_FABA"
        status[(other_pea & ~faba).to_numpy(dtype=bool)]="CAUTION_RECENT_OTHER_PEA"
        status[target_recent.to_numpy(dtype=bool)]="CAUTION_RECENT_CONSERVART"

        new_c=high & ~rotation_ok
        new_a=high & rotation_ok & positive_pred
        new_b=high & rotation_ok & ~positive_pred

        released=original_c & ~new_c
        rows.append({
            "min_component_share":t,
            "min_component_pct":100*t,
            "C_fields":int(new_c.sum()),
            "C_released_vs_original":int(released.sum()),
            "A_after":int(new_a.sum()),
            "B_after":int(new_b.sum()),
            "recent_target_fields":int(target_recent.sum()),
        })

    out=pd.DataFrame(rows)
    print(out.to_string(index=False,formatters={
        "min_component_pct":lambda x:f"{x:.3f}%",
    }))

    # Diagnose the suspect sliver-only population.
    sliver_only=(
        original_cons
        & ~clean_target
        & ~other_pea
        & ~faba
        & f["max_recent_mixed_share"].gt(0)
    )
    q=f.loc[sliver_only,[
        "current_field_id","municipality","artkandidat_class","rotation_status",
        "max_recent_mixed_share","max_recent_mixed_area_m2",
        "recent_mixed_rows","recent_mixed_latest_year"
    ]].copy()
    q["mixed_pct"]=100*q["max_recent_mixed_share"]
    q=q.sort_values(["max_recent_mixed_share","max_recent_mixed_area_m2","current_field_id"],kind="mergesort")

    print()
    print(f"Fields whose CONSERVART caution is mixed/partial-only: {len(q):,}")
    for t in [0.001,0.005,0.01,0.02,0.05]:
        print(f"  below {100*t:g}%: {int((q['max_recent_mixed_share']<t).sum()):,}")

    print()
    print("SMALLEST 30 MIXED/PARTIAL-ONLY CONSERVART TRIGGERS")
    show=q.head(30).copy()
    print(show.to_string(index=False,formatters={
        "max_recent_mixed_share":lambda x:f"{x:.9f}",
        "mixed_pct":lambda x:f"{x:.6f}%",
        "max_recent_mixed_area_m2":lambda x:f"{x:.3f}",
    }))

    work=ROOT/"work"/"akerfro_ertor_v0a"/"rotation_component_materiality"
    work.mkdir(parents=True,exist_ok=True)
    out.to_csv(work/"threshold_sensitivity.csv",index=False,encoding="utf-8-sig")
    q.to_csv(work/"mixed_partial_only_cautions.csv",index=False,encoding="utf-8-sig")
    print()
    print("Saved:",work/"threshold_sensitivity.csv")
    print("Saved:",work/"mixed_partial_only_cautions.csv")
    print("No frozen/model files changed.")
    print("="*118)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
