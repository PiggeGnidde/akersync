#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D5 — ÅkerFrö × ÅkerAccess BestMatch with actual OSM road distance to Bjuv.

Frozen inputs remain read-only:
- ÅkerFrö C10
- ÅkerAccess D0/D1/D2
- D4 route-distance layer

D5 replaces only the downstream Bjuv logistics proxy:
  old: straight-line distance
  new: mapped road-network distance where available

Three transparent, predeclared ranking policies are compared. None is frozen.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
for p in (ROOT,ROOT/"src"):
    if str(p) not in sys.path:
        sys.path.insert(0,str(p))

from analysis.akeraccess_v0a.akerfro_access_bestmatch_d2 import discover_c10
from analysis.akerfro_ertor_v0a.operational_c10 import piecewise_score

DEFAULT_CFG=ROOT/"config"/"akerfro_akeraccess_d5.json"
DEFAULT_D4=ROOT/"work"/"akeraccess_v0a"/"bjuv_route_d4"/"bestmatch_d4_fields.parquet"
DEFAULT_C10CFG=ROOT/"config"/"akerfro_ertor_c10.json"
DEFAULT_OUT=ROOT/"work"/"akeraccess_v0a"/"bestmatch_d5"


def load_json(p:Path)->dict[str,Any]:
    return json.loads(p.read_text(encoding="utf-8-sig"))


def norm_id(x:Any)->str:
    if x is None:
        return ""
    s=str(x).strip()
    if s.endswith(".0"):
        try:
            return str(int(float(s)))
        except Exception:
            pass
    return s


def add_road_logistics(
    d4:pd.DataFrame,
    c10:pd.DataFrame,
    c10cfg:dict[str,Any]
)->pd.DataFrame:
    c=c10[[
        "current_field_id","area_fit_score","bjuv_proximity_score"
    ]].copy()
    c["field_id"]=c["current_field_id"].map(norm_id)
    c=c.drop(columns=["current_field_id"])
    out=d4.merge(c,on="field_id",how="left",validate="one_to_one")

    road_km=pd.to_numeric(out["field_to_bjuv_road_km"],errors="coerce")
    dcfg=c10cfg["bjuv_proximity"]
    out["road_bjuv_proximity_score"]=piecewise_score(
        road_km,
        [float(x) for x in dcfg["knots_km"]],
        [float(x) for x in dcfg["scores"]],
        float(dcfg["above_last_knot_score"]),
    )

    # Keep the full screening universe. Missing D4 routes fall back to frozen
    # C10 straight-line proximity, with source explicitly retained.
    routed=road_km.notna() & out["bjuv_route_status"].eq("ROUTED")
    out["bjuv_proximity_d5_source"]=np.where(
        routed,"ROAD_NETWORK_D4","C10_STRAIGHTLINE_FALLBACK"
    )
    out["bjuv_proximity_d5_score"]=out["road_bjuv_proximity_score"]
    out.loc[~routed,"bjuv_proximity_d5_score"]=pd.to_numeric(
        out.loc[~routed,"bjuv_proximity_score"],errors="coerce"
    )

    w=c10cfg["area_logistics"]["weights"]
    wa=float(w["area_fit"]); wb=float(w["bjuv_proximity"])
    out["road_area_logistics_score"]=(
        wa*pd.to_numeric(out["area_fit_score"],errors="coerce")
        +wb*pd.to_numeric(out["bjuv_proximity_d5_score"],errors="coerce")
    )
    return out


def add_policy_scores(df:pd.DataFrame,cfg:dict[str,Any])->pd.DataFrame:
    out=df.copy()
    classes=list(cfg["candidate_classes"])
    out["d5_candidate"]=out["artkandidat_class"].isin(classes)
    class_rank={c:i for i,c in enumerate(classes)}
    out["_class_rank_d5"]=out["artkandidat_class"].map(class_rank)

    for name,w in cfg["policies"].items():
        vals=[float(w[k]) for k in ["artmatch","road_area_logistics","local_road_access"]]
        if abs(sum(vals)-1.0)>1e-12:
            raise RuntimeError(f"D5 policy {name} weights do not sum to 1")
        score=(
            vals[0]*pd.to_numeric(out["artmatch_score"],errors="coerce")
            +vals[1]*pd.to_numeric(out["road_area_logistics_score"],errors="coerce")
            +vals[2]*pd.to_numeric(out["road_access_score"],errors="coerce")
        )
        scol=f"bestmatch_d5_{name}_score"
        rcol=f"rank_d5_{name}"
        out[scol]=score

        q=out[out["d5_candidate"]].copy()
        q=q.sort_values(
            ["_class_rank_d5",scol,"field_id"],
            ascending=[True,False,True],
            na_position="last",
            kind="mergesort"
        )
        out[rcol]=pd.NA
        out.loc[q.index,rcol]=np.arange(1,len(q)+1)

    return out


def eval_rank(df:pd.DataFrame,rank_col:str,top_n:list[int])->list[dict[str,Any]]:
    q=df[df["d5_candidate"] & pd.to_numeric(df[rank_col],errors="coerce").notna()].copy()
    q[rank_col]=pd.to_numeric(q[rank_col],errors="coerce")
    total_pos=int(q["historical_conservart_positive"].sum())
    base=float(q["historical_conservart_positive"].mean()) if len(q) else math.nan
    rows=[]
    for n in top_n:
        g=q.nsmallest(min(int(n),len(q)),rank_col)
        hits=int(g["historical_conservart_positive"].sum())
        rate=float(g["historical_conservart_positive"].mean()) if len(g) else math.nan
        routed=g["bjuv_route_status"].eq("ROUTED")
        rows.append({
            "ranking":rank_col,
            "top_n":int(n),
            "n_fields":int(len(g)),
            "total_area_ha":float(pd.to_numeric(g["field_area_ha"],errors="coerce").sum()),
            "historical_positive_hits":hits,
            "historical_positive_recall":hits/total_pos if total_pos else math.nan,
            "historical_positive_enrichment":rate/base if base>0 else math.nan,
            "mean_artmatch":float(pd.to_numeric(g["artmatch_score"],errors="coerce").mean()),
            "mean_road_area_logistics":float(pd.to_numeric(g["road_area_logistics_score"],errors="coerce").mean()),
            "mean_local_road_access":float(pd.to_numeric(g["road_access_score"],errors="coerce").mean()),
            "median_bjuv_road_km":float(pd.to_numeric(g.loc[routed,"field_to_bjuv_road_km"],errors="coerce").median()) if routed.any() else math.nan,
            "median_bjuv_straight_km":float(pd.to_numeric(g["distance_bjuv_km"],errors="coerce").median()),
            "median_nearest_drivable_m":float(pd.to_numeric(g["nearest_drivable_osm_m"],errors="coerce").median()),
            "median_nearest_statlig_kommunal_m":float(pd.to_numeric(g["nearest_statlig_kommunal_nvdb_m"],errors="coerce").median()),
            "route_coverage_pct":100.0*float(routed.mean()) if len(g) else math.nan,
        })
    return rows


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--config",default=str(DEFAULT_CFG))
    ap.add_argument("--d4",default=str(DEFAULT_D4))
    ap.add_argument("--c10",default=None)
    ap.add_argument("--c10-config",default=str(DEFAULT_C10CFG))
    ap.add_argument("--out",default=str(DEFAULT_OUT))
    args=ap.parse_args()

    cfg=load_json(Path(args.config))
    c10cfg=load_json(Path(args.c10_config))
    d4_path=Path(args.d4)
    if not d4_path.exists():
        raise FileNotFoundError(f"Run D4 first: {d4_path}")
    c10_path=discover_c10(args.c10)

    d4=pd.read_parquet(d4_path)
    c10=pd.read_parquet(c10_path)
    d4["field_id"]=d4["field_id"].map(norm_id)
    c10["current_field_id"]=c10["current_field_id"].map(norm_id)

    print("="*124)
    print("ÅkerFrö × ÅkerAccess D5 - ROAD-LOGISTICS BESTMATCH")
    print("="*124)
    print(f"D4:  {d4_path}")
    print(f"C10: {c10_path}")

    out=add_road_logistics(d4,c10,c10cfg)
    out=add_policy_scores(out,cfg)

    ab=out["d5_candidate"]
    routed=out["bjuv_route_status"].eq("ROUTED")
    cov=100.0*float((ab&routed).sum())/float(ab.sum())
    fallback=int((ab & ~routed).sum())
    print(f"A/B candidate fields: {int(ab.sum()):,}")
    print(f"D4 route coverage A/B: {int((ab&routed).sum()):,}/{int(ab.sum()):,} = {cov:.2f}%")
    print(f"Straight-line fallback A/B: {fallback:,}")
    warn_thr=float(cfg["minimum_ab_route_coverage_pct_for_no_warning"])
    if cov<warn_thr:
        print(f"WARNING: A/B route coverage below configured {warn_thr:.1f}% threshold")

    # Compare against frozen C10 and D2 Balanced as well as the three D5 policies.
    rankings=[
        "rank_c10_baseline",
        "rank_bestmatch_balanced",
        "rank_d5_match_first",
        "rank_d5_balanced",
        "rank_d5_logistics_forward",
    ]
    rows=[]
    for r in rankings:
        if r in out.columns:
            rows.extend(eval_rank(out,r,list(map(int,cfg["top_n"]))))
    ev=pd.DataFrame(rows)

    od=Path(args.out); od.mkdir(parents=True,exist_ok=True)
    fp=od/"bestmatch_d5_fields.parquet"
    ep=od/"bestmatch_d5_policy_comparison.csv"
    top=od/"bestmatch_d5_balanced_top5000.csv"
    out.to_parquet(fp,index=False)
    ev.to_csv(ep,index=False,encoding="utf-8-sig")

    qq=out[out["d5_candidate"]].copy()
    qq["rank_d5_balanced"]=pd.to_numeric(qq["rank_d5_balanced"],errors="coerce")
    qq.sort_values("rank_d5_balanced",kind="mergesort").head(5000).to_csv(
        top,index=False,encoding="utf-8-sig"
    )

    report={
        "schema_version":cfg["schema_version"],
        "inputs":{"d4":str(d4_path),"c10":str(c10_path)},
        "candidate_fields":int(ab.sum()),
        "route_coverage_ab_pct":cov,
        "route_fallback_ab_fields":fallback,
        "road_area_logistics":{
            "area_fit_source":"frozen C10",
            "bjuv_proximity_curve":"same frozen C10 piecewise curve, evaluated on D4 road distance",
            "weights":c10cfg["area_logistics"]["weights"],
            "missing_route_policy":"explicit fallback to frozen C10 straight-line proximity"
        },
        "policies":cfg["policies"],
        "decision_status":"CANDIDATE_ONLY_NOT_FROZEN",
        "guardrails":[
            "Frozen C10 and frozen ÄrtMatch are read-only.",
            "D5 weights are predeclared transparent policies, not fitted to historical pea labels.",
            "Historical positive lift is diagnostic only and must not be the sole selection criterion.",
            "D4 road distance is approximate OSM network distance, not certified truck navigation.",
            "Fields without a D4 route retain frozen C10 straight-line proximity and are explicitly flagged."
        ],
        "outputs":{"fields":str(fp),"comparison":str(ep),"balanced_top5000":str(top)}
    }
    rp=od/"bestmatch_d5_report.json"
    rp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")

    print("\nPOLICY COMPARISON")
    for n in list(map(int,cfg["top_n"])):
        print("-"*124)
        print(f"TOP {n}")
        q=ev[ev["top_n"].eq(n)]
        for r in q.itertuples(index=False):
            print(
                f"  {r.ranking:30s} hits={r.historical_positive_hits:4d} "
                f"enrich={r.historical_positive_enrichment:4.2f}x "
                f"Art={r.mean_artmatch:5.1f} "
                f"RoadArea={r.mean_road_area_logistics:5.1f} "
                f"LocalRoad={r.mean_local_road_access:5.1f} "
                f"BjuvRoadMed={r.median_bjuv_road_km:6.1f}km "
                f"PublicMed={r.median_nearest_statlig_kommunal_m:6.1f}m "
                f"ha={r.total_area_ha:7.0f}"
            )

    print(f"\nFields: {fp}")
    print(f"Comparison: {ep}")
    print(f"Report: {rp}")
    print("="*124)
    print("ÅkerFrö × ÅkerAccess D5: PASS")
    print("="*124)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
