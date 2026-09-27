#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_CONFIG=ROOT/"config"/"akervatten_mvp_v0a_g.json"
KEY=["blockid","skiftesbeteckning"]

def load_json(p:Path)->dict[str,Any]:
    return json.loads(p.read_text(encoding="utf-8"))

def numeric(s:pd.Series)->pd.Series:
    return pd.to_numeric(s,errors="coerce").replace([np.inf,-np.inf],np.nan)

def band_label(x:float,bands:list[dict[str,Any]])->str|None:
    if pd.isna(x):
        return None
    for b in bands:
        if float(b["min"]) <= float(x) < float(b["max"]):
            return str(b["label"])
    return None

def detect_group_columns(df:pd.DataFrame)->list[str]:
    exact=[
        "kommun","kommun_namn","kommunnamn","Kommun","KOMMUN",
        "SKO","sko","dominant_sko","dom_sko","soil_class","jordklass"
    ]
    out=[]
    for c in exact:
        if c in df.columns and c not in out:
            out.append(c)
    return out

def detect_coordinate_columns(df:pd.DataFrame)->list[str]:
    pairs=[
        ("lon","lat"),("longitude","latitude"),("centroid_lon","centroid_lat"),
        ("field_lon","field_lat"),("x_wgs84","y_wgs84"),("east","north"),
        ("centroid_x","centroid_y")
    ]
    out=[]
    for a,b in pairs:
        if a in df.columns and b in df.columns:
            out.extend([a,b])
            break
    return out

def rank_tail_indices(score:pd.Series,fraction:float,high:bool)->pd.Index:
    x=numeric(score).dropna()
    if x.empty:
        return x.index
    n=max(1,int(math.ceil(len(x)*fraction)))
    ordered=x.sort_values(ascending=not high,kind="mergesort")
    return ordered.iloc[:n].index

def summarize_subset(df:pd.DataFrame,idx:pd.Index,component:str,tail:str,fraction:float,drivers:list[str])->dict[str,Any]:
    q=df.loc[idx]
    rec={
        "component":component,"tail":tail,"fraction":fraction,
        "n":int(len(q))
    }
    for d in drivers:
        if d in q.columns:
            x=numeric(q[d]).dropna()
            rec[f"{d}__n"]=int(len(x))
            rec[f"{d}__median"]=None if x.empty else float(x.median())
            rec[f"{d}__mean"]=None if x.empty else float(x.mean())
    return rec

def group_enrichment(df:pd.DataFrame,score_col:str,group_col:str,fraction:float)->pd.DataFrame:
    valid=df[score_col].notna() & df[group_col].notna()
    q=df.loc[valid,[group_col,score_col]].copy()
    if q.empty:
        return pd.DataFrame()
    hi_idx=rank_tail_indices(q[score_col],fraction,True)
    lo_idx=rank_tail_indices(q[score_col],fraction,False)
    base=q[group_col].astype(str).value_counts()
    hi=q.loc[hi_idx,group_col].astype(str).value_counts()
    lo=q.loc[lo_idx,group_col].astype(str).value_counts()
    cats=sorted(set(base.index)|set(hi.index)|set(lo.index))
    rows=[]
    for c in cats:
        b=int(base.get(c,0)); h=int(hi.get(c,0)); l=int(lo.get(c,0))
        base_share=b/len(q) if len(q) else np.nan
        hi_share=h/len(hi_idx) if len(hi_idx) else np.nan
        lo_share=l/len(lo_idx) if len(lo_idx) else np.nan
        rows.append({
            "group_column":group_col,"group_value":c,
            "population_n":b,"population_share":base_share,
            "high_n":h,"high_share":hi_share,
            "high_enrichment":None if base_share==0 else hi_share/base_share,
            "low_n":l,"low_share":lo_share,
            "low_enrichment":None if base_share==0 else lo_share/base_share,
            "fraction":fraction
        })
    return pd.DataFrame(rows)

def representative_cases(df:pd.DataFrame,component:str,score_col:str,targets:list[float],keep:list[str])->pd.DataFrame:
    q=df[df[score_col].notna()].copy()
    if q.empty:
        return pd.DataFrame()
    q["_score"]=numeric(q[score_col])
    rows=[]
    for t in targets:
        target=float(q["_score"].quantile(t))
        q["_dist"]=(q["_score"]-target).abs()
        sortcols=["_dist","_score"]
        asc=[True,True]
        for k in KEY:
            if k in q.columns:
                sortcols.append(k); asc.append(True)
        r=q.sort_values(sortcols,ascending=asc,kind="mergesort").iloc[0]
        rec={"component":component,"target_quantile":t,"target_score":target,"actual_score":float(r["_score"])}
        for c in keep:
            if c in r.index:
                rec[c]=r[c]
        rows.append(rec)
    return pd.DataFrame(rows)

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--config",default=str(DEFAULT_CONFIG))
    args=ap.parse_args()
    cfg=load_json(Path(args.config))
    work=ROOT/cfg["output"]["work_dir"]
    work.mkdir(parents=True,exist_ok=True)

    print("="*124)
    print("ÅkerVatten MVP v0a · STOPPUNKT G · GEOGRAPHIC / AGRONOMIC SANITY VALIDATION")
    print("="*124)
    print("Frozen F component formulas are not modified. No combined index is created.")

    print("\n[1/7] Load frozen F5 field table")
    df=pd.read_parquet(ROOT/cfg["paths"]["f5_fields"])
    if len(df)!=128636:
        raise RuntimeError(f"Expected 128636 fields, got {len(df)}")
    if df[KEY].duplicated().any():
        raise RuntimeError("Duplicate field keys")
    groups=detect_group_columns(df)
    coords=detect_coordinate_columns(df)
    print(f"  fields: {len(df):,}")
    print(f"  grouping columns detected: {', '.join(groups) if groups else '(none)'}")
    print(f"  coordinate columns detected: {', '.join(coords) if coords else '(none)'}")

    print("\n[2/7] Score range, coverage and fixed product bands")
    dist_rows=[]; band_rows=[]
    problems=[]
    for component,spec in cfg["components"].items():
        col=spec["score"]
        if col not in df.columns:
            problems.append(f"{component}: missing score column {col}")
            continue
        x=numeric(df[col])
        valid=x.dropna()
        if len(valid) and (valid.min() < -1e-9 or valid.max() > 100+1e-9):
            problems.append(f"{component}: score outside 0..100")
        qq=valid.quantile([.01,.10,.50,.90,.99]) if len(valid) else pd.Series(dtype=float)
        dist_rows.append({
            "component":component,"n":int(len(valid)),
            "coverage_pct":float(100*x.notna().mean()),
            "min":None if valid.empty else float(valid.min()),
            "p01":None if valid.empty else float(qq.loc[.01]),
            "p10":None if valid.empty else float(qq.loc[.10]),
            "p50":None if valid.empty else float(qq.loc[.50]),
            "p90":None if valid.empty else float(qq.loc[.90]),
            "p99":None if valid.empty else float(qq.loc[.99]),
            "max":None if valid.empty else float(valid.max())
        })
        labels=x.map(lambda v:band_label(v,cfg["score_bands"]))
        for b in cfg["score_bands"]:
            lab=b["label"]; n=int((labels==lab).sum())
            band_rows.append({"component":component,"band":lab,"n":n,
                              "pct_valid":100*n/max(1,int(x.notna().sum()))})
        print(f"  {component:23s}: n={len(valid):,} · min={valid.min():.2f} · P10={qq.loc[.10]:.2f} · P50={qq.loc[.50]:.2f} · P90={qq.loc[.90]:.2f} · max={valid.max():.2f}")
    pd.DataFrame(dist_rows).to_csv(work/"g_component_distributions.csv",index=False)
    pd.DataFrame(band_rows).to_csv(work/"g_component_bands.csv",index=False)

    print("\n[3/7] Hydrological unit invariants")
    unit_rows=[]
    for component,spec in cfg["components"].items():
        unit=spec.get("unit","field")
        if unit=="field":
            continue
        score=spec["score"]
        if unit not in df.columns:
            problems.append(f"{component}: unit column missing: {unit}")
            continue
        q=df[df[unit].notna() & df[score].notna()][[unit,score]].copy()
        nunits=int(q[unit].nunique())
        inconsistent=int((q.groupby(unit)[score].nunique(dropna=True)>1).sum())
        expected=int(spec.get("expected_unique_units",nunits))
        unit_rows.append({"component":component,"unit_column":unit,"unique_units":nunits,
                          "expected_units":expected,"inconsistent_units":inconsistent})
        print(f"  {component:23s}: units={nunits:,} expected={expected:,} · inconsistent score within unit={inconsistent}")
        if nunits!=expected:
            problems.append(f"{component}: expected {expected} units, got {nunits}")
        if inconsistent:
            problems.append(f"{component}: {inconsistent} units have multiple scores")
    pd.DataFrame(unit_rows).to_csv(work/"g_hydrological_unit_invariants.csv",index=False)

    print("\n[4/7] Extreme profiles · top/bottom 1%, 5%, 10%")
    profile_rows=[]
    extreme_case_rows=[]
    base_keep=KEY+groups+coords+["omrade_id","Subid","ARO_UUID"]
    for component,spec in cfg["components"].items():
        score=spec["score"]; drivers=[d for d in spec["drivers"] if d in df.columns]
        for f in cfg["extremes"]["fractions"]:
            for tail,high in (("HIGH",True),("LOW",False)):
                idx=rank_tail_indices(df[score],float(f),high)
                profile_rows.append(summarize_subset(df,idx,component,tail,float(f),drivers))
        n=int(cfg["extremes"]["rows_per_tail"])
        for tail,high in (("HIGH",True),("LOW",False)):
            x=numeric(df[score]).dropna().sort_values(ascending=not high,kind="mergesort").head(n)
            for rank,(idx,val) in enumerate(x.items(),start=1):
                rec={"component":component,"tail":tail,"rank":rank,"score":float(val)}
                for c in base_keep+drivers:
                    if c in df.columns:
                        rec[c]=df.at[idx,c]
                extreme_case_rows.append(rec)
        print(f"  {component:23s}: profiles complete")
    pd.DataFrame(profile_rows).to_csv(work/"g_extreme_driver_profiles.csv",index=False)
    pd.DataFrame(extreme_case_rows).to_csv(work/"g_extreme_cases.csv",index=False)

    print("\n[5/7] Geographic/group enrichment")
    enrich_parts=[]
    if not groups:
        print("  no kommun/SKO-like grouping columns found in F5 table; skipped")
    else:
        for component,spec in cfg["components"].items():
            for g in groups:
                z=group_enrichment(df,spec["score"],g,0.10)
                if len(z):
                    z.insert(0,"component",component)
                    enrich_parts.append(z)
            print(f"  {component:23s}: {len(groups)} grouping dimension(s)")
    enrich=pd.concat(enrich_parts,ignore_index=True) if enrich_parts else pd.DataFrame()
    enrich.to_csv(work/"g_group_enrichment_top_bottom10.csv",index=False)

    print("\n[6/7] 25 representative field cases")
    reps=[]
    keep=base_keep.copy()
    all_drivers=[]
    for spec in cfg["components"].values():
        all_drivers.extend(spec["drivers"])
    keep += [c for c in all_drivers if c not in keep]
    keep += [spec["score"] for spec in cfg["components"].values()]
    keep=list(dict.fromkeys([c for c in keep if c in df.columns]))
    for component,spec in cfg["components"].items():
        z=representative_cases(df,component,spec["score"],cfg["representative_quantiles"],keep)
        reps.append(z)
    reps=pd.concat(reps,ignore_index=True)
    reps.to_csv(work/"g_representative_25_cases.csv",index=False)
    print(f"  cases written: {len(reps):,}")

    print("\n[7/7] Contrast cases + product copy")
    contrasts=[
        ("dry_soil_good_gw","mark_torka_candidate_0_100",80,">=","grundvatten_tillgang_candidate_0_100",80,">="),
        ("dry_soil_poor_gw","mark_torka_candidate_0_100",80,">=","grundvatten_tillgang_candidate_0_100",20,"<="),
        ("high_wet_and_dry","mark_torka_candidate_0_100",80,">=","mark_vata_candidate_f5_0_100",80,">="),
        ("gw_drought_and_surface_drought","grundvatten_torka_candidate_0_100",80,">=","ytvatten_torka_candidate_0_100",80,">=")
    ]
    contrast_rows=[]
    for name,a,ta,opa,b,tb,opb in contrasts:
        xa=numeric(df[a]); xb=numeric(df[b])
        ma=(xa>=ta) if opa==">=" else (xa<=ta)
        mb=(xb>=tb) if opb==">=" else (xb<=tb)
        mask=ma&mb
        contrast_rows.append({"contrast":name,"n":int(mask.sum()),"pct_fields":float(100*mask.mean())})
        print(f"  {name:31s}: {int(mask.sum()):,} fields · {100*mask.mean():.3f}%")
    pd.DataFrame(contrast_rows).to_csv(work/"g_contrast_counts.csv",index=False)

    product={
        "score_bands":cfg["score_bands"],
        "components":cfg["product_copy"],
        "interpretation_rule":"0-100 is a relative empirical component scale. It is not a probability.",
        "combined_index":"NOT_DEFINED",
        "guardrails":cfg["guardrails"]
    }
    (work/"g_product_copy.json").write_text(json.dumps(product,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    status="PASS_WITH_REVIEW" if not problems else "FAIL"
    summary={
        "schema_version":"akervatten-mvp-v0a-g-sanity-validation-result",
        "status":status,
        "problems":problems,
        "detected_group_columns":groups,
        "detected_coordinate_columns":coords,
        "outputs":{
            "distributions":"g_component_distributions.csv",
            "bands":"g_component_bands.csv",
            "unit_invariants":"g_hydrological_unit_invariants.csv",
            "extreme_profiles":"g_extreme_driver_profiles.csv",
            "extreme_cases":"g_extreme_cases.csv",
            "group_enrichment":"g_group_enrichment_top_bottom10.csv",
            "representative_cases":"g_representative_25_cases.csv",
            "contrast_counts":"g_contrast_counts.csv",
            "product_copy":"g_product_copy.json"
        }
    }
    (work/"g_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    print(f"\n  problems: {len(problems)}")
    if problems:
        for p in problems:
            print("   -",p)
    print("  status:",status)
    print("  outputs:",work)
    print("="*124)
    print(f"AKERVATTEN STOPPUNKT G SANITY VALIDATION: {status}")
    print("="*124)
    return 0 if not problems else 2

if __name__=="__main__":
    raise SystemExit(main())
