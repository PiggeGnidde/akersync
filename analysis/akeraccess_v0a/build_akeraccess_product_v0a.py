#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the frozen ÅkerAccess v0a product table from D0 only.

The product score is intentionally simple and independent of ÅkerFrö:
  50% inverse empirical percentile of distance to nearest mapped drivable OSM way
+ 50% inverse empirical percentile of distance to nearest statlig/kommunal
  NVDB roadkeeper geometry.

This is a screening/ranking score, not a probability of physical/legal access.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_POLICY=ROOT/"config"/"akeraccess_v0a_freeze.json"
DEFAULT_D0=ROOT/"work"/"akeraccess_v0a"/"skane_d0"/"skane_akeraccess_road_features_d0.parquet"
DEFAULT_OUT=ROOT/"data"/"derived"/"akeraccess_v0a"


def load_json(path:Path)->dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def inverse_percentile(values:pd.Series)->pd.Series:
    x=pd.to_numeric(values,errors="coerce")
    arr=x.to_numpy(float)
    ref=np.sort(arr[np.isfinite(arr)])
    out=np.full(len(x),np.nan,dtype=float)
    valid=np.isfinite(arr)
    if len(ref):
        left=np.searchsorted(ref,arr[valid],side="left")
        right=np.searchsorted(ref,arr[valid],side="right")
        pct=(left+right)/(2.0*len(ref))
        out[valid]=100.0*(1.0-pct)
    return pd.Series(out,index=values.index)


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--policy",default=str(DEFAULT_POLICY))
    ap.add_argument("--d0",default=str(DEFAULT_D0))
    ap.add_argument("--out",default=str(DEFAULT_OUT))
    args=ap.parse_args()

    policy=load_json(Path(args.policy))
    d0_path=Path(args.d0)
    if not d0_path.exists():
        raise FileNotFoundError(f"Run ÅkerAccess D0 first: {d0_path}")

    d=pd.read_parquet(d0_path).copy()
    if len(d)!=67073:
        raise RuntimeError(f"Population anchor failed: {len(d):,} != 67,073")
    if d["field_id"].astype(str).duplicated().any():
        raise RuntimeError("field_id is not unique")

    d["field_id"]=d["field_id"].astype(str)
    d["drivable_access_component_v0a"]=inverse_percentile(d["nearest_drivable_osm_m"])
    d["public_roadkeeper_access_component_v0a"]=inverse_percentile(
        d["nearest_statlig_kommunal_nvdb_m"]
    )

    w=policy["score_weights"]
    wd=float(w["nearest_drivable_osm"])
    wp=float(w["nearest_statlig_kommunal_roadkeeper"])
    if abs(wd+wp-1.0)>1e-12:
        raise RuntimeError("ÅkerAccess score weights must sum to 1")

    d["akeraccess_score_v0a"]=(
        wd*d["drivable_access_component_v0a"]
        +wp*d["public_roadkeeper_access_component_v0a"]
    )

    ranked=d[pd.to_numeric(d["akeraccess_score_v0a"],errors="coerce").notna()].copy()
    ranked=ranked.sort_values(
        ["akeraccess_score_v0a","field_id"],
        ascending=[False,True],
        kind="mergesort"
    )
    d["akeraccess_rank_v0a"]=pd.NA
    d.loc[ranked.index,"akeraccess_rank_v0a"]=np.arange(1,len(ranked)+1)
    d["akeraccess_rank_v0a"]=d["akeraccess_rank_v0a"].astype("Int64")

    # Product evidence labels. Missing OSM evidence remains UNKNOWN/CHECK, never FAIL.
    d["akeraccess_evidence_v0a"]=np.where(
        d["network_access_status"].eq("CONNECTED_TO_ROAD_NETWORK"),
        "MAPPED_CONNECTED",
        np.where(
            pd.to_numeric(d["nearest_drivable_osm_m"],errors="coerce").le(50),
            "MAPPED_ROAD_NEAR_FIELD",
            "CHECK_MAPPING_OR_ACCESS"
        )
    )

    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    fp=out/"akeraccess_v0a_fields.parquet"
    sp=out/"akeraccess_v0a_summary.json"
    d.to_parquet(fp,index=False)

    score=pd.to_numeric(d["akeraccess_score_v0a"],errors="coerce")
    summary={
        "schema_version":"akeraccess-v0a-product-v1",
        "freeze_name":policy["freeze_name"],
        "population_fields":int(len(d)),
        "scored_fields":int(score.notna().sum()),
        "score_weights":policy["score_weights"],
        "score_semantics":policy["score_semantics"],
        "product_labels":policy["product_labels"],
        "estimated_entry_semantics":policy["estimated_entry_semantics"],
        "exclude_from_score":policy["exclude_from_score"],
        "score_quantiles":{
            "p10":float(score.quantile(.10)),
            "p25":float(score.quantile(.25)),
            "p50":float(score.quantile(.50)),
            "p75":float(score.quantile(.75)),
            "p90":float(score.quantile(.90)),
        },
        "evidence_counts":{str(k):int(v) for k,v in d["akeraccess_evidence_v0a"].value_counts().items()},
        "source_d0":str(d0_path),
        "guardrails":[
            "ÅkerAccess v0a is a screening/ranking score, not a probability or guarantee.",
            "Nearest drivable OSM includes mapped track/service roads; it does not certify truck suitability.",
            "Statlig/kommunal refers to NVDB roadkeeper responsibility, not asphalt, legal allmän väg or truck standard.",
            "Selected field entry is machine-estimated from mapped geometry and is not field-verified.",
            "NO/weak mapped evidence means CHECK/UNKNOWN, not physical inaccessibility.",
            "NVDB Slitlager is excluded after visual QA found a paved road classified as grus near field 62263103013|20C.",
            "Width, bearing class, functional road class and height-obstacle attributes remain diagnostics only in v0a."
        ],
        "output":str(fp)
    }
    sp.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    print("="*104)
    print("ÅkerAccess v0a PRODUCT BUILD")
    print("="*104)
    print(f"Fields: {len(d):,}")
    print(f"Scored: {int(score.notna().sum()):,}")
    print(f"Score p10/p50/p90: {score.quantile(.10):.2f}/{score.quantile(.50):.2f}/{score.quantile(.90):.2f}")
    print(f"Product: {fp}")
    print(f"Summary: {sp}")
    print("="*104)
    print("ÅkerAccess v0a PRODUCT BUILD: PASS")
    print("="*104)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
