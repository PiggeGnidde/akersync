#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freeze ÅkerPuls merge-v1 policy and build proposal-only 2026 geometry package.

Final product policy:
- official 2025 field geometry remains canonical;
- frozen split-v1 contributes 613 review-only internal split proposals;
- merge proposal = S2026>P90 AND Hprior>P25 (legacy A+B);
- S2026>P95 AND Hprior>P25 is marked HIGH_CONFIDENCE_PROPOSAL only;
- Hprior<=P25 within S2026>P90 is an explicit LOW_HPRIOR_VETO;
- no merge proposal removes a 2025 boundary automatically;
- no cross-block merge;
- no geometry mutation.

This stage consumes the formally frozen final auto-merge decision:
OVERALL_FINAL_GATE=FAIL => proposal-only merge-v1.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
EXPECTED_BRANCH="feature/akerpuls-prelim-fields-2026-v0a"

DECISION=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_final_automerge_gate_decision_freeze_v1\AKERPULS_MERGE_FINAL_AUTOMERGE_GATE_DECISION_FREEZE_V1.json")
EXPECTED_DECISION_SHA="f1cdb4f3cce62467a763c2a0fa6e4f8a190939e1518bf6a85f72b0e7ff873a71"

RANKING=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_sh_gated_ranking_v1\MERGE_SH_GATED_RANKING_V1.parquet")
EXPECTED_RANKING_SHA="288a07042eaa80256541e6c25c14acd9a4b0fc0767822db540f831f0ae668e10"
EXPECTED_RANKING_FREEZE_SHA="2f98d504c61ba71da396e4d459ffd6b3e5d2feaacbe5a8faaab9635d2882ef26"

SPLIT_FREEZE=Path(r"C:\AkerSyncRepo\work\akerpuls_d2c_full_skane_freeze_review_v1\akerpuls_preliminary_geometry_v1_freeze\AKERPULS_PRELIMINARY_GEOMETRY_V1_FREEZE.json")
EXPECTED_SPLIT_FREEZE_SHA="c2f4fd7ee03124f330d3a06a1d1465592399072ed5729a38e5a66ac27dcef376"

M0_GPKG=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_v1\m0_satellite_merge_boundaries.gpkg")
M0_FREEZE=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_freeze_v1\AKERPULS_MERGE_M0_SATELLITE_ONLY_FREEZE_V1.json")
EXPECTED_M0_FREEZE_SHA="fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051"

MAP166=ROOT/"src"/"166_akerpuls_preliminary_fields_2026_map_v1.py"

DEFAULT_OUT=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_v1_policy_proposal_geometry_v1")
STATUS="FROZEN_AKERPULS_MERGE_V1_POLICY_PROPOSAL_GEOMETRY_V1"

EXPECTED_FIELDS_2025=128636
EXPECTED_SPLIT_PROPOSALS=613
EXPECTED_SPLIT_NO_GEOMETRY=5
EXPECTED_PAIR_UNIVERSE=27146
EXPECTED_MERGE_PROPOSALS=2182
EXPECTED_LOW_HPRIOR_VETO=54
EXPECTED_S2026_HIGH_TOTAL=2236
EXPECTED_EPSG=32633


def sha(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()


def read_json(p:Path):
    return json.loads(p.read_text(encoding="utf-8-sig"))


def git_guard()->str:
    b=subprocess.check_output(["git","branch","--show-current"],cwd=ROOT,text=True).strip()
    if b!=EXPECTED_BRANCH: raise RuntimeError(f"Expected {EXPECTED_BRANCH}, got {b}")
    if subprocess.check_output(["git","status","--short"],cwd=ROOT,text=True).strip():
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()


def verify_file(p:Path,e:str,name:str):
    if not p.is_file(): raise FileNotFoundError(p)
    if sha(p)!=e: raise RuntimeError(f"{name} SHA changed")


def load_module(p:Path,name:str):
    spec=importlib.util.spec_from_file_location(name,p)
    m=importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


def write_gpkg(dest:Path, layers:list[tuple[str,object]]):
    tmp=dest.with_name(dest.stem+".partial.gpkg")
    if tmp.exists(): tmp.unlink()
    first=True
    for name,gdf in layers:
        mode="w" if first else "a"
        gdf.to_file(tmp,layer=name,driver="GPKG",index=False,mode=mode)
        first=False
    tmp.replace(dest)


def main()->int:
    import geopandas as gpd

    ap=argparse.ArgumentParser()
    ap.add_argument("--output-dir",default=str(DEFAULT_OUT))
    args=ap.parse_args()
    head=git_guard()
    out=Path(args.output_dir)
    if out.exists(): raise RuntimeError(f"Output already exists: {out}")

    print("AKERPULS MERGE-V1 POLICY + PROPOSAL-ONLY 2026 GEOMETRY")
    print(f"GIT_HEAD={head}")
    print("PROGRESS=VERIFY_FINAL_DECISION_AND_FROZEN_LINEAGE")

    verify_file(DECISION,EXPECTED_DECISION_SHA,"final auto-merge decision")
    verify_file(RANKING,EXPECTED_RANKING_SHA,"gated ranking")
    verify_file(SPLIT_FREEZE,EXPECTED_SPLIT_FREEZE_SHA,"split geometry freeze")
    verify_file(M0_FREEZE,EXPECTED_M0_FREEZE_SHA,"M0 freeze")

    dec=read_json(DECISION)
    if dec.get("status")!="FROZEN_AKERPULS_MERGE_FINAL_AUTOMERGE_GATE_DECISION_V1":
        raise RuntimeError("Unexpected final decision status")
    if dec.get("overall_pass") is not False:
        raise RuntimeError("Final auto-merge gate is not frozen FAIL")
    if dec.get("decision")!="MERGE_V1_PROPOSAL_ONLY_NO_AUTOMATIC_BOUNDARY_REMOVAL":
        raise RuntimeError("Unexpected final merge-v1 decision")
    if dec.get("interpretation_lock",{}).get("no_more_threshold_search_with_same_signals") is not True:
        raise RuntimeError("Final no-threshold-chase lock missing")
    if dec.get("contract",{}).get("blind_key_contents_revealed") is not False:
        raise RuntimeError("Final decision unexpectedly depends on blind-key reveal")

    split=read_json(SPLIT_FREEZE)
    if split.get("status")!="FROZEN_AKERPULS_PRELIMINARY_GEOMETRY_V1":
        raise RuntimeError("Unexpected split-v1 freeze status")
    if split.get("product_policy",{}).get("canonical_geometry")!="OFFICIAL_2025_GEOMETRY":
        raise RuntimeError("Split-v1 canonical geometry policy changed")
    if int(split.get("population",{}).get("prelim_2026_split_proposal",-1))!=EXPECTED_SPLIT_PROPOSALS:
        raise RuntimeError("Split proposal census changed")
    if int(split.get("population",{}).get("no_geometry_proposal",-1))!=EXPECTED_SPLIT_NO_GEOMETRY:
        raise RuntimeError("Split no-geometry census changed")

    prop_hashes=split.get("source_artifacts",{}).get("proposal_output_hashes",{})
    for required in ("p95_primary_split_line_review.gpkg","p95_split_proposal_summary.csv"):
        if required not in prop_hashes: raise RuntimeError(f"Split source missing {required}")
        rec=prop_hashes[required]
        p=Path(rec["path"])
        if not p.is_file() or sha(p)!=rec["sha256"]:
            raise RuntimeError(f"Split source changed: {required}")

    m0f=read_json(M0_FREEZE)
    gpkg_sha=m0f.get("source_hashes",{}).get("source_boundaries_gpkg_sha256")
    if not gpkg_sha or not M0_GPKG.is_file() or sha(M0_GPKG)!=gpkg_sha:
        raise RuntimeError("Frozen M0 boundary GPKG missing or changed")

    print("PROGRESS=BUILD_MERGE_POLICY_INDEX")
    d=pd.read_parquet(RANKING)
    if len(d)!=EXPECTED_PAIR_UNIVERSE or d["pair_key"].nunique()!=EXPECTED_PAIR_UNIVERSE:
        raise RuntimeError("Frozen pair universe changed")
    counts=d["sh_tier"].value_counts().to_dict()
    if int(counts.get("A_CONFIRMED_HIGH",0))!=1011: raise RuntimeError("A census changed")
    if int(counts.get("B_SAT_HIGH_H_MID",0))!=1171: raise RuntimeError("B census changed")
    if int(counts.get("C_SAT_HIGH_H_LOW",0))!=EXPECTED_LOW_HPRIOR_VETO: raise RuntimeError("C census changed")
    if int(counts.get("A_CONFIRMED_HIGH",0)+counts.get("B_SAT_HIGH_H_MID",0)+counts.get("C_SAT_HIGH_H_LOW",0))!=EXPECTED_S2026_HIGH_TOTAL:
        raise RuntimeError("S2026>P90 census changed")

    d["merge_v1_status"]="NO_MERGE_PROPOSAL"
    d.loc[d["sh_tier"].eq("U_M0_UNCERTAIN"),"merge_v1_status"]="UNCERTAIN_KEEP_2025_BOUNDARY"
    d.loc[d["sh_tier"].eq("C_SAT_HIGH_H_LOW"),"merge_v1_status"]="LOW_HPRIOR_VETO_KEEP_2025_BOUNDARY"
    d.loc[d["sh_tier"].isin(["A_CONFIRMED_HIGH","B_SAT_HIGH_H_MID"]),"merge_v1_status"]="MERGE_PROPOSAL_V1"

    d["high_confidence_proposal"]=(
        d["merge_v1_status"].eq("MERGE_PROPOSAL_V1")
        & (d["satellite_score_percentile"]>0.95)
    )
    d["automatic_boundary_removal"]=False
    d["canonical_geometry"]="OFFICIAL_2025_GEOMETRY"
    d["cross_block_merge_allowed"]=False

    n_prop=int(d["merge_v1_status"].eq("MERGE_PROPOSAL_V1").sum())
    n_veto=int(d["merge_v1_status"].eq("LOW_HPRIOR_VETO_KEEP_2025_BOUNDARY").sum())
    n_high=int(d["high_confidence_proposal"].sum())
    if n_prop!=EXPECTED_MERGE_PROPOSALS:
        raise RuntimeError(f"Expected {EXPECTED_MERGE_PROPOSALS} merge proposals, got {n_prop}")
    if n_veto!=EXPECTED_LOW_HPRIOR_VETO:
        raise RuntimeError("Low-Hprior veto census changed")

    print(f"MERGE_PROPOSALS_P90_HGT25={n_prop}")
    print(f"MERGE_HIGH_CONFIDENCE_PROPOSALS_P95_HGT25={n_high}")
    print(f"LOW_HPRIOR_VETO_P90_HLE25={n_veto}")

    print("PROGRESS=LOAD_EXACT_GEOMETRY")
    map166=load_module(MAP166,"akerpuls_map166_for_policy_package")
    official=map166.load_official_2025()
    if len(official)!=EXPECTED_FIELDS_2025:
        raise RuntimeError("Official 2025 field census changed")
    official=official.to_crs(EXPECTED_EPSG)

    split_lines=gpd.read_file(Path(prop_hashes["p95_primary_split_line_review.gpkg"]["path"])).to_crs(EXPECTED_EPSG)
    split_lines["parent_field_id_2025"]=split_lines["parent_field_id_2025"].astype(str)
    if len(split_lines)!=EXPECTED_SPLIT_PROPOSALS or split_lines["parent_field_id_2025"].duplicated().any():
        raise RuntimeError("Split-line layer changed")

    split_summary=pd.read_csv(Path(prop_hashes["p95_split_proposal_summary.csv"]["path"]),encoding="utf-8-sig",dtype={"parent_field_id_2025":str})
    no_ids=set(split_summary.loc[split_summary["proposal_status"].astype(str).eq("NO_SHARED_INTERFACE"),"parent_field_id_2025"].astype(str))
    if len(no_ids)!=EXPECTED_SPLIT_NO_GEOMETRY: raise RuntimeError("Split no-geometry IDs changed")
    split_no=official.loc[official["parent_field_id_2025"].isin(no_ids)].copy()
    if len(split_no)!=EXPECTED_SPLIT_NO_GEOMETRY: raise RuntimeError("Could not materialize five split no-geometry parents")

    mb=gpd.read_file(M0_GPKG).to_crs(EXPECTED_EPSG)
    mb["field_a"]=mb["field_a"].astype(str); mb["field_b"]=mb["field_b"].astype(str)
    mb["pair_key"]=mb["field_a"]+"||"+mb["field_b"]
    if mb["pair_key"].duplicated().any() or len(mb)!=EXPECTED_PAIR_UNIVERSE:
        raise RuntimeError("M0 shared-boundary geometry census changed")

    attrs=d[[
        "pair_key","m0_status","satellite_merge_score","satellite_score_percentile",
        "p_samecrop","hprior_percentile","sh_tier","merge_v1_status",
        "high_confidence_proposal","automatic_boundary_removal"
    ]].copy()
    mg=mb.merge(attrs,on="pair_key",how="inner",validate="one_to_one")
    if len(mg)!=EXPECTED_PAIR_UNIVERSE: raise RuntimeError("Ranking/boundary join changed")

    merge_prop=mg.loc[mg["merge_v1_status"].eq("MERGE_PROPOSAL_V1")].copy()
    merge_high=merge_prop.loc[merge_prop["high_confidence_proposal"].astype(bool)].copy()
    merge_veto=mg.loc[mg["merge_v1_status"].eq("LOW_HPRIOR_VETO_KEEP_2025_BOUNDARY")].copy()
    if len(merge_prop)!=n_prop or len(merge_high)!=n_high or len(merge_veto)!=n_veto:
        raise RuntimeError("Merge geometry subset census changed")

    print("PROGRESS=WRITE_PROPOSAL_ONLY_PACKAGE")
    out.mkdir(parents=True,exist_ok=False)
    gpkg=out/"akerpuls_2026_proposal_geometry_v1.gpkg"
    write_gpkg(gpkg,[
        ("official_2025_fields",official),
        ("split_proposal_lines_v1",split_lines),
        ("split_no_geometry_proposal",split_no),
        ("merge_proposal_boundaries_v1",merge_prop),
        ("merge_high_confidence_proposal",merge_high),
        ("merge_low_hprior_veto",merge_veto),
    ])

    idx_cols=[
        "pair_key","field_a","field_b","m0_status","satellite_merge_score",
        "satellite_score_percentile","p_samecrop","hprior_percentile","sh_tier",
        "merge_v1_status","high_confidence_proposal","automatic_boundary_removal",
        "canonical_geometry","cross_block_merge_allowed",
    ]
    index_path=out/"merge_v1_policy_index.csv.gz"
    d[idx_cols].to_csv(index_path,index=False,encoding="utf-8",compression="gzip")

    policy={
        "schema_version":"akerpuls-merge-v1-policy-proposal-geometry-v1",
        "status":STATUS,
        "frozen_utc":datetime.now(timezone.utc).isoformat(),
        "git_head":head,
        "lineage":{
            "final_automerge_decision_freeze_sha256":EXPECTED_DECISION_SHA,
            "sh_gated_ranking_freeze_sha256":EXPECTED_RANKING_FREEZE_SHA,
            "split_geometry_v1_freeze_sha256":EXPECTED_SPLIT_FREEZE_SHA,
            "m0_satellite_freeze_sha256":EXPECTED_M0_FREEZE_SHA,
        },
        "product_policy":{
            "canonical_geometry":"OFFICIAL_2025_GEOMETRY",
            "split_proposal_rule":"FROZEN_SPLIT_V1_P95_LINE_AVAILABLE",
            "split_proposals":EXPECTED_SPLIT_PROPOSALS,
            "merge_proposal_rule":"S2026>P90 AND Hprior>P25",
            "merge_proposals":n_prop,
            "merge_high_confidence_marker_rule":"S2026>P95 AND Hprior>P25",
            "merge_high_confidence_proposals":n_high,
            "low_hprior_veto_rule":"S2026>P90 AND Hprior<=P25",
            "low_hprior_veto_boundaries":n_veto,
            "automatic_boundary_removal":False,
            "cross_block_merge_allowed":False,
            "geometry_mutated":False,
            "merge_v1_is_proposal_only":True,
            "no_more_threshold_search_with_same_signals":True,
        },
        "validation_lock":{
            "final_gate_rule":"S2026>P95 AND Hprior>P25",
            "final_gate_n":80,
            "final_gate_broad_rate":0.90,
            "final_gate_strict_rate":0.5375,
            "final_gate_one_sided_wilson95_lower":0.831099146151965,
            "predeclared_required_lower":0.85,
            "final_gate_pass":False,
            "decision":"MERGE_V1_PROPOSAL_ONLY_NO_AUTOMATIC_BOUNDARY_REMOVAL",
        },
        "geometry_package":{
            "gpkg":gpkg.name,
            "layers":{
                "official_2025_fields":len(official),
                "split_proposal_lines_v1":len(split_lines),
                "split_no_geometry_proposal":len(split_no),
                "merge_proposal_boundaries_v1":len(merge_prop),
                "merge_high_confidence_proposal":len(merge_high),
                "merge_low_hprior_veto":len(merge_veto),
            },
            "important_semantics":"Merge proposal layers are overlays on canonical 2025 boundaries; they do not mean those boundaries have been removed.",
        },
        "guards":{
            "thresholds_tuned":False,
            "automatic_merge_executed":False,
            "official_2025_geometry_replaced":False,
            "geometry_mutated":False,
            "cross_block_merge_allowed":False,
        },
        "next":"BUILD_FINAL_SKANE_REVIEW_MAP_WITH_SPLIT_AND_MERGE_PROPOSAL_OVERLAYS",
    }

    manifest=out/"AKERPULS_MERGE_V1_POLICY_PROPOSAL_GEOMETRY_V1.json"
    manifest.write_text(json.dumps(policy,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    report=out/"AKERPULS_MERGE_V1_POLICY_REPORT.md"
    report.write_text(
        "# ÅkerPuls merge-v1 policy\n\n"
        "Official 2025 geometry remains canonical. No 2025 boundary is automatically removed.\n\n"
        f"- Frozen split proposals: {EXPECTED_SPLIT_PROPOSALS}\n"
        f"- Merge proposals (S2026>P90 and Hprior>P25): {n_prop}\n"
        f"- High-S2026 subset (S2026>P95 and Hprior>P25): {n_high}, still proposal-only\n"
        f"- Low-Hprior veto boundaries: {n_veto}\n"
        "- Cross-block merge: prohibited in v1\n"
        "- Final blind auto-merge gate: FAIL because one-sided Wilson 95% lower bound 0.8311 < 0.85\n"
        "- No further threshold search is permitted for the same S2026+Hprior signal family in merge-v1.\n",
        encoding="utf-8"
    )

    freeze_hash=sha(manifest)
    (out/"AKERPULS_MERGE_V1_POLICY_PROPOSAL_GEOMETRY_V1.sha256").write_text(
        freeze_hash+"  AKERPULS_MERGE_V1_POLICY_PROPOSAL_GEOMETRY_V1.json\n",encoding="utf-8")

    print(f"STATUS={STATUS}")
    print(f"FINAL_DECISION_FREEZE_SHA256={EXPECTED_DECISION_SHA}")
    print(f"SPLIT_PROPOSALS={EXPECTED_SPLIT_PROPOSALS}")
    print(f"MERGE_PROPOSALS={n_prop}")
    print(f"MERGE_HIGH_CONFIDENCE_PROPOSALS={n_high}")
    print(f"LOW_HPRIOR_VETO={n_veto}")
    print("CANONICAL_GEOMETRY=OFFICIAL_2025_GEOMETRY")
    print("MERGE_V1_PROPOSAL_ONLY=TRUE")
    print("AUTOMATIC_BOUNDARY_REMOVAL=FALSE")
    print("CROSS_BLOCK_MERGE_ALLOWED=FALSE")
    print("NO_MORE_THRESHOLD_SEARCH_WITH_SAME_SIGNALS=TRUE")
    print(f"GPKG_SHA256={sha(gpkg)}")
    print(f"POLICY_INDEX_SHA256={sha(index_path)}")
    print(f"POLICY_FREEZE_SHA256={freeze_hash}")
    print("NEXT=BUILD_FINAL_SKANE_REVIEW_MAP_WITH_SPLIT_AND_MERGE_PROPOSAL_OVERLAYS")
    print(f"OUTPUT={out}")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
