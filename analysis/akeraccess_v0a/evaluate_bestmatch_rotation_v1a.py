#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Evaluate BestMatch v0b policy under ÅkerFrö Rotation v1.1 classes.

This is an impact study only. Frozen BestMatch v0b remains read-only.
Weights stay exactly 50% ÄrtMatch + 25% road AreaLogistik + 25% ÅkerAccess.
A remains a hard tier before B.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_ROT=ROOT/"data"/"derived"/"akerfro_rotation_v1a"/"akerfro_rotation_v1a_fields.parquet"
DEFAULT_D5=ROOT/"work"/"akeraccess_v0a"/"bestmatch_d5"/"bestmatch_d5_fields.parquet"
DEFAULT_ACCESS=ROOT/"data"/"derived"/"akeraccess_v0a"/"akeraccess_v0a_fields.parquet"
DEFAULT_POLICY=ROOT/"config"/"akerfro_akeraccess_bestmatch_v0b_freeze.json"
DEFAULT_OUT=ROOT/"work"/"akerfro_rotation_v1a"/"bestmatch_impact"

def norm(x):
    s=str(x).strip()
    if s.endswith(".0"):
        try:return str(int(float(s)))
        except Exception:pass
    return s

def metrics(df,rank_col,n):
    q=df[df["bestmatch_v1a_candidate"]].copy()
    q=q[pd.to_numeric(q[rank_col],errors="coerce").notna()]
    q[rank_col]=pd.to_numeric(q[rank_col],errors="coerce")
    g=q.nsmallest(min(n,len(q)),rank_col)
    routed=g["bjuv_route_status"].astype(str).eq("ROUTED")
    return {
        "n_fields":int(len(g)),
        "area_ha":float(pd.to_numeric(g["field_area_ha"],errors="coerce").sum()),
        "historical_positive_hits":int(g["historical_conservart_positive"].fillna(False).astype(bool).sum()),
        "mean_artmatch":float(pd.to_numeric(g["artmatch_score"],errors="coerce").mean()),
        "mean_road_area_logistics":float(pd.to_numeric(g["road_area_logistics_score"],errors="coerce").mean()),
        "mean_akeraccess":float(pd.to_numeric(g["akeraccess_score_v0a"],errors="coerce").mean()),
        "route_coverage_pct":100.0*float(routed.mean()) if len(g) else float("nan"),
    }

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--rotation",default=str(DEFAULT_ROT))
    ap.add_argument("--d5",default=str(DEFAULT_D5))
    ap.add_argument("--akeraccess",default=str(DEFAULT_ACCESS))
    ap.add_argument("--policy",default=str(DEFAULT_POLICY))
    ap.add_argument("--out",default=str(DEFAULT_OUT))
    args=ap.parse_args()

    for p in [Path(args.rotation),Path(args.d5),Path(args.akeraccess),Path(args.policy)]:
        if not p.exists(): raise FileNotFoundError(p)
    policy=json.loads(Path(args.policy).read_text(encoding="utf-8-sig"))
    rot=pd.read_parquet(args.rotation,columns=["current_field_id","artkandidat_class_v0a","artkandidat_class_v1a","rotation_v1a_release_candidate"])
    d5=pd.read_parquet(args.d5).copy()
    acc=pd.read_parquet(args.akeraccess,columns=["field_id","akeraccess_score_v0a"]).copy()
    rot["field_id"]=rot["current_field_id"].map(norm)
    d5["field_id"]=d5["field_id"].map(norm)
    acc["field_id"]=acc["field_id"].map(norm)

    out=d5.merge(rot[["field_id","artkandidat_class_v0a","artkandidat_class_v1a","rotation_v1a_release_candidate"]],
                 on="field_id",how="left",validate="one_to_one",suffixes=("","_rot"))
    out=out.merge(acc,on="field_id",how="left",validate="one_to_one")
    if out["artkandidat_class_v1a"].isna().any(): raise RuntimeError("D5 field missing rotation v1.1 class")
    if out["akeraccess_score_v0a"].isna().any(): raise RuntimeError("D5 field missing frozen ÅkerAccess v0a")

    # Verify the score itself remains exactly the frozen 50/25/25 definition.
    w=policy["policy_weights"]
    out["bestmatch_v1a_score"]=(
        float(w["artmatch"])*pd.to_numeric(out["artmatch_score"],errors="coerce")
        +float(w["road_area_logistics"])*pd.to_numeric(out["road_area_logistics_score"],errors="coerce")
        +float(w["local_road_access"])*pd.to_numeric(out["akeraccess_score_v0a"],errors="coerce")
    )
    oldscore=pd.to_numeric(out["bestmatch_d5_balanced_score"],errors="coerce")
    diff=(out["bestmatch_v1a_score"]-oldscore).abs()
    maxdiff=float(diff.max()) if diff.notna().any() else float("nan")
    if not np.isfinite(maxdiff) or maxdiff>1e-9:
        raise RuntimeError(f"50/25/25 score drift vs frozen D5 balanced: {maxdiff}")

    out["bestmatch_v0b_candidate"]=out["d5_candidate"].fillna(False).astype(bool)
    out["bestmatch_v1a_candidate"]=out["artkandidat_class_v1a"].astype(str).isin(policy["candidate_classes"])
    classes=list(policy["candidate_classes"])
    classrank={c:i for i,c in enumerate(classes)}
    q=out[out["bestmatch_v1a_candidate"]].copy()
    q["_classrank"]=q["artkandidat_class_v1a"].map(classrank)
    q=q.sort_values(["_classrank","bestmatch_v1a_score","field_id"],ascending=[True,False,True],
                    na_position="last",kind="mergesort")
    out["bestmatch_v1a_rank"]=pd.NA
    out.loc[q.index,"bestmatch_v1a_rank"]=np.arange(1,len(q)+1)

    old_n=int(out["bestmatch_v0b_candidate"].sum())
    new_n=int(out["bestmatch_v1a_candidate"].sum())
    entrants=out[out["bestmatch_v1a_candidate"] & ~out["bestmatch_v0b_candidate"]].copy()
    missing_released=rot[
        rot["rotation_v1a_release_candidate"].fillna(False).astype(bool)
        & ~rot["field_id"].isin(set(out["field_id"]))
    ].copy()

    # Old frozen-ranking equivalent from D5 for apples-to-apples top-N comparison.
    out["old_rank"]=pd.to_numeric(out["rank_d5_balanced"],errors="coerce")
    rows=[]
    for n in [200,500,800,1000,2000,5000]:
        oldg=out[out["bestmatch_v0b_candidate"] & out["old_rank"].notna()].nsmallest(n,"old_rank")
        newg=out[out["bestmatch_v1a_candidate"] & pd.to_numeric(out["bestmatch_v1a_rank"],errors="coerce").notna()].copy()
        newg["bestmatch_v1a_rank"]=pd.to_numeric(newg["bestmatch_v1a_rank"],errors="coerce")
        newg=newg.nsmallest(n,"bestmatch_v1a_rank")
        oldids=set(oldg["field_id"]); newids=set(newg["field_id"])
        rows.append({
            "top_n":n,
            "old_fields":len(oldg),
            "new_fields":len(newg),
            "new_rotation_v1a_entrants":len(newids-oldids),
            "old_rotation_v0b_exits":len(oldids-newids),
            "old_area_ha":float(pd.to_numeric(oldg["field_area_ha"],errors="coerce").sum()),
            "new_area_ha":float(pd.to_numeric(newg["field_area_ha"],errors="coerce").sum()),
            "old_historical_positive_hits":int(oldg["historical_conservart_positive"].fillna(False).astype(bool).sum()),
            "new_historical_positive_hits":int(newg["historical_conservart_positive"].fillna(False).astype(bool).sum()),
        })
    topcmp=pd.DataFrame(rows)

    existing=out[out["bestmatch_v0b_candidate"] & out["bestmatch_v1a_candidate"]].copy()
    existing["new_rank_num"]=pd.to_numeric(existing["bestmatch_v1a_rank"],errors="coerce")
    existing["rank_delta_new_minus_old"]=existing["new_rank_num"]-existing["old_rank"]
    rankchg=existing[[
        "field_id","municipality","artkandidat_class_v1a","old_rank","new_rank_num","rank_delta_new_minus_old",
        "bestmatch_v1a_score"
    ]].sort_values(["rank_delta_new_minus_old","field_id"],kind="mergesort")

    od=Path(args.out);od.mkdir(parents=True,exist_ok=True)
    outp=od/"bestmatch_rotation_v1a_fields.parquet"
    entp=od/"new_v1a_bestmatch_candidates.csv"
    missp=od/"released_rotation_fields_outside_d5.csv"
    cmpp=od/"topn_comparison.csv"
    rankp=od/"existing_candidate_rank_changes.csv"
    sump=od/"bestmatch_rotation_v1a_impact_summary.json"
    out.to_parquet(outp,index=False)
    entrants.sort_values("bestmatch_v1a_rank",kind="mergesort").to_csv(entp,index=False,encoding="utf-8-sig")
    missing_released.to_csv(missp,index=False,encoding="utf-8-sig")
    topcmp.to_csv(cmpp,index=False,encoding="utf-8-sig")
    rankchg.to_csv(rankp,index=False,encoding="utf-8-sig")

    top800=topcmp[topcmp["top_n"].eq(800)].iloc[0].to_dict()
    summary={
        "schema_version":"akerfro-rotation-v1a-bestmatch-impact-v1",
        "status":"IMPACT_STUDY_ONLY_BESTMATCH_V0B_UNCHANGED",
        "frozen_policy_reused":{
            "weights":policy["policy_weights"],
            "class_order":"A before B",
            "score_max_abs_diff_vs_frozen_d5_balanced":maxdiff,
        },
        "old_bestmatch_candidate_fields":old_n,
        "new_bestmatch_candidate_fields":new_n,
        "net_new_bestmatch_candidates":new_n-old_n,
        "released_rotation_fields_total":int(rot["rotation_v1a_release_candidate"].fillna(False).astype(bool).sum()),
        "released_rotation_fields_present_in_d5":int(len(entrants)),
        "released_rotation_fields_outside_d5":int(len(missing_released)),
        "new_candidate_class_counts":{str(k):int(v) for k,v in out.loc[out["bestmatch_v1a_candidate"],"artkandidat_class_v1a"].value_counts().items()},
        "top800":top800,
        "outputs":{
            "fields":str(outp),"new_candidates":str(entp),"outside_d5":str(missp),
            "topn_comparison":str(cmpp),"rank_changes":str(rankp)
        },
        "guardrails":[
            "Frozen BestMatch v0b is not modified.",
            "No BestMatch weight is refitted.",
            "Only Rotation v1.1 class eligibility changes; component scores remain frozen.",
            "This output is an impact study, not a new BestMatch freeze."
        ]
    }
    sump.write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str)+"\n",encoding="utf-8")

    print("="*120)
    print("BestMatch v0b POLICY × ÅkerFrö Rotation v1.1 · IMPACT STUDY")
    print("="*120)
    print(f"Old BestMatch candidates: {old_n:,}")
    print(f"New candidates under v1.1 classes: {new_n:,} · net +{new_n-old_n:,}")
    print(f"Released rotation fields present in D5: {len(entrants):,} / 43")
    print(f"Released rotation fields outside D5: {len(missing_released):,}")
    print(f"50/25/25 score max abs diff: {maxdiff:.3g}")
    print("\nTOP-N IMPACT")
    print(topcmp.to_string(index=False,formatters={
        "old_area_ha":lambda v:f"{v:.1f}","new_area_ha":lambda v:f"{v:.1f}"
    }))
    if len(entrants):
        print("\nNEW BESTMATCH CANDIDATES · TOP 30 BY v1.1 RANK")
        show=["bestmatch_v1a_rank","field_id","municipality","artkandidat_class_v1a",
              "bestmatch_v1a_score","artmatch_score","road_area_logistics_score","akeraccess_score_v0a"]
        print(entrants.sort_values("bestmatch_v1a_rank").head(30)[show].to_string(index=False))
    print(f"\nSummary: {sump}")
    print("="*120)
    print("BESTMATCH ROTATION V1.1 IMPACT: PASS")
    print("="*120)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
