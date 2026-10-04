#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build canonical ÅkerFrö × ÅkerAccess BestMatch v0c.

v0c changes ONLY candidate eligibility from frozen ÅkerFrö v0a to frozen
ÅkerFrö Rotation v1.1. The BestMatch policy is identical to frozen v0b:

  A before B (hard class order)
  then 50% ÄrtMatch + 25% road AreaLogistik + 25% frozen ÅkerAccess v0a.

Frozen v0b, Rotation v1.1, D5 and ÅkerAccess v0a are read-only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_POLICY=ROOT/"config"/"akerfro_akeraccess_bestmatch_v0c_freeze.json"
DEFAULT_ROTATION=ROOT/"data"/"derived"/"akerfro_rotation_v1a"/"akerfro_rotation_v1a_fields.parquet"
DEFAULT_D5=ROOT/"work"/"akeraccess_v0a"/"bestmatch_d5"/"bestmatch_d5_fields.parquet"
DEFAULT_ACCESS=ROOT/"data"/"derived"/"akeraccess_v0a"/"akeraccess_v0a_fields.parquet"
DEFAULT_V0B=ROOT/"data"/"derived"/"akerfro_akeraccess_bestmatch_v0b"/"bestmatch_v0b_fields.parquet"
DEFAULT_OUT=ROOT/"data"/"derived"/"akerfro_akeraccess_bestmatch_v0c"


def load_json(path:Path)->dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def norm_id(x)->str:
    if x is None:
        return ""
    s=str(x).strip()
    if s.endswith(".0"):
        try:
            return str(int(float(s)))
        except Exception:
            pass
    return s


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--policy",default=str(DEFAULT_POLICY))
    ap.add_argument("--rotation",default=str(DEFAULT_ROTATION))
    ap.add_argument("--d5",default=str(DEFAULT_D5))
    ap.add_argument("--akeraccess",default=str(DEFAULT_ACCESS))
    ap.add_argument("--v0b",default=str(DEFAULT_V0B))
    ap.add_argument("--out",default=str(DEFAULT_OUT))
    args=ap.parse_args()

    policy=load_json(Path(args.policy))
    paths=[Path(args.rotation),Path(args.d5),Path(args.akeraccess),Path(args.v0b)]
    for p in paths:
        if not p.is_file():
            raise FileNotFoundError(p)

    rot=pd.read_parquet(args.rotation).copy()
    d5=pd.read_parquet(args.d5).copy()
    acc=pd.read_parquet(args.akeraccess,columns=["field_id","akeraccess_score_v0a"]).copy()
    v0b=pd.read_parquet(args.v0b).copy()

    rot["field_id"]=rot["current_field_id"].map(norm_id)
    d5["field_id"]=d5["field_id"].map(norm_id)
    acc["field_id"]=acc["field_id"].map(norm_id)
    v0b["field_id"]=v0b["field_id"].map(norm_id)

    for name,df in [("Rotation v1.1",rot),("D5",d5),("ÅkerAccess v0a",acc),("BestMatch v0b",v0b)]:
        if df["field_id"].duplicated().any():
            raise RuntimeError(f"{name}: duplicate field_id")

    rcols=[
        "field_id","artkandidat_class_v0a","artkandidat_class_v1a",
        "rotation_status_v1a","rotation_v1a_release_candidate","rotation_v1a_evidence"
    ]
    missing=[c for c in rcols if c not in rot.columns]
    if missing:
        raise RuntimeError(f"Rotation v1.1 missing columns: {missing}")

    base=d5.merge(rot[rcols],on="field_id",how="left",validate="one_to_one")
    if base["artkandidat_class_v1a"].isna().any():
        n=int(base["artkandidat_class_v1a"].isna().sum())
        raise RuntimeError(f"D5 fields missing Rotation v1.1 lineage: {n:,}")

    # D5's original class must be identical to the frozen v0a class carried by
    # Rotation v1.1. This protects against hidden upstream drift.
    if "artkandidat_class" not in base.columns:
        raise RuntimeError("D5 lacks original artkandidat_class")
    mismatch=base["artkandidat_class"].astype(str).ne(base["artkandidat_class_v0a"].astype(str))
    if mismatch.any():
        raise RuntimeError(f"D5/v0a class lineage mismatch: {int(mismatch.sum()):,} fields")

    base=base.rename(columns={"artkandidat_class":"artkandidat_class_v0a_d5"})
    base=base.merge(acc,on="field_id",how="left",validate="one_to_one")
    if base["akeraccess_score_v0a"].isna().any():
        raise RuntimeError(f"D5 fields missing frozen ÅkerAccess score: {int(base['akeraccess_score_v0a'].isna().sum()):,}")

    w=policy["policy_weights"]
    wa=float(w["artmatch"]); wl=float(w["road_area_logistics"]); wr=float(w["local_road_access"])
    if abs(wa+wl+wr-1.0)>1e-12:
        raise RuntimeError("BestMatch v0c weights do not sum to 1")

    base["bestmatch_v0c_score"]=(
        wa*pd.to_numeric(base["artmatch_score"],errors="coerce")
        +wl*pd.to_numeric(base["road_area_logistics_score"],errors="coerce")
        +wr*pd.to_numeric(base["akeraccess_score_v0a"],errors="coerce")
    )

    # Exact policy identity with the selected/frozen D5 balanced score.
    src=pd.to_numeric(base["bestmatch_d5_balanced_score"],errors="coerce")
    delta=(base["bestmatch_v0c_score"]-src).abs()
    maxdiff=float(delta.max()) if delta.notna().any() else float("nan")
    if not np.isfinite(maxdiff) or maxdiff>1e-9:
        raise RuntimeError(f"50/25/25 score drift vs D5 balanced: max abs diff={maxdiff}")

    classes=list(policy["candidate_classes"])
    base["bestmatch_v0c_candidate"]=base["artkandidat_class_v1a"].astype(str).isin(classes)
    rankmap={c:i for i,c in enumerate(classes)}
    q=base[base["bestmatch_v0c_candidate"]].copy()
    q["_class_rank_v0c"]=q["artkandidat_class_v1a"].map(rankmap)
    q=q.sort_values(
        ["_class_rank_v0c","bestmatch_v0c_score","field_id"],
        ascending=[True,False,True],
        na_position="last",kind="mergesort"
    )
    base["bestmatch_v0c_rank"]=pd.NA
    base.loc[q.index,"bestmatch_v0c_rank"]=np.arange(1,len(q)+1)

    cand=base[base["bestmatch_v0c_candidate"]].copy()
    cand["bestmatch_v0c_rank"]=pd.to_numeric(cand["bestmatch_v0c_rank"],errors="raise").astype("Int64")
    cand["artkandidat_class"]=cand["artkandidat_class_v1a"].astype("string")
    cand["bestmatch_v0c_policy"]="balanced_50_25_25"
    cand["bestmatch_v0c_rotation_eligibility"]="akerfro-rotation-v1a"
    cand["bestmatch_v0c_status"]="SELECTED_PRODUCT_FOR_FORMAL_FREEZE"
    cand=cand.sort_values("bestmatch_v0c_rank",kind="mergesort").reset_index(drop=True)

    expected_n=int(policy["expected_candidate_fields"])
    if len(cand)!=expected_n:
        raise RuntimeError(f"v0c candidate count drift: {len(cand):,} != {expected_n:,}")
    got_classes={str(k):int(v) for k,v in cand["artkandidat_class"].value_counts().items()}
    exp_classes={str(k):int(v) for k,v in policy["expected_class_counts"].items()}
    if got_classes!=exp_classes:
        raise RuntimeError(f"v0c class count drift: {got_classes} != {exp_classes}")

    ranks=cand["bestmatch_v0c_rank"].astype(int).tolist()
    if ranks!=list(range(1,len(cand)+1)):
        raise RuntimeError("BestMatch v0c rank is not complete 1..N")

    # Hard A-before-B contract.
    n_a=int(exp_classes["A_STRONG_CANDIDATE"])
    if not cand.iloc[:n_a]["artkandidat_class"].eq("A_STRONG_CANDIDATE").all():
        raise RuntimeError("Hard A-before-B contract failed in A tier")
    if not cand.iloc[n_a:]["artkandidat_class"].eq("B_PHYSICAL_CANDIDATE").all():
        raise RuntimeError("Hard A-before-B contract failed in B tier")

    old_ids=set(v0b["field_id"].astype(str))
    new_ids=set(cand["field_id"].astype(str))
    new_only=new_ids-old_ids
    dropped=old_ids-new_ids
    exp_vs=policy["expected_vs_v0b"]
    if len(v0b)!=int(exp_vs["v0b_candidate_fields"]):
        raise RuntimeError(f"v0b baseline count drift: {len(v0b):,}")
    if len(new_only)!=int(exp_vs["new_candidates"]):
        raise RuntimeError(f"new candidate anchor drift: {len(new_only)}")
    if len(dropped)!=int(exp_vs["dropped_candidates"]):
        raise RuntimeError(f"dropped candidate anchor drift: {len(dropped)}")

    rows=[]
    for key,expected_churn in policy["expected_topn_churn"].items():
        n=int(key)
        oldg=v0b.sort_values("bestmatch_v0b_rank",kind="mergesort").head(n)
        newg=cand.head(n)
        oldset=set(oldg["field_id"].astype(str)); newset=set(newg["field_id"].astype(str))
        entrants=len(newset-oldset); exits=len(oldset-newset)
        oldhits=int(oldg["historical_conservart_positive"].fillna(False).astype(bool).sum())
        newhits=int(newg["historical_conservart_positive"].fillna(False).astype(bool).sum())
        expected_hits=int(policy["expected_balanced_historical_hits"][key])
        if entrants!=int(expected_churn) or exits!=int(expected_churn):
            raise RuntimeError(f"top-{n} churn drift: entrants/exits={entrants}/{exits}, expected {expected_churn}")
        if oldhits!=expected_hits or newhits!=expected_hits:
            raise RuntimeError(f"top-{n} historical-hit drift: old/new={oldhits}/{newhits}, expected {expected_hits}")
        rows.append({
            "top_n":n,
            "new_v0c_entrants":entrants,
            "old_v0b_exits":exits,
            "old_area_ha":float(pd.to_numeric(oldg["field_area_ha"],errors="coerce").sum()),
            "new_area_ha":float(pd.to_numeric(newg["field_area_ha"],errors="coerce").sum()),
            "old_historical_positive_hits":oldhits,
            "new_historical_positive_hits":newhits,
        })
    comparison=pd.DataFrame(rows)

    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    fp=out/"bestmatch_v0c_fields.parquet"
    top=out/"bestmatch_v0c_top5000.csv"
    cp=out/"bestmatch_v0c_vs_v0b_topn.csv"
    sp=out/"bestmatch_v0c_summary.json"

    cand.to_parquet(fp,index=False)
    cand.head(5000).to_csv(top,index=False,encoding="utf-8-sig")
    comparison.to_csv(cp,index=False,encoding="utf-8-sig")

    routed=cand["bjuv_proximity_d5_source"].astype(str).eq("ROAD_NETWORK_D4")
    fallback=cand["bjuv_proximity_d5_source"].astype(str).eq("C10_STRAIGHTLINE_FALLBACK")
    entrants=cand[cand["field_id"].astype(str).isin(new_only)].copy()
    summary={
        "schema_version":"akerfro-akeraccess-bestmatch-v0c-product-v1",
        "status":"CANDIDATE_FOR_FORMAL_FREEZE",
        "freeze_name":policy["freeze_name"],
        "rotation_eligibility":"akerfro-rotation-v1a",
        "candidate_fields":int(len(cand)),
        "class_counts":got_classes,
        "weights":policy["policy_weights"],
        "class_order":"A_STRONG_CANDIDATE before B_PHYSICAL_CANDIDATE; weighted score orders only within class",
        "score_identity_max_abs_diff_vs_frozen_d5_balanced":maxdiff,
        "vs_v0b":{
            "v0b_candidates":int(len(v0b)),
            "new_candidates":int(len(new_only)),
            "dropped_candidates":int(len(dropped)),
            "new_A":int(entrants["artkandidat_class"].eq("A_STRONG_CANDIDATE").sum()),
            "new_B":int(entrants["artkandidat_class"].eq("B_PHYSICAL_CANDIDATE").sum()),
        },
        "bjuv_route":{
            "routed_fields":int(routed.sum()),
            "straightline_fallback_fields":int(fallback.sum()),
            "route_coverage_pct":100.0*float(routed.mean()),
            "semantics":policy["route_semantics"],
            "fallback":policy["fallback_semantics"],
        },
        "historical_positive_fields":int(cand["historical_conservart_positive"].fillna(False).astype(bool).sum()),
        "top800":{
            "fields":800,
            "area_ha":float(pd.to_numeric(cand.head(800)["field_area_ha"],errors="coerce").sum()),
            "historical_positive_hits":int(cand.head(800)["historical_conservart_positive"].fillna(False).astype(bool).sum()),
            "mean_artmatch":float(pd.to_numeric(cand.head(800)["artmatch_score"],errors="coerce").mean()),
            "mean_road_area_logistics":float(pd.to_numeric(cand.head(800)["road_area_logistics_score"],errors="coerce").mean()),
            "mean_akeraccess":float(pd.to_numeric(cand.head(800)["akeraccess_score_v0a"],errors="coerce").mean()),
        },
        "topn_regression":rows,
        "guardrails":policy["guardrails"],
        "outputs":{
            "fields":str(fp),
            "top5000":str(top),
            "topn_comparison":str(cp)
        }
    }
    sp.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    print("="*118)
    print("ÅkerFrö × ÅkerAccess BestMatch v0c · PRODUCT BUILD")
    print("="*118)
    print(f"Candidates: {len(cand):,} · A {got_classes['A_STRONG_CANDIDATE']:,} / B {got_classes['B_PHYSICAL_CANDIDATE']:,}")
    print(f"vs v0b: +{len(new_only):,} new · {len(dropped):,} dropped")
    print(f"New A/B: {summary['vs_v0b']['new_A']:,}/{summary['vs_v0b']['new_B']:,}")
    print(f"50/25/25 score max abs diff vs frozen D5 balanced: {maxdiff:.3g}")
    print(f"Bjuv routes: {int(routed.sum()):,} routed · {int(fallback.sum()):,} fallback · {100*routed.mean():.2f}%")
    print(f"Top 800: {summary['top800']['area_ha']:.1f} ha · historical positives {summary['top800']['historical_positive_hits']}")
    print("\nTOP-N v0c vs v0b")
    print(comparison.to_string(index=False,formatters={
        "old_area_ha":lambda v:f"{v:.1f}","new_area_ha":lambda v:f"{v:.1f}"
    }))
    print(f"\nProduct: {fp}")
    print(f"Summary: {sp}")
    print("="*118)
    print("BESTMATCH v0c PRODUCT BUILD: PASS")
    print("="*118)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
