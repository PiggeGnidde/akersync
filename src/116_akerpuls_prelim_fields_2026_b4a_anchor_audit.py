#!/usr/bin/env python3
"""B4a: audit reviewed visual anchors against B4 diagnostics. Zero API calls, no threshold changes."""
from __future__ import annotations
import argparse, json, math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CFG=ROOT/"config"/"akerpuls_prelim_fields_2026_b4.json"

def fmt(v):
    if v is None: return "NA"
    try:
        if math.isnan(float(v)): return "NA"
        return f"{float(v):.4f}"
    except Exception:
        return str(v)

def sep_report(df, class_col, features):
    import numpy as np
    rows=[]
    a=df[df[class_col]=="CLEAR"]
    b=df[df[class_col]=="FALSE"]
    for f in features:
        if f not in df.columns: continue
        x=a[f].dropna().astype(float).to_numpy()
        y=b[f].dropna().astype(float).to_numpy()
        if len(x)==0 or len(y)==0: continue
        # Separation sign positive means CLEAR tends larger; negative means CLEAR tends smaller.
        medx=float(np.median(x)); medy=float(np.median(y))
        rng=max(1e-9,float(np.nanmax(np.r_[x,y])-np.nanmin(np.r_[x,y])))
        rows.append({
          "feature":f,
          "clear_median":medx,
          "false_median":medy,
          "normalized_median_gap":(medx-medy)/rng,
          "clear_min":float(np.min(x)),"clear_max":float(np.max(x)),
          "false_min":float(np.min(y)),"false_max":float(np.max(y)),
        })
    return sorted(rows,key=lambda r:abs(r["normalized_median_gap"]),reverse=True)

def main():
    import pandas as pd, numpy as np
    ap=argparse.ArgumentParser()
    ap.add_argument("--b4-dir",default=r"C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_b4_diagnostic")
    ap.add_argument("--output-dir",default=r"C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_b4a_anchor_audit")
    args=ap.parse_args()

    cfg=json.loads(CFG.read_text(encoding="utf-8"))
    b4=Path(args.b4_dir); out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    s=pd.read_csv(b4/"b4_split_morphology_edge_diagnostics.csv",dtype={"parent_field_id_2025":str})
    m=pd.read_csv(b4/"b4_merge_candidate_diagnostics.csv",dtype={"field_a":str,"field_b":str,"pair_key":str})
    s=s[s["manual_anchor_class"].isin(["CLEAR","FALSE"])].copy()
    m=m[m["manual_anchor_class"].isin(["CLEAR","FALSE"])].copy()

    split_features=[
      "b2_confidence","child0_largest_component_fraction","child1_largest_component_fraction",
      "child0_components","child1_components","interface_pixels","interface_length_proxy_m",
      "interface_outer_endpoint_components","edge_ratio_april","edge_ratio_may","edge_ratio_june","edge_ratio_july",
      "edge_ratio_median","edge_ratio_max"
    ]
    merge_features=[
      "confidence","field_mean_distance","between_within_ratio","boundary_median_distance",
      "strong_edge_snapshots","edge_april","edge_may","edge_june","edge_july"
    ]
    # Derived merge trajectory diagnostics.
    edgecols=["edge_april","edge_may","edge_june","edge_july"]
    m["edge_max"]=m[edgecols].max(axis=1,skipna=True)
    m["edge_min"]=m[edgecols].min(axis=1,skipna=True)
    m["edge_range"]=m["edge_max"]-m["edge_min"]
    m["edge_mean"]=m[edgecols].mean(axis=1,skipna=True)
    m["edge_std"]=m[edgecols].std(axis=1,skipna=True,ddof=0)
    merge_features += ["edge_max","edge_min","edge_range","edge_mean","edge_std"]

    s.to_csv(out/"reviewed_split_anchor_metrics.csv",index=False)
    m.to_csv(out/"reviewed_merge_anchor_metrics.csv",index=False)
    sr=sep_report(s,"manual_anchor_class",split_features)
    mr=sep_report(m,"manual_anchor_class",merge_features)
    pd.DataFrame(sr).to_csv(out/"split_feature_separation.csv",index=False)
    pd.DataFrame(mr).to_csv(out/"merge_feature_separation.csv",index=False)

    print("AKERPULS PRELIM FIELDS 2026 - B4a REVIEWED ANCHOR AUDIT")
    print("SPLIT ANCHORS")
    for r in s.sort_values(["manual_anchor_class","b2_confidence"],ascending=[True,False]).itertuples(index=False):
        vals=" ".join([
          f"LCF0={fmt(getattr(r,'child0_largest_component_fraction',None))}",
          f"LCF1={fmt(getattr(r,'child1_largest_component_fraction',None))}",
          f"COMP={getattr(r,'child0_components',None)}/{getattr(r,'child1_components',None)}",
          f"IFACE={getattr(r,'interface_pixels',None)}",
          f"END={getattr(r,'interface_outer_endpoint_components',None)}",
          f"EDGE={fmt(getattr(r,'edge_ratio_april',None))}/{fmt(getattr(r,'edge_ratio_may',None))}/{fmt(getattr(r,'edge_ratio_june',None))}/{fmt(getattr(r,'edge_ratio_july',None))}",
          f"EMED={fmt(getattr(r,'edge_ratio_median',None))}",
          f"EMAX={fmt(getattr(r,'edge_ratio_max',None))}",
          f"LOO={getattr(r,'loo_all4',None)}"
        ])
        print(f"  {r.manual_anchor_class:5s} {r.parent_field_id_2025} {vals}")
    print("SPLIT TOP SEPARATING FEATURES")
    for r in sr[:8]:
        print(f'  {r["feature"]}: CLEAR_MED={r["clear_median"]:.4f} FALSE_MED={r["false_median"]:.4f} GAP={r["normalized_median_gap"]:.4f} CLEAR_RANGE={r["clear_min"]:.4f}-{r["clear_max"]:.4f} FALSE_RANGE={r["false_min"]:.4f}-{r["false_max"]:.4f}')

    print("MERGE ANCHORS")
    for r in m.sort_values(["manual_anchor_class","confidence"],ascending=[True,False]).itertuples(index=False):
        vals=" ".join([
          f"FIELD={fmt(getattr(r,'field_mean_distance',None))}",
          f"BW={fmt(getattr(r,'between_within_ratio',None))}",
          f"MED={fmt(getattr(r,'boundary_median_distance',None))}",
          f"EDGE={fmt(getattr(r,'edge_april',None))}/{fmt(getattr(r,'edge_may',None))}/{fmt(getattr(r,'edge_june',None))}/{fmt(getattr(r,'edge_july',None))}",
          f"MAX={fmt(getattr(r,'edge_max',None))}",
          f"RANGE={fmt(getattr(r,'edge_range',None))}",
          f"STD={fmt(getattr(r,'edge_std',None))}",
          f"LOO={getattr(r,'loo_all4',None)}"
        ])
        print(f"  {r.manual_anchor_class:5s} {r.pair_key} {vals}")
    print("MERGE TOP SEPARATING FEATURES")
    for r in mr[:10]:
        print(f'  {r["feature"]}: CLEAR_MED={r["clear_median"]:.4f} FALSE_MED={r["false_median"]:.4f} GAP={r["normalized_median_gap"]:.4f} CLEAR_RANGE={r["clear_min"]:.4f}-{r["clear_max"]:.4f} FALSE_RANGE={r["false_min"]:.4f}-{r["false_max"]:.4f}')

    summary={
      "schema_version":"akerpuls-prelim-fields-2026-b4a-anchor-audit-v1",
      "status":"PASS",
      "split_clear":int((s["manual_anchor_class"]=="CLEAR").sum()),
      "split_false":int((s["manual_anchor_class"]=="FALSE").sum()),
      "merge_clear":int((m["manual_anchor_class"]=="CLEAR").sum()),
      "merge_false":int((m["manual_anchor_class"]=="FALSE").sum()),
      "top_split_features":sr[:10],"top_merge_features":mr[:12],
      "sentinel_hub_pu_used":0,
      "thresholds_changed":False,
      "note":"Reviewed PNG labels are preliminary visual QA anchors, not ground truth."
    }
    (out/"b4a_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("SENTINEL_HUB_PU_USED=0")
    print("THRESHOLDS_CHANGED=FALSE")
    print("B4A_STATUS=PASS")
    print("OUTPUT="+str(out))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
