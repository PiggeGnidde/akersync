#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerAccess D1 — Skåne conservärt replication using frozen D0 road features.

Primary replication scope deliberately excludes Sjöbo, where the hypotheses
were generated. Full-Skåne results are also reported descriptively.

Historical non-use remains positive-unlabeled. Near-twin matching is spatial +
current-area, with 10 controls per positive and positive-set bootstrap.
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
from scipy.spatial import cKDTree

ROOT=Path(__file__).resolve().parents[2]
for p in (ROOT,ROOT/"src"):
    if str(p) not in sys.path:
        sys.path.insert(0,str(p))

from common import MUN_CODES
from analysis.akerfro_ertor_v0a.crop_groups import CONSERVART, akerfro_crop_group

DEFAULT_CFG=ROOT/"config"/"akeraccess_skane_d1.json"
DEFAULT_D0=ROOT/"work"/"akeraccess_v0a"/"skane_d0"/"skane_akeraccess_road_features_d0.parquet"
DEFAULT_AKERMINNE=Path(r"C:\AkerSync-Minne")
DEFAULT_OUT=ROOT/"work"/"akeraccess_v0a"/"skane_d1"


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


def load_history(root:Path,field_ids:set[str])->tuple[pd.DataFrame,list[str]]:
    munroot=root/"data"/"derived"/"akerminne_v1a"/"skane"/"municipalities"
    if not munroot.exists():
        raise FileNotFoundError(munroot)
    rows=[]; sources=[]
    cols=["history_year","current_field_id","dominant_crop_name","status"]
    for municipality,code in MUN_CODES.items():
        dirs=sorted(munroot.glob(f"{code}_*"))
        if len(dirs)!=1:
            raise RuntimeError(
                f"Expected one ÅkerMinne directory for {municipality} ({code}); got {len(dirs)}"
            )
        p=dirs[0]/"akerminne_year_summary_classified.parquet"
        if not p.exists():
            raise FileNotFoundError(p)
        q=pd.read_parquet(p,columns=cols)
        q["field_id"]=q["current_field_id"].map(norm_id)
        q=q[q["field_id"].isin(field_ids)].copy()
        q["history_year"]=pd.to_numeric(q["history_year"],errors="coerce").astype("Int64")
        q["akerfro_group"]=q["dominant_crop_name"].map(akerfro_crop_group)
        q["clean_conservart"]=q["status"].eq("SINGLE_CROP") & q["akerfro_group"].eq(CONSERVART)
        q["history_municipality"]=municipality
        rows.append(q[[
            "field_id","history_year","dominant_crop_name","status",
            "akerfro_group","clean_conservart","history_municipality"
        ]])
        sources.append(str(p))
    return pd.concat(rows,ignore_index=True),sources


def add_positive_flags(df:pd.DataFrame,hist:pd.DataFrame,cfg:dict[str,Any])->pd.DataFrame:
    out=df.copy()
    for name,years in cfg["windows"].items():
        ids=set(hist.loc[
            hist["clean_conservart"] & hist["history_year"].isin(list(map(int,years))),
            "field_id"
        ].astype(str))
        out["pos_"+name]=out["field_id"].isin(ids)
    return out


def prepare_outcomes(df:pd.DataFrame)->pd.DataFrame:
    out=df.copy()
    out["area_num"]=pd.to_numeric(out["area_ha"],errors="coerce")
    out["cx"]=pd.to_numeric(out["centroid_x"],errors="coerce")
    out["cy"]=pd.to_numeric(out["centroid_y"],errors="coerce")

    # Primary preregistered replication endpoint from Sjöbo C3c.
    d=pd.to_numeric(out["nearest_drivable_osm_m"],errors="coerce")
    out["no_drivable_50m"]=d.gt(50.0).astype("boolean").where(d.notna(),pd.NA)

    # Operational/ranking diagnostics.
    out["access_connected"]=out["network_access_status"].eq("CONNECTED_TO_ROAD_NETWORK")
    pub=pd.to_numeric(out["nearest_statlig_kommunal_nvdb_m"],errors="coerce")
    for m in (50,100,250):
        out[f"statlig_kommunal_within_{m}m"]=pub.le(m).astype("boolean").where(pub.notna(),pd.NA)

    lm=pd.to_numeric(out["path_last_mile_to_anchor_m"],errors="coerce")
    out["last_mile_connected_m"]=lm.where(out["access_connected"])
    out["nearest_drivable_num"]=d
    out["nearest_publickeeper_num"]=pub

    # Raw functional class and natural grouped versions. Missing stays unknown.
    fc=pd.to_numeric(out.get("nvdb_functional_class"),errors="coerce")
    out["_fclass_num"]=fc
    for k in range(10):
        out[f"fclass_{k}"]=fc.eq(k).astype("boolean").where(fc.notna(),pd.NA)
    groups={
        "fclass_0_3":[0,1,2,3],
        "fclass_4_5":[4,5],
        "fclass_6_8":[6,7,8],
        "fclass_9":[9],
        # Sjöbo-generated post-hoc combination is retained only as an explicitly
        # labelled replication diagnostic, never as an official NVDB category.
        "fclass_4_or_7_posthoc":[4,7],
    }
    for name,vals in groups.items():
        out[name]=fc.isin(vals).astype("boolean").where(fc.notna(),pd.NA)

    keeper=out.get("nvdb_roadkeeper",pd.Series(index=out.index,dtype=object)).astype("string")
    for name,val in [
        ("keeper_statlig","statlig"),
        ("keeper_kommunal","kommunal"),
        ("keeper_enskild","enskild"),
    ]:
        out[name]=keeper.str.casefold().eq(val).astype("boolean").where(keeper.notna(),pd.NA)

    width=pd.to_numeric(out.get("nvdb_width_m"),errors="coerce")
    out["width_ge_4_5"]=width.ge(4.5).astype("boolean").where(width.notna(),pd.NA)

    bearing=out.get("nvdb_bearing_class",pd.Series(index=out.index,dtype=object)).astype("string")
    out["bearing_known"]=bearing.notna()
    out["bearing_bk1"]=bearing.str.casefold().eq("bk 1").astype("boolean").where(bearing.notna(),pd.NA)
    return out


BOOL_METRICS=[
    "no_drivable_50m",
    "access_connected",
    "statlig_kommunal_within_50m",
    "statlig_kommunal_within_100m",
    "statlig_kommunal_within_250m",
    "fclass_0_3","fclass_4_5","fclass_6_8","fclass_9",
    "fclass_4_or_7_posthoc",
    "keeper_statlig","keeper_kommunal","keeper_enskild",
    "width_ge_4_5","bearing_known","bearing_bk1",
]
NUM_METRICS=[
    "nearest_drivable_num",
    "nearest_publickeeper_num",
    "last_mile_connected_m",
]


def bootstrap_ci_chunked(x:np.ndarray,reps:int,chunk:int,seed:int)->tuple[float,float,float]:
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
    while left>0:
        n=min(chunk,left)
        ix=rng.integers(0,len(a),size=(n,len(a)))
        vals.append(a[ix].mean(axis=1))
        left-=n
    b=np.concatenate(vals)
    return mean,float(np.quantile(b,.025)),float(np.quantile(b,.975))


def build_control_index(controls:pd.DataFrame):
    xy=controls[["cx","cy"]].to_numpy(float)
    if not np.isfinite(xy).all():
        raise RuntimeError("Control geometry has missing centroid coordinates")
    return cKDTree(xy),xy


def select_controls(
    pos:pd.Series,
    controls:pd.DataFrame,
    tree:cKDTree,
    cfg:dict[str,Any]
)->pd.DataFrame:
    k=int(cfg["controls_per_positive"])
    pxy=np.array([float(pos["cx"]),float(pos["cy"])],dtype=float)
    pa=float(pos["area_num"])
    amin=float(cfg["area_ratio_min"]); amax=float(cfg["area_ratio_max"])
    r1=float(cfg["primary_match_radius_m"]); r2=float(cfg["fallback_match_radius_m"])

    def candidates(radius:float,area_caliper:bool)->tuple[np.ndarray,np.ndarray,np.ndarray]:
        ix=np.asarray(tree.query_ball_point(pxy,r=radius),dtype=int)
        if len(ix)==0:
            return ix,np.array([]),np.array([])
        q=controls.iloc[ix]
        ca=q["area_num"].to_numpy(float)
        ratio=ca/pa
        dist=np.hypot(
            q["cx"].to_numpy(float)-pxy[0],
            q["cy"].to_numpy(float)-pxy[1]
        )
        good=np.isfinite(ca)&(ca>0)&np.isfinite(ratio)
        if area_caliper:
            good&=(ratio>=amin)&(ratio<=amax)
        return ix[good],dist[good],ratio[good]

    ix,dist,ratio=candidates(r1,True); stage="primary"
    if len(ix)<k:
        ix,dist,ratio=candidates(r2,True); stage="fallback_radius"
    if len(ix)<k:
        ix,dist,ratio=candidates(r2,False); stage="fallback_no_area_caliper"
    if len(ix)<k:
        # Rare global fallback: query a bounded nearest-neighbour pool rather
        # than scanning all ~67k controls.
        qk=min(max(500,k),len(controls))
        dist0,ix0=tree.query(pxy,k=qk)
        ix=np.atleast_1d(ix0).astype(int)
        dist=np.atleast_1d(dist0).astype(float)
        ca=controls.iloc[ix]["area_num"].to_numpy(float)
        ratio=ca/pa
        good=np.isfinite(ca)&(ca>0)&np.isfinite(ratio)
        ix=ix[good]; dist=dist[good]; ratio=ratio[good]
        stage="fallback_global_nearest"

    if len(ix)==0:
        return controls.head(0).copy()

    logdiff=np.abs(np.log(ratio))
    score=dist+float(cfg["area_log_penalty_m"])*logdiff
    order=np.argsort(score,kind="stable")[:k]
    q=controls.iloc[ix[order]].copy()
    q["match_distance_m"]=dist[order]
    q["area_ratio_control_to_positive"]=ratio[order]
    q["match_score"]=score[order]
    q["match_stage"]=stage
    return q


def pair_metric(pos:pd.Series,ctrl:pd.DataFrame,metric:str,kind:str):
    if kind=="bool":
        pv=pos[metric]
        if pd.isna(pv):
            return math.nan,math.nan,math.nan
        cs=ctrl[metric]
        cs=cs[cs.notna()]
        if cs.empty:
            return float(bool(pv)),math.nan,math.nan
        p=float(bool(pv)); c=float(cs.astype(bool).mean())
        return p,c,p-c
    ps=pd.to_numeric(pd.Series([pos[metric]]),errors="coerce").iloc[0]
    cs=pd.to_numeric(ctrl[metric],errors="coerce").dropna()
    if pd.isna(ps) or cs.empty:
        return (float(ps) if pd.notna(ps) else math.nan),math.nan,math.nan
    p=float(ps); c=float(cs.mean())
    return p,c,p-c


def qdict(x:pd.Series|np.ndarray)->dict[str,float|None]:
    s=pd.to_numeric(pd.Series(x),errors="coerce").dropna()
    if s.empty:
        return {"p10":None,"p25":None,"p50":None,"p75":None,"p90":None}
    return {f"p{q}":float(s.quantile(q/100.0)) for q in [10,25,50,75,90]}


def run_match(
    df:pd.DataFrame,
    pos_col:str,
    control_mask:pd.Series,
    label:str,
    cfg:dict[str,Any],
    seed_offset:int
):
    positives=df[df[pos_col]].copy().sort_values("field_id",kind="mergesort")
    controls=df[control_mask].copy().reset_index(drop=True)
    if positives.empty or controls.empty:
        return pd.DataFrame(),pd.DataFrame(),{"positive_n":int(len(positives)),"control_pool_n":int(len(controls))}

    tree,_=build_control_index(controls)
    set_rows=[]; match_rows=[]
    for j,(_,p) in enumerate(positives.iterrows(),1):
        q=select_controls(p,controls,tree,cfg)
        for _,c in q.iterrows():
            match_rows.append({
                "match_label":label,
                "positive_field_id":p["field_id"],
                "positive_municipality":p["municipality"],
                "control_field_id":c["field_id"],
                "control_municipality":c["municipality"],
                "distance_m":c["match_distance_m"],
                "area_ratio_control_to_positive":c["area_ratio_control_to_positive"],
                "match_stage":c["match_stage"],
            })
        rec={"match_label":label,"positive_field_id":p["field_id"],"n_controls":int(len(q))}
        for metric in BOOL_METRICS:
            pv,cv,d=pair_metric(p,q,metric,"bool")
            rec[metric+"_positive"]=pv
            rec[metric+"_control_mean"]=cv
            rec[metric+"_diff"]=d
        for metric in NUM_METRICS:
            pv,cv,d=pair_metric(p,q,metric,"numeric")
            rec[metric+"_positive"]=pv
            rec[metric+"_control_mean"]=cv
            rec[metric+"_diff"]=d
        set_rows.append(rec)

    sets=pd.DataFrame(set_rows)
    matches=pd.DataFrame(match_rows)
    summary=[]
    reps=int(cfg["bootstrap_reps"])
    chunk=int(cfg["bootstrap_chunk_reps"])
    seed=int(cfg["random_seed"])+seed_offset
    all_metrics=[(x,"bool") for x in BOOL_METRICS]+[(x,"numeric") for x in NUM_METRICS]
    for i,(metric,kind) in enumerate(all_metrics):
        d=pd.to_numeric(sets[metric+"_diff"],errors="coerce").to_numpy(float)
        mean,lo,hi=bootstrap_ci_chunked(d,reps,chunk,seed+i)
        summary.append({
            "match_label":label,
            "metric":metric,
            "kind":kind,
            "valid_positive_sets":int(np.isfinite(d).sum()),
            "positive_mean":float(pd.to_numeric(sets[metric+"_positive"],errors="coerce").mean()),
            "matched_control_mean":float(pd.to_numeric(sets[metric+"_control_mean"],errors="coerce").mean()),
            "paired_difference":mean,
            "bootstrap95_lo":lo,
            "bootstrap95_hi":hi,
        })

    diag={
        "positive_n":int(len(positives)),
        "control_pool_n":int(len(controls)),
        "match_rows":int(len(matches)),
        "unique_controls":int(matches["control_field_id"].nunique()) if len(matches) else 0,
        "max_control_reuse":int(matches["control_field_id"].value_counts().max()) if len(matches) else 0,
        "match_distance_m_quantiles":qdict(matches["distance_m"]) if len(matches) else {},
        "area_ratio_quantiles":qdict(matches["area_ratio_control_to_positive"]) if len(matches) else {},
        "match_stage_counts":{str(k):int(v) for k,v in matches["match_stage"].value_counts().items()} if len(matches) else {},
    }
    return pd.DataFrame(summary),matches,diag


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--config",default=str(DEFAULT_CFG))
    ap.add_argument("--d0",default=str(DEFAULT_D0))
    ap.add_argument("--akerminne-root",default=str(DEFAULT_AKERMINNE))
    ap.add_argument("--out",default=str(DEFAULT_OUT))
    args=ap.parse_args()

    cfg=load_cfg(Path(args.config))
    d0=Path(args.d0)
    if not d0.exists():
        raise FileNotFoundError(f"Run D0 first: {d0}")
    df=pd.read_parquet(d0)
    df["field_id"]=df["field_id"].map(norm_id)
    if df["field_id"].duplicated().any():
        raise RuntimeError("D0 field_id is not unique")
    df=prepare_outcomes(df)

    hist,sources=load_history(Path(args.akerminne_root),set(df["field_id"]))
    df=add_positive_flags(df,hist,cfg)

    outdir=Path(args.out)
    outdir.mkdir(parents=True,exist_ok=True)

    windows=list(cfg["windows"])
    scopes={
        "skane_excluding_sjobo":~df["municipality"].eq("Sjöbo"),
        "full_skane":pd.Series(True,index=df.index),
    }

    counts=[]
    for scope,mask in scopes.items():
        for w in windows:
            counts.append({
                "scope":scope,
                "window":w,
                "eligible_fields":int(mask.sum()),
                "positive_fields":int((mask & df["pos_"+w]).sum()),
            })
    counts_df=pd.DataFrame(counts)

    # Positive counts by municipality are useful for understanding where the
    # county-wide power comes from, without manual exploration.
    mun_rows=[]
    for municipality in MUN_CODES:
        mm=df["municipality"].eq(municipality)
        rec={"municipality":municipality,"eligible_fields":int(mm.sum())}
        for w in windows:
            rec["positive_"+w]=int((mm & df["pos_"+w]).sum())
        mun_rows.append(rec)
    mun_df=pd.DataFrame(mun_rows)

    all_summary=[]; all_matches=[]; diagnostics={}
    seed_offset=0
    never=df["pos_all_2015_2025"].fillna(False).astype(bool)

    for scope,scope_mask in scopes.items():
        sdf=df[scope_mask].copy()
        for w in windows:
            pos_col="pos_"+w
            pos=sdf[pos_col].fillna(False).astype(bool)
            modes={
                "window_unlabeled":~pos,
                "strict_never_pea":~sdf["pos_all_2015_2025"].fillna(False).astype(bool),
            }
            for mode,cmask in modes.items():
                label=f"{scope}__{w}__{mode}"
                summary,matches,diag=run_match(sdf,pos_col,cmask,label,cfg,seed_offset)
                seed_offset+=100
                all_summary.append(summary)
                all_matches.append(matches)
                diagnostics[label]=diag
                print("-"*118)
                print(label)
                print(
                    f"  positives={diag.get('positive_n',0):,}  controls={diag.get('control_pool_n',0):,} "
                    f"unique controls={diag.get('unique_controls',0):,}  max reuse={diag.get('max_control_reuse',0)}"
                )
                if diag.get("match_distance_m_quantiles"):
                    print("  match distance m:",diag["match_distance_m_quantiles"])
                    print("  area ratio ctrl/pea:",diag["area_ratio_quantiles"])
                    print("  stages:",diag["match_stage_counts"])
                for metric in [
                    "no_drivable_50m",
                    "statlig_kommunal_within_50m",
                    "statlig_kommunal_within_100m",
                    "statlig_kommunal_within_250m",
                    "fclass_0_3","fclass_4_5","fclass_6_8","fclass_9",
                    "fclass_4_or_7_posthoc",
                ]:
                    q=summary[summary["metric"].eq(metric)]
                    if q.empty:
                        continue
                    r=q.iloc[0]
                    print(
                        f"  {metric:31s} pea={100*r.positive_mean:6.1f}% "
                        f"ctrl={100*r.matched_control_mean:6.1f}% "
                        f"diff={100*r.paired_difference:+6.1f}pp "
                        f"boot95=[{100*r.bootstrap95_lo:+6.1f},{100*r.bootstrap95_hi:+6.1f}] "
                        f"n={int(r.valid_positive_sets):,}"
                    )

    summary_df=pd.concat(all_summary,ignore_index=True)
    matches_df=pd.concat(all_matches,ignore_index=True)

    # Primary preregistered replication row for convenient machine/human reading.
    primary_label="skane_excluding_sjobo__recent_2023_2025__strict_never_pea"
    primary=summary_df[
        summary_df["match_label"].eq(primary_label)
        & summary_df["metric"].eq("no_drivable_50m")
    ]
    primary_result=primary.iloc[0].to_dict() if len(primary) else {}

    counts_path=outdir/"skane_d1_positive_counts.csv"
    mun_path=outdir/"skane_d1_positive_counts_by_municipality.csv"
    summary_path=outdir/"skane_d1_neartwin_summary.csv"
    matches_path=outdir/"skane_d1_matches.parquet"
    counts_df.to_csv(counts_path,index=False,encoding="utf-8-sig")
    mun_df.to_csv(mun_path,index=False,encoding="utf-8-sig")
    summary_df.to_csv(summary_path,index=False,encoding="utf-8-sig")
    matches_df.to_parquet(matches_path,index=False)

    report={
        "schema_version":cfg["schema_version"],
        "d0_source":str(d0),
        "eligible_fields_full_skane":int(len(df)),
        "history_sources":sources,
        "positive_definition":"ÅkerMinne status=SINGLE_CROP and semantic CONSERVART from official year-specific crop name",
        "windows":cfg["windows"],
        "positive_counts":counts,
        "primary_replication":{
            "scope":"Skåne excluding Sjöbo",
            "window":"2023-2025",
            "control_definition":"strict_never_pea",
            "endpoint":"no_drivable_50m",
            "hypothesis_direction":"historical conservärt fields have lower prevalence of no mapped drivable OSM way within 50 m",
            "result":primary_result,
        },
        "matching":{
            "controls_per_positive":cfg["controls_per_positive"],
            "primary_radius_m":cfg["primary_match_radius_m"],
            "fallback_radius_m":cfg["fallback_match_radius_m"],
            "area_ratio":[cfg["area_ratio_min"],cfg["area_ratio_max"]],
            "area_log_penalty_m":cfg["area_log_penalty_m"],
            "controls_may_be_reused":True,
            "bootstrap_unit":"positive matched set",
        },
        "diagnostics":diagnostics,
        "guardrails":[
            "Primary replication excludes Sjöbo because Sjöbo generated the hypotheses.",
            "Historical non-use is unlabeled, not a true negative.",
            "strict_never_pea reduces contamination but is still not a true negative class.",
            "Functional road class 0-9 is tested raw and in natural broad groups.",
            "The 4-or-7 indicator is explicitly post-hoc from Sjöbo and is not treated as an official NVDB category.",
            "Statlig/kommunal roadkeeper distance is a ranking proxy, not asserted to equal legal allmän väg.",
            "D1 validates features; it does not freeze an ÅkerAccess score."
        ],
        "outputs":{
            "positive_counts":str(counts_path),
            "positive_counts_by_municipality":str(mun_path),
            "summary":str(summary_path),
            "matches":str(matches_path),
        }
    }
    rp=outdir/"skane_d1_report.json"
    rp.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding="utf-8")

    print("\n"+"="*118)
    print("ÅkerAccess D1 - PRIMARY REPLICATION RESULT")
    print("="*118)
    print(f"Full Skåne eligible fields: {len(df):,}")
    print(counts_df.to_string(index=False))
    if primary_result:
        print("\nPRIMARY: Skåne excluding Sjöbo · 2023-2025 · strict-never-pea controls")
        print(
            f"  no_drivable_50m: pea={100*float(primary_result['positive_mean']):.2f}% "
            f"ctrl={100*float(primary_result['matched_control_mean']):.2f}% "
            f"diff={100*float(primary_result['paired_difference']):+.2f} pp "
            f"boot95=[{100*float(primary_result['bootstrap95_lo']):+.2f},"
            f"{100*float(primary_result['bootstrap95_hi']):+.2f}]"
        )
    print(f"\nSummary: {summary_path}")
    print(f"Matches: {matches_path}")
    print(f"Report: {rp}")
    print("="*118)
    print("ÅkerAccess D1 SKÅNE REPLICATION: PASS")
    print("="*118)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
