#!/usr/bin/env python3
"""B5: provisional split gate + unreviewed holdout QA. Merge remains candidate-only. Zero PU."""
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
    ap.add_argument("--pilot-dir")
    ap.add_argument("--raster-dir")
    ap.add_argument("--baseline-dir")
    ap.add_argument("--b3-dir")
    ap.add_argument("--b4-dir")
    ap.add_argument("--output-dir")
    args=ap.parse_args()

    cfg=json.loads(CFG.read_text(encoding="utf-8"))
    pdir=Path(args.pilot_dir or cfg["pilot_dir"]); rdir=Path(args.raster_dir or cfg["raster_dir"])
    bdir=Path(args.baseline_dir or cfg["baseline_dir"]); qdir=Path(args.b3_dir or cfg["b3_dir"])
    ddir=Path(args.b4_dir or cfg["b4_dir"]); out=Path(args.output_dir or cfg["output_dir"])
    (out/"retained_unreviewed").mkdir(parents=True,exist_ok=True)
    (out/"rejected_unreviewed").mkdir(parents=True,exist_ok=True)

    diag=pd.read_csv(ddir/"b4_split_morphology_edge_diagnostics.csv",dtype={"parent_field_id_2025":str})
    b2=pd.read_csv(bdir/"b2_field_changes.csv",dtype={"parent_field_id_2025":str})
    loo=pd.read_csv(qdir/"split_loo_robustness.csv",dtype={"parent_field_id_2025":str})
    merges=pd.read_csv(bdir/"b2_boundary_changes.csv",dtype={"field_a":str,"field_b":str})
    pilot=gpd.read_file(pdir/"pilot_fields_2025.gpkg").to_crs(32633)
    child_path=bdir/"b2_split_children_qa.gpkg"
    children=gpd.read_file(child_path).to_crs(32633) if child_path.exists() else None

    x=diag.merge(b2[["parent_field_id_2025","confidence"]],on="parent_field_id_2025",how="left",suffixes=("","_b2"))
    if "loo_all4" not in x.columns:
        x=x.merge(loo[["parent_field_id_2025","loo_all4"]],on="parent_field_id_2025",how="left")
    rule=cfg["provisional_split_rule"]
    edgecols=["edge_ratio_april","edge_ratio_may","edge_ratio_june","edge_ratio_july"]
    x["edge_support_count"]=(x[edgecols]>=float(rule["edge_ratio_threshold"])).sum(axis=1)
    x["min_largest_component_fraction"]=x[["child0_largest_component_fraction","child1_largest_component_fraction"]].min(axis=1)
    x["pass_lcf"]=x["min_largest_component_fraction"]>=float(rule["minimum_largest_component_fraction_each_child"])
    x["pass_edge"]=x["edge_support_count"]>=int(rule["minimum_supporting_edge_snapshots"])
    x["pass_loo"]=x["loo_all4"].fillna(False).astype(bool) if bool(rule["require_loo_all4"]) else True
    x["split_rule_pass"]=x["pass_lcf"] & x["pass_edge"] & x["pass_loo"]
    x["rule_reason"]=x.apply(lambda r:
        "PASS" if r["split_rule_pass"] else
        ";".join(([f'LCF<{rule["minimum_largest_component_fraction_each_child"]}'] if not r["pass_lcf"] else [])+
                 ([f'EDGE_SUPPORT<{rule["minimum_supporting_edge_snapshots"]}'] if not r["pass_edge"] else [])+
                 (["LOO_FAIL"] if not r["pass_loo"] else [])),axis=1)

    # Manual anchor class exists only for previously reviewed examples; all others form the visual holdout.
    anchors=x[x["manual_anchor_class"].isin(["CLEAR","FALSE"])].copy()
    holdout=x[~x["manual_anchor_class"].isin(["CLEAR","FALSE"])].copy()
    x.to_csv(out/"b5_split_rule_all_candidates.csv",index=False)
    anchors.to_csv(out/"b5_reviewed_anchor_check.csv",index=False)
    holdout.to_csv(out/"b5_unreviewed_holdout.csv",index=False)

    clear=anchors[anchors["manual_anchor_class"]=="CLEAR"]
    false=anchors[anchors["manual_anchor_class"]=="FALSE"]
    clear_keep=int(clear["split_rule_pass"].sum())
    false_reject=int((~false["split_rule_pass"]).sum())

    # Merge output deliberately does NOT pretend to solve the satellite identifiability problem.
    mc=merges[merges["change_type"]=="MERGE_CANDIDATE"].copy()
    mc["v0_status"]="MERGE_CANDIDATE"
    mc["automatic_merge"]=False
    mc["identifiability_note"]=cfg["merge_policy"]["reason"]
    mc.to_csv(out/"b5_merge_candidate_only.csv",index=False)

    # Generate blinded/unreviewed images: highest-B2-confidence retained and rejected examples only.
    b3=load_b3()
    rasters=[(s,rdir/f"{s.lower()}.tif") for s in SNAPS]
    n=int(cfg["holdout_images_per_group"])
    retained=holdout[holdout["split_rule_pass"]].sort_values("confidence",ascending=False).head(n)
    rejected=holdout[~holdout["split_rule_pass"]].sort_values("confidence",ascending=False).head(n)
    retained_files=[]; rejected_files=[]
    for rank,(_,r) in enumerate(retained.iterrows(),1):
        f=out/"retained_unreviewed"/f"{rank:02d}_{str(r['parent_field_id_2025']).replace('|','_')}.png"
        if b3.render_candidate("split",r,pilot,children,rasters,f): retained_files.append(str(f))
    for rank,(_,r) in enumerate(rejected.iterrows(),1):
        f=out/"rejected_unreviewed"/f"{rank:02d}_{str(r['parent_field_id_2025']).replace('|','_')}.png"
        if b3.render_candidate("split",r,pilot,children,rasters,f): rejected_files.append(str(f))

    summary={
      "schema_version":"akerpuls-prelim-fields-2026-b5-holdout-v1","status":"PASS",
      "baseline_split_candidates":int(len(x)),
      "provisional_rule_retained":int(x["split_rule_pass"].sum()),
      "provisional_rule_rejected":int((~x["split_rule_pass"]).sum()),
      "reviewed_clear_retained":clear_keep,"reviewed_clear_total":int(len(clear)),
      "reviewed_false_rejected":false_reject,"reviewed_false_total":int(len(false)),
      "unreviewed_candidates":int(len(holdout)),
      "unreviewed_retained":int(holdout["split_rule_pass"].sum()),
      "unreviewed_rejected":int((~holdout["split_rule_pass"]).sum()),
      "retained_holdout_images":len(retained_files),"rejected_holdout_images":len(rejected_files),
      "merge_candidates_preserved":int(len(mc)),
      "merge_policy":"MERGE_CANDIDATE_ONLY",
      "sentinel_hub_pu_used":0,"thresholds_frozen":False,"geometry_modified":False,
      "next_step":"Blind visual review of B5 unreviewed retained/rejected split images before any split-rule freeze."
    }
    (out/"b5_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("AKERPULS PRELIM FIELDS 2026 - STOPPUNKT B5 PROVISIONAL SPLIT RULE + HOLDOUT QA")
    print(f'BASELINE_SPLITS={summary["baseline_split_candidates"]} RETAINED={summary["provisional_rule_retained"]} REJECTED={summary["provisional_rule_rejected"]}')
    print(f'REVIEWED_ANCHORS CLEAR_RETAIN={clear_keep}/{len(clear)} FALSE_REJECT={false_reject}/{len(false)}')
    print(f'UNREVIEWED={summary["unreviewed_candidates"]} RETAINED={summary["unreviewed_retained"]} REJECTED={summary["unreviewed_rejected"]}')
    print(f'HOLDOUT_IMAGES RETAINED={summary["retained_holdout_images"]} REJECTED={summary["rejected_holdout_images"]}')
    print(f'MERGE_CANDIDATES_PRESERVED={summary["merge_candidates_preserved"]} POLICY=MERGE_CANDIDATE_ONLY')
    print("SENTINEL_HUB_PU_USED=0")
    print("THRESHOLDS_FROZEN=FALSE")
    print("B5_STATUS=PASS")
    print("OUTPUT="+str(out))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
