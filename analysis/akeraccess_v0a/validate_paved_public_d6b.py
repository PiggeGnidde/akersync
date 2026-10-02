#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D6b — validate paved public-road proximity using frozen D1 near-twin matches.

No rematching is performed. This compares:
- old administrative public-roadkeeper distance
- new paved + public-roadkeeper distance

It also writes a candidate RoadAccess v0b feature:
  0.5 * inverse percentile(nearest drivable OSM)
+ 0.5 * inverse percentile(nearest paved statlig/kommunal NVDB)

No existing D0/D5/web score is overwritten.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_D0=ROOT/"work"/"akeraccess_v0a"/"skane_d0"/"skane_akeraccess_road_features_d0.parquet"
DEFAULT_D6A=ROOT/"work"/"akeraccess_v0a"/"surface_d6a"/"skane_paved_public_road_distance_d6a.parquet"
DEFAULT_D1_MATCHES=ROOT/"work"/"akeraccess_v0a"/"skane_d1"/"skane_d1_matches.parquet"
DEFAULT_D5=ROOT/"work"/"akeraccess_v0a"/"bestmatch_d5"/"bestmatch_d5_fields.parquet"
DEFAULT_OUT=ROOT/"work"/"akeraccess_v0a"/"surface_d6b"
THRESHOLDS=[50,100,250,500,1000]


def percentile_score(values:pd.Series)->pd.Series:
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


def bootstrap_ci(x,reps=10000,seed=20261002):
    a=np.asarray(x,dtype=float)
    a=a[np.isfinite(a)]
    if len(a)==0:
        return math.nan,math.nan,math.nan
    mean=float(a.mean())
    if len(a)==1:
        return mean,math.nan,math.nan
    rng=np.random.default_rng(seed)
    vals=[]
    left=reps
    while left:
        n=min(left,500)
        ix=rng.integers(0,len(a),size=(n,len(a)))
        vals.append(a[ix].mean(axis=1))
        left-=n
    b=np.concatenate(vals)
    return mean,float(np.quantile(b,.025)),float(np.quantile(b,.975))


def summarize_matches(matches,feat):
    f=feat.set_index("field_id")
    rows=[]
    for li,label in enumerate(matches["match_label"].drop_duplicates().tolist()):
        m=matches[matches["match_label"].eq(label)].copy()
        set_rows=[]
        for pid,g in m.groupby("positive_field_id",sort=False):
            pid=str(pid)
            if pid not in f.index:
                continue
            pr=f.loc[pid]
            ctr=f.reindex(g["control_field_id"].astype(str))
            rec={"positive_field_id":pid}
            for metric in [
                "nearest_statlig_kommunal_nvdb_m",
                "nearest_belagd_statlig_kommunal_nvdb_m",
            ]:
                pv=pd.to_numeric(pd.Series([pr.get(metric)]),errors="coerce").iloc[0]
                cv=pd.to_numeric(ctr[metric],errors="coerce").dropna()
                for t in THRESHOLDS:
                    pbin=float(pv<=t) if pd.notna(pv) else math.nan
                    cbin=float((cv<=t).mean()) if len(cv) else math.nan
                    rec[f"{metric}_within_{t}_positive"]=pbin
                    rec[f"{metric}_within_{t}_control_mean"]=cbin
                    rec[f"{metric}_within_{t}_diff"]=(
                        pbin-cbin if math.isfinite(pbin) and math.isfinite(cbin) else math.nan
                    )
            set_rows.append(rec)
        sets=pd.DataFrame(set_rows)
        for metric in [
            "nearest_statlig_kommunal_nvdb_m",
            "nearest_belagd_statlig_kommunal_nvdb_m",
        ]:
            for t in THRESHOLDS:
                col=f"{metric}_within_{t}"
                d=pd.to_numeric(sets[col+"_diff"],errors="coerce").to_numpy(float)
                mean,lo,hi=bootstrap_ci(d,10000,20261002+li*100+t)
                rows.append({
                    "match_label":label,
                    "metric":col,
                    "kind":"binary",
                    "valid_positive_sets":int(np.isfinite(d).sum()),
                    "positive_mean":float(pd.to_numeric(sets[col+"_positive"],errors="coerce").mean()),
                    "matched_control_mean":float(pd.to_numeric(sets[col+"_control_mean"],errors="coerce").mean()),
                    "paired_difference":mean,
                    "bootstrap95_lo":lo,
                    "bootstrap95_hi":hi,
                })
    return pd.DataFrame(rows)


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--d0",default=str(DEFAULT_D0))
    ap.add_argument("--d6a",default=str(DEFAULT_D6A))
    ap.add_argument("--d1-matches",default=str(DEFAULT_D1_MATCHES))
    ap.add_argument("--d5",default=str(DEFAULT_D5))
    ap.add_argument("--out",default=str(DEFAULT_OUT))
    args=ap.parse_args()

    paths=[Path(args.d0),Path(args.d6a),Path(args.d1_matches),Path(args.d5)]
    for p in paths:
        if not p.exists():
            raise FileNotFoundError(p)

    d0=pd.read_parquet(args.d0)
    d6a=pd.read_parquet(args.d6a)
    matches=pd.read_parquet(args.d1_matches)
    d5=pd.read_parquet(args.d5)
    for df in [d0,d6a,d5]:
        df["field_id"]=df["field_id"].astype(str)

    feat=d0[[
        "field_id","nearest_drivable_osm_m","nearest_statlig_kommunal_nvdb_m"
    ]].merge(d6a,on="field_id",how="left",validate="one_to_one")

    feat["drivable_access_component_v0b"]=percentile_score(feat["nearest_drivable_osm_m"])
    feat["paved_public_access_component_v0b"]=percentile_score(
        feat["nearest_belagd_statlig_kommunal_nvdb_m"]
    )
    feat["road_access_score_paved"]=(
        0.5*feat["drivable_access_component_v0b"]+
        0.5*feat["paved_public_access_component_v0b"]
    )

    summary=summarize_matches(matches,feat)

    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    summary_path=out/"d6b_paved_public_neartwin_summary.csv"
    feat_path=out/"d6b_paved_public_features.parquet"
    aug_path=out/"bestmatch_d6b_fields.parquet"

    summary.to_csv(summary_path,index=False,encoding="utf-8-sig")
    feat.to_parquet(feat_path,index=False)

    aug=d5.merge(
        feat[[
            "field_id",
            "nearest_belagd_statlig_kommunal_nvdb_m",
            "road_access_score_paved"
        ]],
        on="field_id",how="left",validate="one_to_one"
    )
    aug.to_parquet(aug_path,index=False)

    primary="skane_excluding_sjobo__recent_2023_2025__strict_never_pea"
    q=summary[summary["match_label"].eq(primary)]

    print("="*118)
    print("ÅkerAccess D6b - PAVED PUBLIC-ROAD VALIDATION")
    print("="*118)
    print("PRIMARY holdout: Skåne excluding Sjöbo · recent 2023-2025 · strict-never-pea")
    for t in [50,100,250,500]:
        for metric,label in [
            (f"nearest_statlig_kommunal_nvdb_m_within_{t}","old public-roadkeeper"),
            (f"nearest_belagd_statlig_kommunal_nvdb_m_within_{t}","paved public-roadkeeper"),
        ]:
            r=q[q["metric"].eq(metric)]
            if r.empty:
                continue
            z=r.iloc[0]
            print(
                f"{t:4d} m · {label:24s} "
                f"pea={100*z.positive_mean:5.1f}% "
                f"ctrl={100*z.matched_control_mean:5.1f}% "
                f"diff={100*z.paired_difference:+5.1f}pp "
                f"boot95=[{100*z.bootstrap95_lo:+5.1f},{100*z.bootstrap95_hi:+5.1f}]"
            )

    print(f"\nSummary: {summary_path}")
    print(f"Candidate feature table: {feat_path}")
    print(f"Augmented D5: {aug_path}")
    print("="*118)
    print("ÅkerAccess D6b: PASS")
    print("="*118)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
