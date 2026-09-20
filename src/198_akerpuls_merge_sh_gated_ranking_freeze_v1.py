#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Formal freeze of S2026/Hprior gated merge ranking v1."""
from __future__ import annotations
import argparse, hashlib, json, shutil, subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EXPECTED_BRANCH="feature/akerpuls-prelim-fields-2026-v0a"
EXPECTED_SOURCE_GIT_HEAD="9ef396ef496348bf603371526075953f47f92940"

SRC=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_sh_gated_ranking_v1")
DEFAULT_OUT=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_sh_gated_ranking_freeze_v1")
STATUS="FROZEN_AKERPULS_MERGE_SH_GATED_RANKING_V1"

EXPECTED_REVEAL_FREEZE_SHA="8ce0e0bd606da13f59576c63afd98d5fdebca655d23c88b4c17e2da42b8c9612"
EXPECTED_PARQUET_SHA="288a07042eaa80256541e6c25c14acd9a4b0fc0767822db540f831f0ae668e10"
EXPECTED_CSV_SHA="e2d3cf804525c5b7fa757607eda968d0c20d329e52d03750de852757775866bf"
EXPECTED_SUMMARY_SHA="f542da9f5026a5a5215cf881727b68bcce82e71b4ab8c70374468ff674fb5a48"
EXPECTED_COUNTS={
"A_CONFIRMED_HIGH":1011,
"B_SAT_HIGH_H_MID":1171,
"C_SAT_HIGH_H_LOW":54,
"D_S_NOT_HIGH":20122,
"U_M0_UNCERTAIN":4788,
}

def sha(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def git_guard()->str:
    branch=subprocess.check_output(["git","branch","--show-current"],cwd=ROOT,text=True).strip()
    if branch!=EXPECTED_BRANCH: raise RuntimeError(f"Expected {EXPECTED_BRANCH}, got {branch}")
    if subprocess.check_output(["git","status","--short"],cwd=ROOT,text=True).strip():
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--source-dir",default=str(SRC))
    ap.add_argument("--output-dir",default=str(DEFAULT_OUT))
    args=ap.parse_args()
    head=git_guard(); src=Path(args.source_dir); out=Path(args.output_dir)
    if out.exists(): raise RuntimeError(f"Freeze output already exists: {out}")
    summary=src/"MERGE_SH_GATED_RANKING_SUMMARY_V1.json"
    pq=src/"MERGE_SH_GATED_RANKING_V1.parquet"
    csv=src/"MERGE_SH_GATED_RANKING_V1.csv.gz"
    cross=src/"MERGE_SH_GATED_RANKING_BY_M0_STATUS.csv"
    for p in (summary,pq,csv,cross):
        if not p.is_file(): raise FileNotFoundError(p)
    if sha(summary)!=EXPECTED_SUMMARY_SHA: raise RuntimeError("Summary SHA changed")
    if sha(pq)!=EXPECTED_PARQUET_SHA: raise RuntimeError("Parquet SHA changed")
    if sha(csv)!=EXPECTED_CSV_SHA: raise RuntimeError("CSV SHA changed")

    s=json.loads(summary.read_text(encoding="utf-8-sig"))
    if s.get("status")!="PASS_TO_SH_GATED_RANKING_REVIEW": raise RuntimeError("Unexpected source status")
    if s.get("git_head")!=EXPECTED_SOURCE_GIT_HEAD: raise RuntimeError("Unexpected source git head")
    if s.get("parents",{}).get("reveal_analysis_freeze_sha256")!=EXPECTED_REVEAL_FREEZE_SHA:
        raise RuntimeError("Reveal lineage changed")
    if s.get("tier_counts")!=EXPECTED_COUNTS: raise RuntimeError(f"Tier counts changed: {s.get('tier_counts')}")
    if int(s.get("s2026_high_total",-1))!=2236: raise RuntimeError("S2026 high census changed")
    pol=s.get("policy",{})
    if pol.get("block_boundary_hard_wall") is not True: raise RuntimeError("Block hard-wall policy changed")
    if pol.get("cross_block_merge_allowed") is not False: raise RuntimeError("Cross-block policy changed")
    if pol.get("automatic_merge") is not False or pol.get("geometry_mutated") is not False:
        raise RuntimeError("Operational guards changed")

    freeze={
      "schema_version":"akerpuls-merge-sh-gated-ranking-freeze-v1",
      "status":STATUS,
      "freeze_git_head":head,
      "source_git_head":EXPECTED_SOURCE_GIT_HEAD,
      "parent_reveal_analysis_freeze_sha256":EXPECTED_REVEAL_FREEZE_SHA,
      "source_hashes":{
        "parquet_sha256":EXPECTED_PARQUET_SHA,
        "csv_gz_sha256":EXPECTED_CSV_SHA,
        "summary_sha256":EXPECTED_SUMMARY_SHA,
        "cross_table_sha256":sha(cross),
      },
      "terminology":s["terminology"],
      "rule":s["rule"],
      "tier_counts":EXPECTED_COUNTS,
      "s2026_high_total":2236,
      "policy":s["policy"],
      "contract":{
        "ranking_frozen_before_independent_validation_sampling":True,
        "first_audit_pairs_must_be_excluded_from_next_validation":True,
        "continuous_fusion":False,
        "fitted_weights":False,
        "automatic_merge":False,
        "geometry_mutated":False,
        "cross_block_merge_allowed":False,
      },
      "next":"INDEPENDENT_BLIND_VALIDATION_SAMPLE_A_AND_B_EXCLUDING_FIRST_100_AUDIT_PAIRS",
    }
    out.mkdir(parents=True,exist_ok=False)
    fp=out/"AKERPULS_MERGE_SH_GATED_RANKING_FREEZE_V1.json"
    fp.write_text(json.dumps(freeze,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    fsha=sha(fp)
    (out/"AKERPULS_MERGE_SH_GATED_RANKING_FREEZE_V1.sha256").write_text(
        fsha+"  AKERPULS_MERGE_SH_GATED_RANKING_FREEZE_V1.json\n",encoding="utf-8")
    shutil.copyfile(summary,out/"SOURCE_SH_GATED_RANKING_SUMMARY_V1.json")

    print("AKERPULS MERGE S2026/HPRIOR GATED RANKING FORMAL FREEZE")
    print(f"STATUS={STATUS}")
    print(f"SOURCE_GIT_HEAD={EXPECTED_SOURCE_GIT_HEAD}")
    print(f"FREEZE_GIT_HEAD={head}")
    print(f"REVEAL_ANALYSIS_FREEZE_SHA256={EXPECTED_REVEAL_FREEZE_SHA}")
    print(f"SH_GATED_RANKING_FREEZE_SHA256={fsha}")
    print("TIER_COUNTS="+" | ".join(f"{k}:{v}" for k,v in EXPECTED_COUNTS.items()))
    print("S2026_HIGH_TOTAL=2236")
    print("BLOCK_BOUNDARY_HARD_WALL=TRUE CROSS_BLOCK_MERGE_ALLOWED=FALSE")
    print("CONTINUOUS_FUSION=FALSE FITTED_WEIGHTS=FALSE AUTOMATIC_MERGE=FALSE GEOMETRY_MUTATED=FALSE")
    print("NEXT=INDEPENDENT_BLIND_VALIDATION_SAMPLE_A_AND_B_EXCLUDING_FIRST_100_AUDIT_PAIRS")
    print(f"OUTPUT={out}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
