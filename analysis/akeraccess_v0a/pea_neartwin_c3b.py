#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerAccess STOPPUNKT C3b — spatial/area near-twin validation in Sjöbo.

Each historical conservärt-positive field is compared with nearby non-positive
fields of similar current area. Matching is diagnostic, not causal proof.

Two control definitions are run:
  window_unlabeled : no clean CONSERVART in that validation window
  strict_never_pea : no clean CONSERVART anywhere in 2015-2025

Controls may be reused across positive fields; inference/CI is clustered at the
positive matched-set level by bootstrap resampling positive sets.
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

ROOT=Path(__file__).resolve().parents[2]
for p in (ROOT,ROOT/"src"):
    if str(p) not in sys.path:
        sys.path.insert(0,str(p))

from analysis.akeraccess_v0a.entry_discovery_v0a import discover_field_inputs, load_fields

DEFAULT_WORK=ROOT/"work"/"akeraccess_v0a"/"sjobo"
DEFAULT_CFG=ROOT/"config"/"akeraccess_c3b.json"


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
    return json.loads(p.read_text(encoding="utf-8"))


def qdict(x:pd.Series|np.ndarray)->dict[str,float|None]:
    s=pd.to_numeric(pd.Series(x),errors="coerce").dropna()
    if s.empty:
        return {"p10":None,"p25":None,"p50":None,"p75":None,"p90":None}
    return {f"p{q}":float(s.quantile(q/100)) for q in [10,25,50,75,90]}


def bootstrap_ci(diffs:np.ndarray,reps:int,seed:int)->tuple[float,float,float]:
    x=np.asarray(diffs,dtype=float)
    x=x[np.isfinite(x)]
    if len(x)==0:
        return math.nan,math.nan,math.nan
    mean=float(np.mean(x))
    if len(x)==1:
        return mean,math.nan,math.nan
    rng=np.random.default_rng(seed)
    idx=rng.integers(0,len(x),size=(reps,len(x)))
    b=np.mean(x[idx],axis=1)
    return mean,float(np.quantile(b,.025)),float(np.quantile(b,.975))


def prepare_geometry(df:pd.DataFrame)->tuple[pd.DataFrame,str]:
    blocks_path,skiften_path,local_cfg=discover_field_inputs()
    g=load_fields("Sjöbo",blocks_path,skiften_path)
    g["field_id"]=g["field_id"].map(norm_id)
    g=g[g["field_id"].isin(set(df["field_id"]))].copy()
    g=g.to_crs(3006)
    if g["field_id"].duplicated().any():
        raise RuntimeError("Field geometry is not unique by field_id")
    c=g.geometry.centroid
    xy=pd.DataFrame({
        "field_id":g["field_id"].astype(str).to_numpy(),
        "cx":c.x.to_numpy(),
        "cy":c.y.to_numpy(),
    })
    out=df.merge(xy,on="field_id",how="left",validate="one_to_one")
    if out[["cx","cy"]].isna().any().any():
        n=int(out["cx"].isna().sum())
        raise RuntimeError(f"Missing current geometry for {n} C3 fields")
    return out,str(local_cfg)


def ensure_outcomes(df:pd.DataFrame,nvmax:float)->pd.DataFrame:
    out=df.copy()
    out["area_ha_num"]=pd.to_numeric(out["area_ha"],errors="coerce")
    out["last_mile_num"]=pd.to_numeric(out["path_last_mile_to_anchor_m"],errors="coerce")
    out["access_connected"]=out["network_access_status"].eq("CONNECTED_TO_ROAD_NETWORK") & out["last_mile_num"].notna()
    for m in [50,100,250,500,1000]:
        out[f"within_{m}m"]=out["access_connected"] & out["last_mile_num"].le(m)

    def close_value(prefix:str,value_col:str,numeric:bool=False):
        d=pd.to_numeric(out.get(prefix+"_distance_m"),errors="coerce")
        raw=out.get(value_col,pd.Series(index=out.index,dtype=object))
        v=pd.to_numeric(raw,errors="coerce") if numeric else raw.copy()
        return v.where(d.le(nvmax))

    out["_width"]=close_value("Vägbredd","Vägbredd_Bredd",numeric=True)
    out["_fclass"]=close_value("FunktionellVägklass","FunktionellVägklass_Klass",numeric=False).astype("string")
    out["_keeper"]=close_value("Väghållare","Väghållare_Väghållartyp",numeric=False).astype("string")
    out["_bearing"]=close_value("Bärighet","Bärighet_Bärighetsklass",numeric=False).astype("string")

    # Explicitly post-hoc indicators from C3; never silently promoted to score.
    out["_fclass_4_or_7"]=out["_fclass"].isin(["4","4.0","7","7.0"])
    out["_keeper_kommunal"]=out["_keeper"].eq("kommunal")
    out["_keeper_enskild"]=out["_keeper"].eq("enskild")
    out["_width_ge_4_5"]=out["_width"].ge(4.5)
    out["_bearing_known"]=out["_bearing"].notna()
    out["_bearing_bk1"]=out["_bearing"].eq("BK 1")
    return out


def select_controls(pos:pd.Series,controls:pd.DataFrame,cfg:dict[str,Any])->pd.DataFrame:
    k=int(cfg["controls_per_positive"])
    dx=controls["cx"].to_numpy(float)-float(pos["cx"])
    dy=controls["cy"].to_numpy(float)-float(pos["cy"])
    dist=np.hypot(dx,dy)
    pa=float(pos["area_ha_num"])
    ca=controls["area_ha_num"].to_numpy(float)
    good_area=np.isfinite(ca) & (ca>0) & np.isfinite(pa) & (pa>0)
    ratio=np.full(len(controls),np.nan)
    ratio[good_area]=ca[good_area]/pa
    logdiff=np.full(len(controls),np.inf)
    logdiff[good_area]=np.abs(np.log(ratio[good_area]))
    amin=float(cfg["area_ratio_min"]); amax=float(cfg["area_ratio_max"])
    r1=float(cfg["primary_match_radius_m"]); r2=float(cfg["fallback_match_radius_m"])
    eligible=good_area & (ratio>=amin) & (ratio<=amax) & (dist<=r1)
    stage="primary"
    if int(eligible.sum())<k:
        eligible=good_area & (ratio>=amin) & (ratio<=amax) & (dist<=r2)
        stage="fallback_radius"
    if int(eligible.sum())<k:
        eligible=good_area & (dist<=r2)
        stage="fallback_no_area_caliper"
    if int(eligible.sum())<k:
        eligible=good_area
        stage="fallback_global"
    ix=np.flatnonzero(eligible)
    score=dist[ix]+float(cfg["area_log_penalty_m"])*logdiff[ix]
    order=ix[np.argsort(score,kind="stable")[:k]]
    q=controls.iloc[order].copy()
    q["match_distance_m"]=dist[order]
    q["area_ratio_control_to_positive"]=ratio[order]
    q["match_stage"]=stage
    q["match_score"]=dist[order]+float(cfg["area_log_penalty_m"])*logdiff[order]
    return q


def mean_bool(s:pd.Series)->float:
    return float(s.fillna(False).astype(bool).mean()) if len(s) else math.nan


def metric_pair(pos:pd.Series,ctrl:pd.DataFrame,metric:str,kind:str)->tuple[float,float,float]:
    if kind=="bool":
        pv=float(bool(pos[metric]))
        cv=mean_bool(ctrl[metric])
    elif kind=="numeric":
        pv=pd.to_numeric(pd.Series([pos[metric]]),errors="coerce").iloc[0]
        cv=float(pd.to_numeric(ctrl[metric],errors="coerce").mean())
    else:
        raise ValueError(kind)
    return float(pv) if pd.notna(pv) else math.nan,cv,(float(pv)-cv if pd.notna(pv) and pd.notna(cv) else math.nan)


METRICS=[
    ("access_connected","bool"),
    ("within_50m","bool"),
    ("within_100m","bool"),
    ("within_250m","bool"),
    ("within_500m","bool"),
    ("within_1000m","bool"),
    ("_width_ge_4_5","bool"),
    ("_fclass_4_or_7","bool"),
    ("_keeper_kommunal","bool"),
    ("_keeper_enskild","bool"),
    ("_bearing_known","bool"),
    ("_bearing_bk1","bool"),
]


def run_match(df:pd.DataFrame,pos_col:str,control_mask:pd.Series,label:str,cfg:dict[str,Any],seed_offset:int):
    positives=df[df[pos_col]].copy().sort_values("field_id",kind="mergesort")
    controls=df[control_mask].copy()
    if positives.empty:
        return [],pd.DataFrame(),{"positive_n":0}

    set_rows=[]
    match_rows=[]
    for _,p in positives.iterrows():
        q=select_controls(p,controls,cfg)
        for _,c in q.iterrows():
            match_rows.append({
                "match_label":label,
                "positive_field_id":p["field_id"],
                "control_field_id":c["field_id"],
                "distance_m":c["match_distance_m"],
                "area_ratio_control_to_positive":c["area_ratio_control_to_positive"],
                "match_stage":c["match_stage"],
            })
        rec={"match_label":label,"positive_field_id":p["field_id"],"n_controls":int(len(q))}
        for metric,kind in METRICS:
            pv,cv,d=metric_pair(p,q,metric,kind)
            rec[metric+"_positive"]=pv
            rec[metric+"_control_mean"]=cv
            rec[metric+"_diff"]=d

        # Last-mile numeric only when positive is connected and at least one matched control is connected.
        if bool(p["access_connected"]):
            cq=q[q["access_connected"]]
            pv=float(p["last_mile_num"])
            cv=float(cq["last_mile_num"].mean()) if len(cq) else math.nan
            rec["last_mile_connected_positive"]=pv
            rec["last_mile_connected_control_mean"]=cv
            rec["last_mile_connected_diff"]=pv-cv if np.isfinite(cv) else math.nan
        else:
            rec["last_mile_connected_positive"]=math.nan
            rec["last_mile_connected_control_mean"]=math.nan
            rec["last_mile_connected_diff"]=math.nan
        set_rows.append(rec)

    sets=pd.DataFrame(set_rows)
    matches=pd.DataFrame(match_rows)
    reps=int(cfg["bootstrap_reps"])
    seed=int(cfg["random_seed"])+seed_offset
    summary=[]
    for i,(metric,kind) in enumerate(METRICS):
        d=pd.to_numeric(sets[metric+"_diff"],errors="coerce").to_numpy()
        mean,lo,hi=bootstrap_ci(d,reps,seed+i)
        summary.append({
            "match_label":label,
            "metric":metric,
            "positive_n":int(len(sets)),
            "positive_mean":float(pd.to_numeric(sets[metric+"_positive"],errors="coerce").mean()),
            "matched_control_mean":float(pd.to_numeric(sets[metric+"_control_mean"],errors="coerce").mean()),
            "paired_difference":mean,
            "bootstrap95_lo":lo,
            "bootstrap95_hi":hi,
        })
    d=pd.to_numeric(sets["last_mile_connected_diff"],errors="coerce").to_numpy()
    mean,lo,hi=bootstrap_ci(d,reps,seed+999)
    summary.append({
        "match_label":label,
        "metric":"last_mile_connected_m",
        "positive_n":int(np.isfinite(d).sum()),
        "positive_mean":float(pd.to_numeric(sets["last_mile_connected_positive"],errors="coerce").mean()),
        "matched_control_mean":float(pd.to_numeric(sets["last_mile_connected_control_mean"],errors="coerce").mean()),
        "paired_difference":mean,
        "bootstrap95_lo":lo,
        "bootstrap95_hi":hi,
    })

    diag={
        "positive_n":int(len(positives)),
        "control_pool_n":int(len(controls)),
        "match_rows":int(len(matches)),
        "unique_controls":int(matches["control_field_id"].nunique()),
        "max_control_reuse":int(matches["control_field_id"].value_counts().max()),
        "match_distance_m_quantiles":qdict(matches["distance_m"]),
        "area_ratio_quantiles":qdict(matches["area_ratio_control_to_positive"]),
        "match_stage_counts":{str(k):int(v) for k,v in matches["match_stage"].value_counts().items()},
    }
    return summary,matches,diag


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--work",default=str(DEFAULT_WORK))
    ap.add_argument("--config",default=str(DEFAULT_CFG))
    args=ap.parse_args()
    work=Path(args.work); cfg=load_cfg(Path(args.config))
    c3=work/"pea_validation_c3"/"sjobo_akeraccess_pea_c3_fields.csv"
    if not c3.exists():
        raise FileNotFoundError(f"Run C3 first: {c3}")
    df=pd.read_csv(c3,low_memory=False)
    df["field_id"]=df["field_id"].map(norm_id)
    if df["field_id"].duplicated().any():
        raise RuntimeError("C3 field_id not unique")
    df,geometry_source=prepare_geometry(df)
    df=ensure_outcomes(df,float(cfg["nvdb_match_max_m"]))

    windows=cfg["windows"]
    colmap={
        "recent_2023_2025":"pos_primary_2023_2025",
        "recent_2020_2025":"pos_recent_2020_2025",
        "all_2015_2025":"pos_all_2015_2025",
    }
    missing=[c for c in colmap.values() if c not in df.columns]
    if missing:
        raise RuntimeError("C3 missing expected positive columns: "+", ".join(missing))

    never_pea=~df[colmap["all_2015_2025"]].fillna(False).astype(bool)
    all_summary=[]
    all_matches=[]
    diagnostics={}
    seed_off=0

    for wname in windows:
        pos_col=colmap[wname]
        pos=df[pos_col].fillna(False).astype(bool)
        modes={
            "window_unlabeled":~pos,
            "strict_never_pea":never_pea,
        }
        for mode,mask in modes.items():
            label=f"{wname}__{mode}"
            summary,matches,diag=run_match(df,pos_col,mask,label,cfg,seed_off)
            seed_off+=100
            all_summary.extend(summary)
            all_matches.append(matches)
            diagnostics[label]=diag

    summary_df=pd.DataFrame(all_summary)
    matches_df=pd.concat(all_matches,ignore_index=True) if all_matches else pd.DataFrame()

    out=work/"pea_validation_c3b"
    out.mkdir(parents=True,exist_ok=True)
    sp=out/"sjobo_akeraccess_pea_c3b_neartwin_summary.csv"
    mp=out/"sjobo_akeraccess_pea_c3b_matches.csv"
    summary_df.to_csv(sp,index=False,encoding="utf-8-sig")
    matches_df.to_csv(mp,index=False,encoding="utf-8-sig")

    report={
        "schema_version":cfg["schema_version"],
        "eligible_fields":int(len(df)),
        "geometry_source":geometry_source,
        "windows":windows,
        "matching":{
            "controls_per_positive":cfg["controls_per_positive"],
            "primary_radius_m":cfg["primary_match_radius_m"],
            "fallback_radius_m":cfg["fallback_match_radius_m"],
            "area_ratio":[cfg["area_ratio_min"],cfg["area_ratio_max"]],
            "area_log_penalty_m":cfg["area_log_penalty_m"],
            "controls_reused":"yes; bootstrap is clustered by positive matched set",
        },
        "diagnostics":diagnostics,
        "guardrails":[
            "Small Sjöbo positive counts make C3b diagnostic, not a freeze.",
            "Historical non-use remains unlabeled.",
            "strict_never_pea controls reduce historical-positive contamination but do not create true negatives.",
            "Functional-class 4-or-7 and municipal-road indicators are explicitly post-hoc from C3.",
            "No ÅkerAccess score or threshold is frozen."
        ],
        "outputs":{"summary":str(sp),"matches":str(mp)},
    }
    rp=out/"sjobo_akeraccess_pea_c3b_report.json"
    rp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")

    print("="*112)
    print("ÅkerAccess STOPPUNKT C3b - SPATIAL / AREA NEAR-TWINS, SJÖBO")
    print("="*112)
    print(f"Eligible fields: {len(df):,}")
    for wname in windows:
        pos_col=colmap[wname]
        print(f"{wname}: positives={int(df[pos_col].fillna(False).sum()):,}")
    print()
    for label,diag in diagnostics.items():
        print("-"*112)
        print(label)
        print(f"  positives={diag['positive_n']:,}  control pool={diag['control_pool_n']:,}  unique controls used={diag['unique_controls']:,}  max reuse={diag['max_control_reuse']}")
        print(f"  match distance m: {diag['match_distance_m_quantiles']}")
        print(f"  area ratio ctrl/pea: {diag['area_ratio_quantiles']}")
        print(f"  match stages: {diag['match_stage_counts']}")
        q=summary_df[summary_df["match_label"].eq(label)]
        for r in q.itertuples(index=False):
            if r.metric=="last_mile_connected_m":
                print(f"  {r.metric:25s} pea={r.positive_mean:8.1f}  ctrl={r.matched_control_mean:8.1f}  diff={r.paired_difference:8.1f}  boot95=[{r.bootstrap95_lo:8.1f},{r.bootstrap95_hi:8.1f}]  n={int(r.positive_n)}")
            else:
                print(f"  {r.metric:25s} pea={100*r.positive_mean:6.1f}% ctrl={100*r.matched_control_mean:6.1f}% diff={100*r.paired_difference:+6.1f}pp boot95=[{100*r.bootstrap95_lo:+6.1f},{100*r.bootstrap95_hi:+6.1f}]")
    print(f"\nSummary: {sp}")
    print(f"Matches: {mp}")
    print(f"Report: {rp}")
    print("="*112)
    print("STOPPUNKT C3b: PASS")
    print("="*112)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
