#!/usr/bin/env python3
"""B5b: true visual holdout excluding ALL 12 split cases previously rendered in B3. Zero PU."""
from __future__ import annotations
import argparse, importlib.util, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CFG=ROOT/"config"/"akerpuls_prelim_fields_2026_b5.json"
B3SCRIPT=ROOT/"src"/"114_akerpuls_prelim_fields_2026_b3_qa.py"
SNAPS=["S2_2026_APRIL","S2_2026_MAY","S2_2026_JUNE","S2_2026_JULY"]

def load_b3():
    spec=importlib.util.spec_from_file_location("akerpuls_b3_render",B3SCRIPT)
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod

def main():
    import geopandas as gpd, pandas as pd
    ap=argparse.ArgumentParser()
    ap.add_argument("--pilot-dir",default=r"C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_stopb0_selection")
    ap.add_argument("--raster-dir",default=r"C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_b1_rasters")
    ap.add_argument("--baseline-dir",default=r"C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_b2_baseline")
    ap.add_argument("--b3-dir",default=r"C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_b3_qa")
    ap.add_argument("--b4-dir",default=r"C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_b4_diagnostic")
    ap.add_argument("--output-dir",default=r"C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_b5b_true_holdout")
    args=ap.parse_args()

    cfg=json.loads(CFG.read_text(encoding="utf-8"))
    pdir=Path(args.pilot_dir); rdir=Path(args.raster_dir); bdir=Path(args.baseline_dir)
    qdir=Path(args.b3_dir); ddir=Path(args.b4_dir); out=Path(args.output_dir)
    (out/"retained_true_holdout").mkdir(parents=True,exist_ok=True)
    (out/"rejected_true_holdout").mkdir(parents=True,exist_ok=True)

    diag=pd.read_csv(ddir/"b4_split_morphology_edge_diagnostics.csv",dtype={"parent_field_id_2025":str})
    b2=pd.read_csv(bdir/"b2_field_changes.csv",dtype={"parent_field_id_2025":str})
    loo=pd.read_csv(qdir/"split_loo_robustness.csv",dtype={"parent_field_id_2025":str})
    pilot=gpd.read_file(pdir/"pilot_fields_2025.gpkg").to_crs(32633)
    child_path=bdir/"b2_split_children_qa.gpkg"
    children=gpd.read_file(child_path).to_crs(32633) if child_path.exists() else None

    x=diag.merge(b2[["parent_field_id_2025","confidence"]],on="parent_field_id_2025",how="left",suffixes=("","_b2"))
    rule=cfg["provisional_split_rule"]
    edgecols=["edge_ratio_april","edge_ratio_may","edge_ratio_june","edge_ratio_july"]
    x["edge_support_count"]=(x[edgecols]>=float(rule["edge_ratio_threshold"])).sum(axis=1)
    x["min_largest_component_fraction"]=x[["child0_largest_component_fraction","child1_largest_component_fraction"]].min(axis=1)
    x["pass_lcf"]=x["min_largest_component_fraction"]>=float(rule["minimum_largest_component_fraction_each_child"])
    x["pass_edge"]=x["edge_support_count"]>=int(rule["minimum_supporting_edge_snapshots"])
    x["pass_loo"]=x["loo_all4"].fillna(False).astype(bool)
    x["split_rule_pass"]=x["pass_lcf"] & x["pass_edge"] & x["pass_loo"]

    # B3 wrote the already-rendered candidates in their visual-QA order.
    # Exclude ALL first 12, not merely the 8 later designated as CLEAR/FALSE anchors.
    previously_reviewed=loo.head(12)["parent_field_id_2025"].astype(str).tolist()
    holdout=x[~x["parent_field_id_2025"].astype(str).isin(set(previously_reviewed))].copy()
    contaminated=x[x["parent_field_id_2025"].astype(str).isin(set(previously_reviewed))].copy()

    holdout.to_csv(out/"b5b_true_holdout_candidates.csv",index=False)
    contaminated.to_csv(out/"b5b_excluded_previously_reviewed.csv",index=False)
    (out/"previously_reviewed_ids.json").write_text(json.dumps(previously_reviewed,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    retained=holdout[holdout["split_rule_pass"]].sort_values("confidence",ascending=False)
    rejected=holdout[~holdout["split_rule_pass"]].sort_values("confidence",ascending=False).head(8)

    b3=load_b3(); rasters=[(s,rdir/f"{s.lower()}.tif") for s in SNAPS]
    rf=[]; jf=[]
    for rank,(_,r) in enumerate(retained.iterrows(),1):
        f=out/"retained_true_holdout"/f"{rank:02d}_{str(r['parent_field_id_2025']).replace('|','_')}.png"
        if b3.render_candidate("split",r,pilot,children,rasters,f): rf.append(str(f))
    for rank,(_,r) in enumerate(rejected.iterrows(),1):
        f=out/"rejected_true_holdout"/f"{rank:02d}_{str(r['parent_field_id_2025']).replace('|','_')}.png"
        if b3.render_candidate("split",r,pilot,children,rasters,f): jf.append(str(f))

    summary={
      "schema_version":"akerpuls-prelim-fields-2026-b5b-true-holdout-v1","status":"PASS",
      "baseline_split_candidates":int(len(x)),
      "previously_reviewed_excluded":int(len(contaminated)),
      "true_holdout_candidates":int(len(holdout)),
      "true_holdout_retained":int(holdout["split_rule_pass"].sum()),
      "true_holdout_rejected":int((~holdout["split_rule_pass"]).sum()),
      "retained_images":len(rf),"rejected_images":len(jf),
      "sentinel_hub_pu_used":0,"thresholds_changed":False,"thresholds_frozen":False,
      "warning":"This fixes visual-QA leakage in B5. B5 artifacts remain historical and are not overwritten.",
      "next_step":"Review true-holdout images. If retained positives are too few, validate the provisional split rule in an independent geographic STOPPUNKT C pilot rather than tune further on B."
    }
    (out/"b5b_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("AKERPULS PRELIM FIELDS 2026 - B5b TRUE VISUAL HOLDOUT")
    print(f'BASELINE_SPLITS={len(x)} PREVIOUSLY_REVIEWED_EXCLUDED={len(contaminated)}')
    print(f'TRUE_HOLDOUT={len(holdout)} RETAINED={summary["true_holdout_retained"]} REJECTED={summary["true_holdout_rejected"]}')
    print(f'HOLDOUT_IMAGES RETAINED={len(rf)} REJECTED={len(jf)}')
    print("SENTINEL_HUB_PU_USED=0")
    print("THRESHOLDS_CHANGED=FALSE")
    print("THRESHOLDS_FROZEN=FALSE")
    print("B5B_STATUS=PASS")
    print("OUTPUT="+str(out))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
