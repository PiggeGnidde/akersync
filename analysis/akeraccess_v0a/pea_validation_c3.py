#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerAccess STOPPUNKT C3 — validate access against historical conservärt fields in Sjöbo.

Primary endpoint:
  fields with >=1 clean CONSERVART observation in 2023-2025
vs
  other currently eligible Sjöbo fields (positive-unlabeled framing).

No ÅkerAccess score is fitted or frozen here.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import unicodedata
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
for p in (ROOT,ROOT/"src"):
    if str(p) not in sys.path:
        sys.path.insert(0,str(p))

from analysis.akerfro_ertor_v0a.crop_groups import CONSERVART, akerfro_crop_group

DEFAULT_WORK=ROOT/"work"/"akeraccess_v0a"/"sjobo"
DEFAULT_CFG=ROOT/"config"/"akeraccess_c3.json"
DEFAULT_AKERMINNE=Path(r"C:\AkerSync-Minne")


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


def find_sjobo_history(root:Path, field_ids:set[str])->tuple[pd.DataFrame,Path]:
    mun=root/"data"/"derived"/"akerminne_v1a"/"skane"/"municipalities"
    if not mun.exists():
        raise FileNotFoundError(mun)
    candidates=sorted(mun.glob("*/akerminne_year_summary_classified.parquet"))
    cols=[
        "municipality","history_year","current_field_id","dominant_crop_name",
        "dominant_crop_known","status","current_area_m2",
    ]
    best=None; best_path=None; best_hits=-1
    for p in candidates:
        try:
            df=pd.read_parquet(p,columns=cols)
        except Exception:
            continue
        ids=df["current_field_id"].map(norm_id)
        hits=int(ids.isin(field_ids).sum())
        if hits>best_hits:
            best=df.copy(); best_path=p; best_hits=hits
    if best is None or best_hits<=0:
        raise RuntimeError("Could not locate Sjöbo ÅkerMinne history by field overlap")
    best["field_id"]=best["current_field_id"].map(norm_id)
    best["history_year"]=pd.to_numeric(best["history_year"],errors="coerce").astype("Int64")
    best["akerfro_group"]=best["dominant_crop_name"].map(akerfro_crop_group)
    best["clean_conservart"]=best["status"].eq("SINGLE_CROP") & best["akerfro_group"].eq(CONSERVART)
    return best,best_path


def positive_fields(hist:pd.DataFrame, years:list[int])->set[str]:
    q=hist[hist["history_year"].isin(years) & hist["clean_conservart"]]
    return set(q["field_id"].astype(str))


def rr_ci(a:int,n1:int,c:int,n0:int)->tuple[float,float,float]:
    """Approximate log risk-ratio CI; 0.5 correction only when required."""
    if n1<=0 or n0<=0:
        return math.nan,math.nan,math.nan
    aa=float(a); bb=float(n1-a); cc=float(c); dd=float(n0-c)
    if min(aa,bb,cc,dd)<=0:
        aa+=0.5; bb+=0.5; cc+=0.5; dd+=0.5
    r1=aa/(aa+bb); r0=cc/(cc+dd)
    rr=r1/r0 if r0>0 else math.inf
    se=math.sqrt(max(0.0,1/aa-1/(aa+bb)+1/cc-1/(cc+dd)))
    lo=math.exp(math.log(rr)-1.96*se)
    hi=math.exp(math.log(rr)+1.96*se)
    return rr,lo,hi


def compare_bool(df:pd.DataFrame, pos_col:str, event:pd.Series, label:str)->dict[str,Any]:
    pos=df[pos_col].fillna(False).astype(bool)
    ctl=~pos
    a=int(event[pos].fillna(False).sum()); n1=int(pos.sum())
    c=int(event[ctl].fillna(False).sum()); n0=int(ctl.sum())
    rr,lo,hi=rr_ci(a,n1,c,n0)
    out={
        "metric":label,
        "positive_event_n":a,"positive_n":n1,
        "positive_rate":a/n1 if n1 else None,
        "unlabeled_event_n":c,"unlabeled_n":n0,
        "unlabeled_rate":c/n0 if n0 else None,
        "risk_ratio":rr,"rr95_lo":lo,"rr95_hi":hi,
    }
    try:
        from scipy.stats import fisher_exact
        table=[[a,n1-a],[c,n0-c]]
        out["fisher_p"]=float(fisher_exact(table).pvalue)
    except Exception:
        out["fisher_p"]=None
    return out


def weighted_control_rate(df:pd.DataFrame,pos_col:str,event_col:str,area_bin_col:str)->float|None:
    pos=df[df[pos_col]].copy()
    ctl=df[~df[pos_col]].copy()
    if pos.empty or ctl.empty:
        return None
    total=len(pos)
    acc=0.0
    weight_sum=0.0
    for b,n in pos[area_bin_col].value_counts(dropna=False).items():
        if pd.isna(b):
            continue
        q=ctl[ctl[area_bin_col].eq(b)]
        if q.empty:
            continue
        w=n/total
        acc+=w*float(q[event_col].mean())
        weight_sum+=w
    return acc/weight_sum if weight_sum>0 else None


def qdict(s:pd.Series)->dict[str,float|None]:
    x=pd.to_numeric(s,errors="coerce").dropna()
    if x.empty:
        return {"p10":None,"p25":None,"p50":None,"p75":None,"p90":None}
    return {f"p{p}":float(x.quantile(p/100)) for p in [10,25,50,75,90]}


def safe_vc(s:pd.Series)->dict[str,int]:
    return {str(k):int(v) for k,v in s.fillna("(missing)").astype(str).value_counts().items()}


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--work",default=str(DEFAULT_WORK))
    ap.add_argument("--config",default=str(DEFAULT_CFG))
    ap.add_argument("--akerminne-root",default=str(DEFAULT_AKERMINNE))
    args=ap.parse_args()
    work=Path(args.work); cfg=load_cfg(Path(args.config))

    c1=work/"path_c1"/"sjobo_field_path_profile_c1.csv"
    c2=work/"nvdb_c2"/"sjobo_field_nvdb_anchor_match_c2.csv"
    if not c1.exists():
        raise FileNotFoundError(f"Run C1 first: {c1}")
    if not c2.exists():
        raise FileNotFoundError(f"Run C2 first: {c2}")

    base=pd.read_csv(c1,low_memory=False)
    base["field_id"]=base["field_id"].map(norm_id)
    if base["field_id"].duplicated().any():
        raise RuntimeError("C1 field_id is not unique")
    if len(base)!=4324:
        print(f"WARNING: expected current C1 eligible population 4,324; got {len(base):,}")

    nv=pd.read_csv(c2,low_memory=False)
    nv["field_id"]=nv["field_id"].map(norm_id)
    if nv["field_id"].duplicated().any():
        raise RuntimeError("C2 field_id is not unique")
    # Avoid duplicate last-mile helper columns from C2.
    keep=["field_id"]+[c for c in nv.columns if c not in {"field_id","last_mile_m","candidate_highway","anchor_node"}]
    df=base.merge(nv[keep],on="field_id",how="left",validate="one_to_one")

    hist,hist_path=find_sjobo_history(Path(args.akerminne_root),set(df["field_id"]))
    hist=hist[hist["field_id"].isin(set(df["field_id"]))].copy()

    primary=list(map(int,cfg["primary_window"]))
    windows={"primary_"+str(primary[0])+"_"+str(primary[-1]):primary}
    windows.update({k:list(map(int,v)) for k,v in cfg["secondary_windows"].items()})
    # Also year-specific diagnostics for the primary period.
    for y in primary:
        windows[f"year_{y}"]=[y]

    for name,years in windows.items():
        ids=positive_fields(hist,years)
        df["pos_"+name]=df["field_id"].isin(ids)

    area=pd.to_numeric(df["area_ha"],errors="coerce")
    bins=list(map(float,cfg["area_bins_ha"]))
    labels=list(cfg["area_bin_labels"])
    df["area_bin"]=pd.cut(area,bins=bins,labels=labels,right=False,include_lowest=True)

    lm=pd.to_numeric(df["path_last_mile_to_anchor_m"],errors="coerce")
    connected=df["network_access_status"].eq("CONNECTED_TO_ROAD_NETWORK") & lm.notna()
    df["access_connected"]=connected
    thresholds=list(map(float,cfg["last_mile_thresholds_m"]))
    for x in thresholds:
        df[f"within_{int(x)}m"]=connected & lm.le(x)

    primary_name="primary_"+str(primary[0])+"_"+str(primary[-1])
    outdir=work/"pea_validation_c3"
    outdir.mkdir(parents=True,exist_ok=True)

    comparisons=[]
    window_summary={}
    for wname,years in windows.items():
        pc="pos_"+wname
        npos=int(df[pc].sum())
        entry={"years":years,"positive_fields":npos,"eligible_fields":int(len(df))}
        metrics=[]
        metrics.append(compare_bool(df,pc,df["access_connected"],"CONNECTED_OSM_CANDIDATE"))
        for x in thresholds:
            metrics.append(compare_bool(df,pc,df[f"within_{int(x)}m"],f"CONNECTED_AND_LAST_MILE_LE_{int(x)}M"))
        for m in metrics:
            m["window"]=wname
            comparisons.append(m)
        pos_conn=df.loc[df[pc] & df["access_connected"],"path_last_mile_to_anchor_m"]
        ctl_conn=df.loc[(~df[pc]) & df["access_connected"],"path_last_mile_to_anchor_m"]
        entry["connected_last_mile_quantiles_positive_m"]=qdict(pos_conn)
        entry["connected_last_mile_quantiles_unlabeled_m"]=qdict(ctl_conn)
        entry["connected_positive_n"]=int(pos_conn.notna().sum())
        entry["connected_unlabeled_n"]=int(ctl_conn.notna().sum())
        try:
            from scipy.stats import mannwhitneyu
            if len(pos_conn) and len(ctl_conn):
                entry["mannwhitney_p_last_mile_connected"]=float(
                    mannwhitneyu(pd.to_numeric(pos_conn),pd.to_numeric(ctl_conn),alternative="two-sided").pvalue
                )
            else:
                entry["mannwhitney_p_last_mile_connected"]=None
        except Exception:
            entry["mannwhitney_p_last_mile_connected"]=None
        window_summary[wname]=entry

    comp=pd.DataFrame(comparisons)

    # Primary area-standardized controls: same area-bin mix as recent pea fields.
    pc="pos_"+primary_name
    std_rows=[]
    for event in ["access_connected"]+[f"within_{int(x)}m" for x in thresholds]:
        ctl_std=weighted_control_rate(df,pc,event,"area_bin")
        pr=float(df.loc[df[pc],event].mean()) if int(df[pc].sum()) else math.nan
        std_rows.append({
            "metric":event,
            "positive_rate":pr,
            "area_standardized_unlabeled_rate":ctl_std,
            "area_standardized_enrichment":pr/ctl_std if ctl_std and ctl_std>0 else None,
        })
    std=pd.DataFrame(std_rows)

    # Primary threshold CDF table, conditional and operational.
    cdf=[]
    for x in thresholds:
        for group,mask in [
            ("recent_conservart",df[pc]),
            ("unlabeled",~df[pc]),
        ]:
            q=df[mask]
            n=len(q); nc=int(q["access_connected"].sum())
            hit=int(q[f"within_{int(x)}m"].sum())
            cdf.append({
                "group":group,"threshold_m":x,"n_fields":n,
                "connected_n":nc,
                "operational_rate_all_fields":hit/n if n else None,
                "conditional_cdf_connected":hit/nc if nc else None,
            })
    cdf_df=pd.DataFrame(cdf)

    # NVDB comparisons use only close matches to the C1 ordinary-road anchor.
    nvmax=float(cfg["nvdb_match_max_m"])
    nvdb={}
    keeper_dist=pd.to_numeric(df.get("Väghållare_distance_m"),errors="coerce")
    keeper_ok=keeper_dist.le(nvmax)
    keeper=df.get("Väghållare_Väghållartyp",pd.Series(index=df.index,dtype=object)).where(keeper_ok)
    width_dist=pd.to_numeric(df.get("Vägbredd_distance_m"),errors="coerce")
    width_ok=width_dist.le(nvmax)
    width=pd.to_numeric(df.get("Vägbredd_Bredd"),errors="coerce").where(width_ok)
    fclass_dist=pd.to_numeric(df.get("FunktionellVägklass_distance_m"),errors="coerce")
    fclass_ok=fclass_dist.le(nvmax)
    fclass=df.get("FunktionellVägklass_Klass",pd.Series(index=df.index,dtype=object)).where(fclass_ok)
    bear_dist=pd.to_numeric(df.get("Bärighet_distance_m"),errors="coerce")
    bear_ok=bear_dist.le(nvmax)
    bear=df.get("Bärighet_Bärighetsklass",pd.Series(index=df.index,dtype=object)).where(bear_ok)

    for label,mask in [("recent_conservart",df[pc]),("unlabeled",~df[pc])]:
        nvdb[label]={
            "n_fields":int(mask.sum()),
            "roadkeeper_matched_n":int((mask & keeper.notna()).sum()),
            "roadkeeper_counts":safe_vc(keeper[mask].dropna()),
            "width_matched_n":int((mask & width.notna()).sum()),
            "width_quantiles_m":qdict(width[mask]),
            "width_lt_4_5m_n":int((mask & width.lt(4.5)).sum()),
            "functional_class_matched_n":int((mask & fclass.notna()).sum()),
            "functional_class_counts":safe_vc(fclass[mask].dropna()),
            "bearing_matched_n":int((mask & bear.notna()).sum()),
            "bearing_counts":safe_vc(bear[mask].dropna()),
        }

    # Year counts among the current eligible universe.
    yr=(
        hist[hist["clean_conservart"]]
        .groupby("history_year")["field_id"].nunique()
        .reindex(range(2015,2026),fill_value=0)
    )
    yearly={str(int(k)):int(v) for k,v in yr.items()}

    merged_path=outdir/"sjobo_akeraccess_pea_c3_fields.csv"
    comp_path=outdir/"sjobo_akeraccess_pea_c3_comparisons.csv"
    std_path=outdir/"sjobo_akeraccess_pea_c3_area_standardized.csv"
    cdf_path=outdir/"sjobo_akeraccess_pea_c3_cdf.csv"
    df.to_csv(merged_path,index=False,encoding="utf-8-sig")
    comp.to_csv(comp_path,index=False,encoding="utf-8-sig")
    std.to_csv(std_path,index=False,encoding="utf-8-sig")
    cdf_df.to_csv(cdf_path,index=False,encoding="utf-8-sig")

    report={
        "schema_version":cfg["schema_version"],
        "positive_definition":cfg["primary_positive_definition"],
        "primary_window":primary,
        "primary_positive_fields":int(df[pc].sum()),
        "eligible_fields":int(len(df)),
        "akerminne_source":str(hist_path),
        "clean_conservart_unique_fields_by_year_in_current_eligible_universe":yearly,
        "windows":window_summary,
        "primary_area_standardized":std.to_dict(orient="records"),
        "primary_nvdb":nvdb,
        "guardrails":[
            "Historical non-use is unlabeled, not a true negative.",
            "A field is counted once per window even if conservärt occurred multiple years.",
            "Operational distance rate counts no connected OSM candidate as not passing the distance threshold; conditional CDF is also reported separately.",
            "NVDB width is road width near the ordinary-road anchor, not field-entrance width or free-height clearance.",
            "Missing NVDB bearing class is unknown, not a failure.",
            "C3 is validation/diagnostics only; no ÅkerAccess score is frozen."
        ],
        "outputs":{
            "field_table":str(merged_path),
            "comparisons":str(comp_path),
            "area_standardized":str(std_path),
            "cdf":str(cdf_path),
        },
    }
    rp=outdir/"sjobo_akeraccess_pea_c3_report.json"
    rp.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding="utf-8")

    print("="*108)
    print("ÅkerAccess STOPPUNKT C3 - HISTORICAL CONSERVÄRT VALIDATION, SJÖBO")
    print("="*108)
    print(f"Eligible current fields: {len(df):,}")
    print(f"ÅkerMinne source: {hist_path}")
    print(f"Primary: clean CONSERVART in {primary[0]}-{primary[-1]} -> {int(df[pc].sum()):,} unique fields")
    print("\nCURRENT-ELIGIBLE CLEAN CONSERVÄRT FIELDS BY YEAR")
    print(pd.Series(yearly).to_string())
    print("\nPRIMARY ACCESS COMPARISON")
    q=comp[comp["window"].eq(primary_name)].copy()
    for r in q.itertuples(index=False):
        p=100*r.positive_rate if r.positive_rate is not None else math.nan
        u=100*r.unlabeled_rate if r.unlabeled_rate is not None else math.nan
        print(f"  {r.metric:40s} pea={p:6.1f}%  unlabeled={u:6.1f}%  RR={r.risk_ratio:5.2f}  95%CI [{r.rr95_lo:5.2f},{r.rr95_hi:5.2f}]" + (f"  Fisher p={r.fisher_p:.3g}" if r.fisher_p is not None else ""))
    print("\nPRIMARY AREA-STANDARDIZED UNLABELED COMPARISON")
    for r in std.itertuples(index=False):
        c=100*r.area_standardized_unlabeled_rate if r.area_standardized_unlabeled_rate is not None else math.nan
        p=100*r.positive_rate
        e=r.area_standardized_enrichment
        print(f"  {r.metric:24s} pea={p:6.1f}%  area-std unlabeled={c:6.1f}%  enrichment={e:5.2f}x")
    print("\nPRIMARY LAST-MILE QUANTILES AMONG CONNECTED FIELDS")
    ws=window_summary[primary_name]
    print("  pea:      ",ws["connected_last_mile_quantiles_positive_m"])
    print("  unlabeled:",ws["connected_last_mile_quantiles_unlabeled_m"])
    if ws.get("mannwhitney_p_last_mile_connected") is not None:
        print(f"  Mann-Whitney p={ws['mannwhitney_p_last_mile_connected']:.3g}")
    print("\nPRIMARY NVDB @ <=20 m FROM C1 ANCHOR")
    for group in ["recent_conservart","unlabeled"]:
        x=nvdb[group]
        print(f"  {group}:")
        print(f"    roadkeeper {x['roadkeeper_counts']}")
        print(f"    width q {x['width_quantiles_m']} · <4.5m n={x['width_lt_4_5m_n']:,}/{x['width_matched_n']:,}")
        print(f"    functional class {x['functional_class_counts']}")
        print(f"    bearing {x['bearing_counts']} (matched n={x['bearing_matched_n']:,})")
    print(f"\nReport: {rp}")
    print("="*108)
    print("STOPPUNKT C3: PASS")
    print("="*108)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
