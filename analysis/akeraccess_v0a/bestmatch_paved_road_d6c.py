#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D6c — rebuild BestMatch candidate rankings with paved-road Väglogistik.

Input:
- D6b augmented field table (D5 + validated paved-public distance/score)

Change from D5:
- keep road-based AreaLogistik to Bjuv unchanged,
- replace local RoadAccess v0a with RoadAccess v0b (nearest drivable OSM +
  nearest paved statlig/kommunal NVDB road).

No frozen upstream product is modified.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_IN=ROOT/"work"/"akeraccess_v0a"/"surface_d6b"/"bestmatch_d6b_fields.parquet"
DEFAULT_OUT=ROOT/"work"/"akeraccess_v0a"/"bestmatch_d6c"
TOP_N=[200,500,800,1000,2000,5000]
POLICIES={
    "match_first":{"artmatch":0.60,"road_area_logistics":0.25,"local_road_access":0.15},
    "balanced":{"artmatch":0.50,"road_area_logistics":0.25,"local_road_access":0.25},
    "logistics_forward":{"artmatch":0.45,"road_area_logistics":0.30,"local_road_access":0.25},
}
CLASSES=["A_STRONG_CANDIDATE","B_PHYSICAL_CANDIDATE"]


def rank_within_class(df:pd.DataFrame,score_col:str,rank_col:str)->pd.DataFrame:
    out=df.copy()
    class_rank={c:i for i,c in enumerate(CLASSES)}
    out["_class_rank_d6c"]=out["artkandidat_class"].map(class_rank)
    q=out[out["artkandidat_class"].isin(CLASSES)].copy()
    q=q.sort_values(
        ["_class_rank_d6c",score_col,"field_id"],
        ascending=[True,False,True],
        na_position="last",
        kind="mergesort"
    )
    out[rank_col]=pd.NA
    out.loc[q.index,rank_col]=np.arange(1,len(q)+1)
    return out


def eval_rank(df:pd.DataFrame,rank_col:str)->list[dict]:
    q=df[df["artkandidat_class"].isin(CLASSES) & pd.to_numeric(df[rank_col],errors="coerce").notna()].copy()
    q[rank_col]=pd.to_numeric(q[rank_col],errors="coerce")
    total_pos=int(q["historical_conservart_positive"].sum())
    base=float(q["historical_conservart_positive"].mean()) if len(q) else math.nan
    rows=[]
    for n in TOP_N:
        g=q.nsmallest(min(n,len(q)),rank_col)
        hits=int(g["historical_conservart_positive"].sum())
        rate=float(g["historical_conservart_positive"].mean()) if len(g) else math.nan
        rows.append({
            "ranking":rank_col,
            "top_n":n,
            "n_fields":int(len(g)),
            "total_area_ha":float(pd.to_numeric(g["field_area_ha"],errors="coerce").sum()),
            "historical_positive_hits":hits,
            "historical_positive_enrichment":rate/base if base>0 else math.nan,
            "mean_artmatch":float(pd.to_numeric(g["artmatch_score"],errors="coerce").mean()),
            "mean_road_area_logistics":float(pd.to_numeric(g["road_area_logistics_score"],errors="coerce").mean()),
            "mean_road_access_old":float(pd.to_numeric(g["road_access_score"],errors="coerce").mean()),
            "mean_road_access_paved":float(pd.to_numeric(g["road_access_score_paved"],errors="coerce").mean()),
            "median_nearest_drivable_m":float(pd.to_numeric(g["nearest_drivable_osm_m"],errors="coerce").median()),
            "median_nearest_public_m":float(pd.to_numeric(g["nearest_statlig_kommunal_nvdb_m"],errors="coerce").median()),
            "median_nearest_paved_public_m":float(pd.to_numeric(g["nearest_belagd_statlig_kommunal_nvdb_m"],errors="coerce").median()),
            "median_bjuv_road_km":float(pd.to_numeric(g.loc[g["bjuv_route_status"].eq("ROUTED"),"field_to_bjuv_road_km"],errors="coerce").median()),
        })
    return rows


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",default=str(DEFAULT_IN))
    ap.add_argument("--out",default=str(DEFAULT_OUT))
    args=ap.parse_args()

    inp=Path(args.input)
    if not inp.exists():
        raise FileNotFoundError(f"Run D6b first: {inp}")

    d=pd.read_parquet(inp)
    required=[
        "field_id","artkandidat_class","artmatch_score","road_area_logistics_score",
        "road_access_score_paved","historical_conservart_positive",
        "nearest_belagd_statlig_kommunal_nvdb_m"
    ]
    missing=[c for c in required if c not in d.columns]
    if missing:
        raise RuntimeError("D6b input missing: "+", ".join(missing))

    print("="*120)
    print("ÅkerFrö × ÅkerAccess D6c - BESTMATCH WITH PAVED-ROAD VÄGLOGISTIK")
    print("="*120)

    for name,w in POLICIES.items():
        vals=[float(w[k]) for k in ["artmatch","road_area_logistics","local_road_access"]]
        score_col=f"bestmatch_d6c_{name}_score"
        rank_col=f"rank_d6c_{name}"
        d[score_col]=(
            vals[0]*pd.to_numeric(d["artmatch_score"],errors="coerce")+
            vals[1]*pd.to_numeric(d["road_area_logistics_score"],errors="coerce")+
            vals[2]*pd.to_numeric(d["road_access_score_paved"],errors="coerce")
        )
        d=rank_within_class(d,score_col,rank_col)

    rankings=[
        "rank_d5_match_first","rank_d5_balanced","rank_d5_logistics_forward",
        "rank_d6c_match_first","rank_d6c_balanced","rank_d6c_logistics_forward",
        "rank_c10_baseline",
    ]
    rows=[]
    for r in rankings:
        if r in d.columns:
            rows.extend(eval_rank(d,r))
    ev=pd.DataFrame(rows)

    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    fp=out/"bestmatch_d6c_fields.parquet"
    ep=out/"bestmatch_d6c_policy_comparison.csv"
    rp=out/"bestmatch_d6c_report.json"
    d.to_parquet(fp,index=False)
    ev.to_csv(ep,index=False,encoding="utf-8-sig")

    report={
        "schema_version":"akerfro-akeraccess-bestmatch-d6c-v0a",
        "status":"CANDIDATE_NOT_FROZEN",
        "change_from_d5":"replace local RoadAccess with D6b paved-public RoadAccess; Bjuv road-distance AreaLogistik unchanged",
        "policies":POLICIES,
        "validated_input":"D6b paved-public proximity retained D1 holdout signal at 50/100/250 m",
        "outputs":{"fields":str(fp),"comparison":str(ep)}
    }
    rp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")

    print("POLICY COMPARISON · OLD D5 vs NEW D6c")
    for n in TOP_N:
        print("-"*120)
        print(f"TOP {n}")
        q=ev[ev["top_n"].eq(n)]
        for r in q.itertuples(index=False):
            print(
                f"  {r.ranking:30s} hits={r.historical_positive_hits:4d} "
                f"enrich={r.historical_positive_enrichment:4.2f}x "
                f"Art={r.mean_artmatch:5.1f} "
                f"Väglog={r.mean_road_access_paved:5.1f} "
                f"PavedMed={r.median_nearest_paved_public_m:7.1f}m "
                f"BjuvMed={r.median_bjuv_road_km:6.1f}km "
                f"ha={r.total_area_ha:7.0f}"
            )
    print(f"\nFields: {fp}")
    print(f"Comparison: {ep}")
    print(f"Report: {rp}")
    print("="*120)
    print("ÅkerFrö × ÅkerAccess D6c: PASS")
    print("="*120)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
