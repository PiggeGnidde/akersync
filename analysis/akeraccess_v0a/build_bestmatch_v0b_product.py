#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build canonical frozen ÅkerFrö × ÅkerAccess BestMatch v0b product.

Selected product policy:
  A before B (hard class order)
  then 50% ÄrtMatch + 25% road-based AreaLogistik + 25% frozen ÅkerAccess v0a.

D5 match-first and logistics-forward remain diagnostics only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_POLICY=ROOT/"config"/"akerfro_akeraccess_bestmatch_v0b_freeze.json"
DEFAULT_D5=ROOT/"work"/"akeraccess_v0a"/"bestmatch_d5"/"bestmatch_d5_fields.parquet"
DEFAULT_ACCESS=ROOT/"data"/"derived"/"akeraccess_v0a"/"akeraccess_v0a_fields.parquet"
DEFAULT_OUT=ROOT/"data"/"derived"/"akerfro_akeraccess_bestmatch_v0b"


def load_json(path:Path)->dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--policy",default=str(DEFAULT_POLICY))
    ap.add_argument("--d5",default=str(DEFAULT_D5))
    ap.add_argument("--akeraccess",default=str(DEFAULT_ACCESS))
    ap.add_argument("--out",default=str(DEFAULT_OUT))
    args=ap.parse_args()

    policy=load_json(Path(args.policy))
    d5_path=Path(args.d5)
    access_path=Path(args.akeraccess)
    if not d5_path.exists():
        raise FileNotFoundError(f"Run D5 first: {d5_path}")
    if not access_path.exists():
        raise FileNotFoundError(f"Freeze ÅkerAccess v0a first: {access_path}")

    d5=pd.read_parquet(d5_path).copy()
    acc=pd.read_parquet(access_path,columns=["field_id","akeraccess_score_v0a"]).copy()
    d5["field_id"]=d5["field_id"].astype(str)
    acc["field_id"]=acc["field_id"].astype(str)

    cand=d5[d5["d5_candidate"].fillna(False).astype(bool)].copy()
    cand=cand.merge(acc,on="field_id",how="left",validate="one_to_one")

    if len(cand)!=int(policy["expected_candidate_fields"]):
        raise RuntimeError(f"Candidate count drift: {len(cand):,}")

    # Establish formal lineage to the now-frozen generic ÅkerAccess v0a product.
    old=pd.to_numeric(cand["road_access_score"],errors="coerce")
    frozen=pd.to_numeric(cand["akeraccess_score_v0a"],errors="coerce")
    delta=(old-frozen).abs()
    maxdiff=float(delta.max()) if delta.notna().any() else float("nan")
    if not np.isfinite(maxdiff) or maxdiff>1e-9:
        raise RuntimeError(f"D5 RoadAccess != frozen ÅkerAccess v0a; max abs diff={maxdiff}")

    cand["bestmatch_v0b_score"]=pd.to_numeric(
        cand["bestmatch_d5_balanced_score"],errors="coerce"
    )
    cand["bestmatch_v0b_rank"]=pd.to_numeric(
        cand["rank_d5_balanced"],errors="coerce"
    ).astype("Int64")
    cand["bestmatch_v0b_policy"]="balanced_50_25_25"
    cand["bestmatch_v0b_status"]="SELECTED_PRODUCT_FOR_FORMAL_FREEZE"

    cand=cand.sort_values("bestmatch_v0b_rank",kind="mergesort").reset_index(drop=True)
    expected=np.arange(1,len(cand)+1)
    got=cand["bestmatch_v0b_rank"].to_numpy(dtype=int)
    if not np.array_equal(got,expected):
        raise RuntimeError("BestMatch v0b rank is not a complete 1..N ordering")

    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    fp=out/"bestmatch_v0b_fields.parquet"
    top=out/"bestmatch_v0b_top5000.csv"
    sp=out/"bestmatch_v0b_summary.json"

    cand.to_parquet(fp,index=False)
    cand.head(5000).to_csv(top,index=False,encoding="utf-8-sig")

    routed=cand["bjuv_proximity_d5_source"].eq("ROAD_NETWORK_D4")
    fallback=cand["bjuv_proximity_d5_source"].eq("C10_STRAIGHTLINE_FALLBACK")
    summary={
        "schema_version":"akerfro-akeraccess-bestmatch-v0b-product-v1",
        "freeze_name":policy["freeze_name"],
        "selected_policy":"balanced",
        "candidate_fields":int(len(cand)),
        "class_counts":{str(k):int(v) for k,v in cand["artkandidat_class"].value_counts().items()},
        "weights":policy["policy_weights"],
        "class_order":"A_STRONG_CANDIDATE before B_PHYSICAL_CANDIDATE; weighted score orders only within class",
        "akeraccess_lineage_max_abs_diff":maxdiff,
        "bjuv_route":{
            "routed_fields":int(routed.sum()),
            "straightline_fallback_fields":int(fallback.sum()),
            "route_coverage_pct":100.0*float(routed.mean()),
            "semantics":policy["route_semantics"],
            "fallback":policy["fallback_semantics"],
        },
        "historical_positive_fields":int(cand["historical_conservart_positive"].sum()),
        "top800":{
            "fields":800,
            "area_ha":float(pd.to_numeric(cand.head(800)["field_area_ha"],errors="coerce").sum()),
            "historical_positive_hits":int(cand.head(800)["historical_conservart_positive"].sum()),
            "mean_artmatch":float(pd.to_numeric(cand.head(800)["artmatch_score"],errors="coerce").mean()),
            "mean_road_area_logistics":float(pd.to_numeric(cand.head(800)["road_area_logistics_score"],errors="coerce").mean()),
            "mean_akeraccess":float(pd.to_numeric(cand.head(800)["akeraccess_score_v0a"],errors="coerce").mean()),
            "median_bjuv_road_km":float(pd.to_numeric(cand.head(800).loc[cand.head(800)["bjuv_route_status"].eq("ROUTED"),"field_to_bjuv_road_km"],errors="coerce").median()),
        },
        "guardrails":[
            "BestMatch v0b is a screening/ranking product, not an agronomic or access guarantee.",
            "RoadAccess cannot promote a C/D ÅkerFrö field into the A/B universe.",
            "A/B class order is hard; BestMatch score only orders within class.",
            "D4 road distance is approximate OSM network distance, not certified truck navigation.",
            "Missing D4 route uses explicit frozen-C10 straight-line fallback.",
            "Historical clean CONSERVART lift is diagnostic, not causal evidence.",
            "NVDB Slitlager is not used."
        ],
        "outputs":{"fields":str(fp),"top5000":str(top)}
    }
    sp.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    print("="*112)
    print("ÅkerFrö × ÅkerAccess BestMatch v0b PRODUCT BUILD")
    print("="*112)
    print(f"Candidates: {len(cand):,}")
    print(f"A/B: {summary['class_counts']}")
    print(f"ÅkerAccess lineage max abs diff: {maxdiff:.3g}")
    print(f"Bjuv routes: {int(routed.sum()):,} routed · {int(fallback.sum()):,} fallback · {100*routed.mean():.2f}% coverage")
    print(f"Top 800: {summary['top800']['area_ha']:.1f} ha · historical positives {summary['top800']['historical_positive_hits']}")
    print(f"Product: {fp}")
    print(f"Summary: {sp}")
    print("="*112)
    print("BestMatch v0b PRODUCT BUILD: PASS")
    print("="*112)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
