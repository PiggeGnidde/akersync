#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D2 — join frozen ÅkerFrö operational product with validated ÅkerAccess D0.

This stage is exploratory/product-facing. It does not modify either freeze.

Outputs:
- one joined road-eligible field table,
- three candidate rankings (C10 baseline, access-first, balanced BestMatch),
- recent-2023..2025 historical enrichment diagnostics,
- map-ready GeoJSON for the top candidates.

No API calls.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer

ROOT=Path(__file__).resolve().parents[2]
for p in (ROOT,ROOT/"src"):
    if str(p) not in sys.path:
        sys.path.insert(0,str(p))

from analysis.akeraccess_v0a.skane_pea_replication_d1 import load_history

DEFAULT_CFG=ROOT/"config"/"akerfro_akeraccess_d2.json"
DEFAULT_D0=ROOT/"work"/"akeraccess_v0a"/"skane_d0"/"skane_akeraccess_road_features_d0.parquet"
DEFAULT_AKERMINNE=Path(r"C:\AkerSync-Minne")
DEFAULT_OUT=ROOT/"work"/"akeraccess_v0a"/"bestmatch_d2"


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


def load_cfg(p:Path)->dict[str,Any]:
    return json.loads(p.read_text(encoding="utf-8-sig"))


def discover_c10(explicit:str|None)->Path:
    if explicit:
        p=Path(explicit)
        if p.exists():
            return p
        raise FileNotFoundError(p)

    rel=Path("data/derived/akerfro_ertor_v0a/artkandidat_v0a_operational_fields.parquet")
    candidates=[
        ROOT/rel,
        Path(r"C:\AkerSync-AkerFro")/rel,
        Path(r"C:\AkerSyncRepo")/rel,
        Path(r"C:\AkerSync")/rel,
    ]
    try:
        candidates.extend(sorted(Path("C:/").glob("AkerSync-*"))[0:50])
    except Exception:
        pass

    checked=[]
    for p in candidates:
        if p.is_dir():
            p=p/rel
        checked.append(str(p))
        if p.exists():
            return p
    raise FileNotFoundError(
        "Could not auto-discover frozen C10 operational field product. Checked:\n  "
        + "\n  ".join(checked[:30])
    )


def percentile_score(values:pd.Series,higher_is_better:bool)->pd.Series:
    x=pd.to_numeric(values,errors="coerce")
    ref=x.dropna().to_numpy(float)
    ref.sort()
    out=np.full(len(x),np.nan,dtype=float)
    valid=np.isfinite(x.to_numpy(float))
    xv=x.to_numpy(float)[valid]
    if len(ref):
        left=np.searchsorted(ref,xv,side="left")
        right=np.searchsorted(ref,xv,side="right")
        pct=(left+right)/(2.0*len(ref))
        if not higher_is_better:
            pct=1.0-pct
        out[valid]=100.0*pct
    return pd.Series(out,index=values.index)


def add_recent_positive(df:pd.DataFrame,root:Path,years:list[int])->pd.DataFrame:
    hist,_sources=load_history(root,set(df["field_id"]))
    ids=set(hist.loc[
        hist["clean_conservart"] & hist["history_year"].isin(years),
        "field_id"
    ].astype(str))
    out=df.copy()
    out["recent_conservart_positive"]=out["field_id"].isin(ids)
    return out


def build_scores(df:pd.DataFrame,cfg:dict[str,Any])->pd.DataFrame:
    out=df.copy()
    out["drivable_access_component"]=percentile_score(
        out["nearest_drivable_osm_m"],higher_is_better=False
    )
    out["public_access_component"]=percentile_score(
        out["nearest_statlig_kommunal_nvdb_m"],higher_is_better=False
    )
    rw=cfg["road_access_weights"]
    wd=float(rw["nearest_drivable_osm"])
    wp=float(rw["nearest_statlig_kommunal_nvdb"])
    if abs(wd+wp-1.0)>1e-12:
        raise RuntimeError("road_access_weights must sum to 1")
    out["road_access_score"]=(
        wd*out["drivable_access_component"]+
        wp*out["public_access_component"]
    )

    bw=cfg["balanced_bestmatch_weights"]
    wa=float(bw["artmatch"]); wl=float(bw["area_logistics"]); wr=float(bw["road_access"])
    if abs(wa+wl+wr-1.0)>1e-12:
        raise RuntimeError("balanced_bestmatch_weights must sum to 1")
    out["bestmatch_balanced_score"]=(
        wa*pd.to_numeric(out["artmatch_score"],errors="coerce")
        +wl*pd.to_numeric(out["area_logistics_score"],errors="coerce")
        +wr*pd.to_numeric(out["road_access_score"],errors="coerce")
    )
    return out


def rank_candidates(df:pd.DataFrame,cfg:dict[str,Any])->pd.DataFrame:
    out=df.copy()
    classes=list(cfg["candidate_classes"])
    out["bestmatch_candidate"]=out["artkandidat_class"].isin(classes)
    cand=out[out["bestmatch_candidate"]].copy()

    # Baseline = frozen C10 priority restricted to road-eligible A/B fields.
    q=cand.sort_values(
        ["operational_priority_rank","field_id"],kind="mergesort"
    )
    out["rank_c10_baseline"]=pd.NA
    out.loc[q.index,"rank_c10_baseline"]=np.arange(1,len(q)+1)

    # Access-first keeps A before B, then validated road access, then the
    # existing operational and physical signals.
    class_rank={c:i for i,c in enumerate(classes)}
    cand["_class_rank_d2"]=cand["artkandidat_class"].map(class_rank)
    q=cand.sort_values(
        ["_class_rank_d2","road_access_score","area_logistics_score","artmatch_score","field_id"],
        ascending=[True,False,False,False,True],
        na_position="last",kind="mergesort"
    )
    out["rank_access_first"]=pd.NA
    out.loc[q.index,"rank_access_first"]=np.arange(1,len(q)+1)

    # Balanced is deliberately a candidate policy, not a freeze. A/B class
    # remains the hard first ordering; score only orders within class.
    q=cand.sort_values(
        ["_class_rank_d2","bestmatch_balanced_score","field_id"],
        ascending=[True,False,True],
        na_position="last",kind="mergesort"
    )
    out["rank_bestmatch_balanced"]=pd.NA
    out.loc[q.index,"rank_bestmatch_balanced"]=np.arange(1,len(q)+1)
    return out


def eval_rank(df:pd.DataFrame,rank_col:str,top_ns:list[int])->list[dict[str,Any]]:
    cand=df[df["bestmatch_candidate"] & pd.to_numeric(df[rank_col],errors="coerce").notna()].copy()
    cand[rank_col]=pd.to_numeric(cand[rank_col],errors="coerce")
    total_pos=int(cand["recent_conservart_positive"].sum())
    base=float(cand["recent_conservart_positive"].mean()) if len(cand) else math.nan
    rows=[]
    for n in top_ns:
        q=cand.nsmallest(min(int(n),len(cand)),rank_col)
        hits=int(q["recent_conservart_positive"].sum())
        rate=float(q["recent_conservart_positive"].mean()) if len(q) else math.nan
        rows.append({
            "ranking":rank_col,
            "top_n_requested":int(n),
            "n_fields":int(len(q)),
            "recent_positive_hits":hits,
            "recent_positive_recall":hits/total_pos if total_pos else math.nan,
            "recent_positive_rate":rate,
            "enrichment_vs_candidate_universe":rate/base if base>0 else math.nan,
            "mean_artmatch":float(pd.to_numeric(q["artmatch_score"],errors="coerce").mean()),
            "mean_area_logistics":float(pd.to_numeric(q["area_logistics_score"],errors="coerce").mean()),
            "mean_road_access":float(pd.to_numeric(q["road_access_score"],errors="coerce").mean()),
            "median_nearest_drivable_m":float(pd.to_numeric(q["nearest_drivable_osm_m"],errors="coerce").median()),
            "median_nearest_statlig_kommunal_m":float(pd.to_numeric(q["nearest_statlig_kommunal_nvdb_m"],errors="coerce").median()),
        })
    return rows


def map_geojson(df:pd.DataFrame,rank_col:str,n:int,path:Path)->None:
    q=df[
        df["bestmatch_candidate"] & pd.to_numeric(df[rank_col],errors="coerce").notna()
    ].copy()
    q[rank_col]=pd.to_numeric(q[rank_col],errors="coerce")
    q=q.nsmallest(min(n,len(q)),rank_col).copy()

    x=pd.to_numeric(q["centroid_x"],errors="coerce")
    y=pd.to_numeric(q["centroid_y"],errors="coerce")
    ok=x.notna()&y.notna()
    q=q[ok].copy()
    tr=Transformer.from_crs(3006,4326,always_xy=True)
    lon,lat=tr.transform(
        pd.to_numeric(q["centroid_x"],errors="coerce").to_numpy(float),
        pd.to_numeric(q["centroid_y"],errors="coerce").to_numpy(float)
    )
    q["lon"]=lon; q["lat"]=lat
    keep=[
        "field_id","municipality","field_area_ha","artkandidat_class",
        "artmatch_score","area_logistics_score","road_access_score",
        "bestmatch_balanced_score","rank_c10_baseline","rank_access_first",
        "rank_bestmatch_balanced","nearest_drivable_osm_m",
        "nearest_statlig_kommunal_nvdb_m","network_access_status",
        "recent_conservart_positive","lon","lat"
    ]
    keep=[c for c in keep if c in q.columns]
    g=gpd.GeoDataFrame(
        q[keep].copy(),
        geometry=gpd.points_from_xy(q["lon"],q["lat"]),
        crs=4326
    )
    path.parent.mkdir(parents=True,exist_ok=True)
    g.to_file(path,driver="GeoJSON")


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--config",default=str(DEFAULT_CFG))
    ap.add_argument("--d0",default=str(DEFAULT_D0))
    ap.add_argument("--c10",default=None)
    ap.add_argument("--akerminne-root",default=str(DEFAULT_AKERMINNE))
    ap.add_argument("--out",default=str(DEFAULT_OUT))
    args=ap.parse_args()

    cfg=load_cfg(Path(args.config))
    d0_path=Path(args.d0)
    if not d0_path.exists():
        raise FileNotFoundError(f"D0 missing: {d0_path}")
    c10_path=discover_c10(args.c10)

    print("="*120)
    print("ÅkerFrö × ÅkerAccess D2 - BESTMATCH JOIN + INCREMENTAL LIFT")
    print("="*120)
    print(f"D0:  {d0_path}")
    print(f"C10: {c10_path}")

    d0=pd.read_parquet(d0_path)
    c10=pd.read_parquet(c10_path)
    d0["field_id"]=d0["field_id"].map(norm_id)
    c10["field_id"]=c10["current_field_id"].map(norm_id)
    if d0["field_id"].duplicated().any():
        raise RuntimeError("D0 field_id duplicate")
    if c10["field_id"].duplicated().any():
        raise RuntimeError("C10 current_field_id duplicate")

    need=[
        "current_field_id","artkandidat_class","artmatch_score",
        "area_logistics_score","operational_priority_rank","field_area_ha",
        "rotation_status","predecessor_prior","distance_bjuv_km",
    ]
    missing=[c for c in need if c not in c10.columns]
    if missing:
        raise RuntimeError(f"C10 missing columns: {missing}")

    road_cols=[
        "field_id","municipality","municipality_code","centroid_x","centroid_y",
        "nearest_drivable_osm_m","nearest_statlig_kommunal_nvdb_m",
        "network_access_status","entry_status","path_last_mile_to_anchor_m",
        "nvdb_width_m","nvdb_bearing_class","nvdb_roadkeeper",
    ]
    missing=[c for c in road_cols if c not in d0.columns]
    if missing:
        raise RuntimeError(f"D0 missing columns: {missing}")

    product=c10[need+["field_id"]].merge(
        d0[road_cols],on="field_id",how="inner",validate="one_to_one"
    )
    print(f"Road-eligible joined fields: {len(product):,} / C10 {len(c10):,}")

    years=list(map(int,cfg["evaluation_window"]))
    product=add_recent_positive(product,Path(args.akerminne_root),years)
    product=build_scores(product,cfg)
    product=rank_candidates(product,cfg)

    cand=product[product["bestmatch_candidate"]].copy()
    print(f"A/B candidate universe after road eligibility: {len(cand):,}")
    print(f"Recent clean CONSERVART {years[0]}-{years[-1]} in A/B universe: {int(cand['recent_conservart_positive'].sum()):,}")
    print("Candidate classes:")
    print(cand["artkandidat_class"].value_counts().to_string())

    rankings=[
        "rank_c10_baseline",
        "rank_access_first",
        "rank_bestmatch_balanced",
    ]
    rows=[]
    for rank in rankings:
        rows.extend(eval_rank(product,rank,list(map(int,cfg["top_n"]))))
    ev=pd.DataFrame(rows)

    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    joined_path=out/"akerfro_akeraccess_d2_fields.parquet"
    eval_path=out/"akerfro_akeraccess_d2_incremental_lift.csv"
    top1000_path=out/"bestmatch_balanced_top1000.csv"
    top5000_path=out/"bestmatch_balanced_top5000.csv"
    map_path=out/"bestmatch_balanced_top5000.geojson"

    product.to_parquet(joined_path,index=False)
    ev.to_csv(eval_path,index=False,encoding="utf-8-sig")

    ordered=product[
        product["bestmatch_candidate"] & pd.to_numeric(product["rank_bestmatch_balanced"],errors="coerce").notna()
    ].copy()
    ordered["rank_bestmatch_balanced"]=pd.to_numeric(ordered["rank_bestmatch_balanced"],errors="coerce")
    ordered=ordered.sort_values("rank_bestmatch_balanced",kind="mergesort")
    ordered.head(1000).to_csv(top1000_path,index=False,encoding="utf-8-sig")
    ordered.head(5000).to_csv(top5000_path,index=False,encoding="utf-8-sig")
    map_geojson(product,"rank_bestmatch_balanced",int(cfg["map_top_n"]),map_path)

    report={
        "schema_version":cfg["schema_version"],
        "inputs":{
            "d0":str(d0_path),
            "c10":str(c10_path),
        },
        "joined_road_eligible_fields":int(len(product)),
        "candidate_classes":cfg["candidate_classes"],
        "candidate_fields":int(len(cand)),
        "evaluation_window":years,
        "recent_positive_fields_in_candidates":int(cand["recent_conservart_positive"].sum()),
        "road_access_score":{
            "definition":"equal-weight average of inverse empirical percentile of nearest drivable OSM distance and nearest statlig/kommunal NVDB-roadkeeper distance",
            "weights":cfg["road_access_weights"],
            "status":"candidate policy; not frozen"
        },
        "balanced_bestmatch":{
            "weights":cfg["balanced_bestmatch_weights"],
            "ordering":"candidate class A before B; weighted score orders within class",
            "status":"candidate policy; compare against C10 baseline before freeze"
        },
        "guardrails":[
            "Frozen ÄrtMatch and frozen C10 operational product are read-only inputs.",
            "Road access cannot promote a C/D field into the A/B candidate universe.",
            "statlig/kommunal roadkeeper is a logistics proxy, not legal allmän-väg classification.",
            "D2 historical enrichment is product diagnostics, not causal evidence.",
            "No D2 weighting is frozen until incremental lift and map sanity checks are reviewed."
        ],
        "outputs":{
            "joined_fields":str(joined_path),
            "incremental_lift":str(eval_path),
            "top1000":str(top1000_path),
            "top5000":str(top5000_path),
            "map_geojson":str(map_path),
        }
    }
    rp=out/"akerfro_akeraccess_d2_report.json"
    rp.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding="utf-8")

    print("\nINCREMENTAL LIFT · recent clean CONSERVART")
    for n in list(map(int,cfg["top_n"])):
        q=ev[ev["top_n_requested"].eq(n)]
        print("-"*120)
        print(f"TOP {n}")
        for r in q.itertuples(index=False):
            print(
                f"  {r.ranking:28s} hits={r.recent_positive_hits:4d} "
                f"recall={100*r.recent_positive_recall:5.1f}% "
                f"enrich={r.enrichment_vs_candidate_universe:5.2f}x "
                f"road={r.mean_road_access:5.1f} "
                f"d_drive_med={r.median_nearest_drivable_m:6.1f}m "
                f"d_pub_med={r.median_nearest_statlig_kommunal_m:6.1f}m"
            )

    print("\nTOP 20 BALANCED BESTMATCH")
    show=[
        "rank_bestmatch_balanced","field_id","municipality","artkandidat_class",
        "artmatch_score","area_logistics_score","road_access_score",
        "bestmatch_balanced_score","field_area_ha",
        "nearest_drivable_osm_m","nearest_statlig_kommunal_nvdb_m",
    ]
    print(ordered.head(20)[show].to_string(index=False,formatters={
        "artmatch_score":lambda v:f"{v:.1f}",
        "area_logistics_score":lambda v:f"{v:.1f}",
        "road_access_score":lambda v:f"{v:.1f}",
        "bestmatch_balanced_score":lambda v:f"{v:.1f}",
        "field_area_ha":lambda v:f"{v:.1f}",
        "nearest_drivable_osm_m":lambda v:f"{v:.1f}",
        "nearest_statlig_kommunal_nvdb_m":lambda v:f"{v:.1f}",
    }))

    print(f"\nJoined: {joined_path}")
    print(f"Lift:   {eval_path}")
    print(f"Map:    {map_path}")
    print(f"Report: {rp}")
    print("="*120)
    print("ÅkerFrö × ÅkerAccess D2: PASS")
    print("="*120)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
