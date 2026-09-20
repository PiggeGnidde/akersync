#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Formal freeze of the revealed blind M0/M1 merge audit analysis.

Verifies the predeclared HH/HL/LH/LL results already produced by src/195.
No new reveal analysis, fusion, sign selection, threshold tuning, automatic
merge, or geometry mutation is performed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
EXPECTED_SOURCE_GIT_HEAD = "237e3326bd395979271549e2a5578a628ce92115"

SOURCE_DIR = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_blind_disagreement_audit_reveal_analysis_v1")
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_blind_disagreement_audit_reveal_analysis_freeze_v1")
STATUS = "FROZEN_AKERPULS_MERGE_BLIND_AUDIT_REVEAL_ANALYSIS_V1"

EXPECTED_LABEL_FREEZE_SHA256 = "de4b7fc7e9a6587c966304bb70d9456f4f8d6f65cbb869c47ce6339e90057ba8"
EXPECTED_LABELS_SHA256 = "4bd2583ea4f1d4255997acbe5c602b7b0743641f7dd12ad961a8132e87969e70"
EXPECTED_BLIND_KEY_SHA256 = "706d800769ac2bd1eb9deb5ff6d035aaef2407b4586501bd2a0cfc5ad87feeee"
EXPECTED_SUMMARY_SHA256 = "f1d4314b79a531f1764d99d045acda59bd40ef8bd2fe66cc4ca04d74f8005f26"
EXPECTED_JOIN_SHA256 = "bce010ece5982599231117e83fb301f3391b78b00e5d6e39abc700588b63e284"

EXPECTED = {
    "HH": {"n":25,"assessable":25,"strict":0.64,"broad":0.88,"labels":{"TYDLIG_MERGE":16,"MÖJLIG_MERGE":6,"TVEKSAM":2,"BEHÅLL_GRÄNS":1,"EJ_BEDÖMBAR":0}},
    "HL": {"n":25,"assessable":25,"strict":0.28,"broad":0.56,"labels":{"TYDLIG_MERGE":7,"MÖJLIG_MERGE":7,"TVEKSAM":3,"BEHÅLL_GRÄNS":8,"EJ_BEDÖMBAR":0}},
    "LH": {"n":25,"assessable":24,"strict":0.0,"broad":1/24,"labels":{"TYDLIG_MERGE":0,"MÖJLIG_MERGE":1,"TVEKSAM":3,"BEHÅLL_GRÄNS":20,"EJ_BEDÖMBAR":1}},
    "LL": {"n":25,"assessable":25,"strict":0.0,"broad":0.08,"labels":{"TYDLIG_MERGE":0,"MÖJLIG_MERGE":2,"TVEKSAM":4,"BEHÅLL_GRÄNS":19,"EJ_BEDÖMBAR":0}},
}

EXPECTED_CONTRASTS = {
    ("HH_vs_HL","strict"):(0.36,0.022241296),
    ("HH_vs_HL","broad"):(0.32,0.025476633),
    ("LH_vs_LL","strict"):(0.0,1.0),
    ("LH_vs_LL","broad"):(-0.03833333333333334,1.0),
    ("HH_vs_LH","strict"):(0.64,8.298553e-07),
    ("HH_vs_LH","broad"):(0.8383333333333334,1.0699419e-09),
    ("HL_vs_LL","strict"):(0.28,0.0096251266),
    ("HL_vs_LL","broad"):(0.48,0.00057720208),
}


def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def git_guard() -> str:
    branch=subprocess.check_output(["git","branch","--show-current"],cwd=ROOT,text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    if subprocess.check_output(["git","status","--short"],cwd=ROOT,text=True).strip():
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()


def close(a,b,tol=5e-7):
    return abs(float(a)-float(b)) <= tol


def verify_source(src: Path) -> dict:
    summary_path=src/"MERGE_AUDIT_REVEAL_ANALYSIS_SUMMARY_V1.json"
    join_path=src/"MERGE_AUDIT_REVEALED_JOIN.csv"
    contrasts_path=src/"MERGE_AUDIT_PREDECLARED_CONTRASTS.csv"
    strata_path=src/"MERGE_AUDIT_BY_STRATUM.csv"
    manifest_path=src/"SHA256_MANIFEST.txt"
    for p in (summary_path,join_path,contrasts_path,strata_path,manifest_path):
        if not p.is_file():
            raise FileNotFoundError(p)
    if sha256_file(summary_path) != EXPECTED_SUMMARY_SHA256:
        raise RuntimeError("Reveal summary SHA changed")
    if sha256_file(join_path) != EXPECTED_JOIN_SHA256:
        raise RuntimeError("Reveal join SHA changed")

    s=load_json(summary_path)
    if s.get("status") != "PASS_TO_MERGE_AUDIT_REVEAL_REVIEW":
        raise RuntimeError("Unexpected reveal status")
    if s.get("git_head") != EXPECTED_SOURCE_GIT_HEAD:
        raise RuntimeError("Unexpected reveal source git head")
    parents=s.get("parents",{})
    if parents.get("labels_freeze_sha256") != EXPECTED_LABEL_FREEZE_SHA256:
        raise RuntimeError("Label-freeze lineage changed")
    if parents.get("labels_sha256") != EXPECTED_LABELS_SHA256:
        raise RuntimeError("Label SHA lineage changed")
    if parents.get("blind_key_sha256") != EXPECTED_BLIND_KEY_SHA256:
        raise RuntimeError("Blind-key lineage changed")

    by=s.get("by_stratum",{})
    for name,exp in EXPECTED.items():
        got=by.get(name,{})
        if int(got.get("n_total",-1)) != exp["n"] or int(got.get("n_assessable",-1)) != exp["assessable"]:
            raise RuntimeError(f"Stratum census changed: {name}")
        if got.get("label_counts") != exp["labels"]:
            raise RuntimeError(f"Stratum labels changed: {name}")
        if not close(got.get("strict_positive_rate"),exp["strict"]):
            raise RuntimeError(f"Strict rate changed: {name}")
        if not close(got.get("broad_positive_rate"),exp["broad"]):
            raise RuntimeError(f"Broad rate changed: {name}")

    got_contrasts={(r["contrast"],r["endpoint"]):r for r in s.get("predeclared_contrasts",[])}
    if set(got_contrasts) != set(EXPECTED_CONTRASTS):
        raise RuntimeError("Contrast set changed")
    for key,(rd,pval) in EXPECTED_CONTRASTS.items():
        r=got_contrasts[key]
        if not close(r.get("risk_difference_high_minus_low"),rd):
            raise RuntimeError(f"Risk difference changed: {key}")
        if not close(r.get("fisher_two_sided_p"),pval,1e-9):
            raise RuntimeError(f"Fisher p changed: {key}")

    guards=s.get("guards",{})
    for k in ("fusion_executed","fusion_score_created","fusion_weight_selected","sign_selected","thresholds_tuned","automatic_merge","geometry_mutated"):
        if guards.get(k) is not False:
            raise RuntimeError(f"Reveal guard changed: {k}")

    return {
        "summary_sha256":sha256_file(summary_path),
        "join_sha256":sha256_file(join_path),
        "contrasts_sha256":sha256_file(contrasts_path),
        "strata_sha256":sha256_file(strata_path),
        "source_manifest_sha256":sha256_file(manifest_path),
        "summary":s,
    }


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--source-dir",default=str(SOURCE_DIR))
    ap.add_argument("--output-dir",default=str(DEFAULT_OUT))
    args=ap.parse_args()
    head=git_guard()
    src=Path(args.source_dir); out=Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Freeze output already exists: {out}")
    v=verify_source(src)

    freeze={
        "schema_version":"akerpuls-merge-blind-audit-reveal-analysis-freeze-v1",
        "status":STATUS,
        "freeze_git_head":head,
        "source_git_head":EXPECTED_SOURCE_GIT_HEAD,
        "parents":{
            "labels_freeze_sha256":EXPECTED_LABEL_FREEZE_SHA256,
            "labels_sha256":EXPECTED_LABELS_SHA256,
            "blind_key_sha256":EXPECTED_BLIND_KEY_SHA256,
        },
        "source_hashes":{
            "summary_sha256":v["summary_sha256"],
            "join_sha256":v["join_sha256"],
            "contrasts_sha256":v["contrasts_sha256"],
            "strata_sha256":v["strata_sha256"],
            "source_manifest_sha256":v["source_manifest_sha256"],
        },
        "by_stratum":v["summary"]["by_stratum"],
        "predeclared_contrasts":v["summary"]["predeclared_contrasts"],
        "interpretation_limits":v["summary"]["interpretation_limits"],
        "contract":{
            "analysis_frozen_before_fusion_decision":True,
            "fusion_executed":False,
            "fusion_score_created":False,
            "fusion_weight_selected":False,
            "sign_selected":False,
            "thresholds_tuned":False,
            "automatic_merge":False,
            "geometry_mutated":False,
        },
        "next":"DECIDE_M1_ROLE_FROM_FROZEN_REVEAL_RESULTS",
    }

    out.mkdir(parents=True,exist_ok=False)
    fp=out/"AKERPULS_MERGE_BLIND_AUDIT_REVEAL_ANALYSIS_FREEZE_V1.json"
    fp.write_text(json.dumps(freeze,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    fsha=sha256_file(fp)
    (out/"AKERPULS_MERGE_BLIND_AUDIT_REVEAL_ANALYSIS_FREEZE_V1.sha256").write_text(
        fsha+"  AKERPULS_MERGE_BLIND_AUDIT_REVEAL_ANALYSIS_FREEZE_V1.json\n",encoding="utf-8"
    )
    shutil.copyfile(src/"SHA256_MANIFEST.txt",out/"SOURCE_REVEAL_SHA256_MANIFEST.txt")

    print("AKERPULS MERGE BLIND AUDIT REVEAL ANALYSIS FORMAL FREEZE")
    print(f"STATUS={STATUS}")
    print(f"SOURCE_GIT_HEAD={EXPECTED_SOURCE_GIT_HEAD}")
    print(f"FREEZE_GIT_HEAD={head}")
    print(f"LABELS_FREEZE_SHA256={EXPECTED_LABEL_FREEZE_SHA256}")
    print(f"BLIND_KEY_SHA256={EXPECTED_BLIND_KEY_SHA256}")
    print(f"REVEAL_ANALYSIS_FREEZE_SHA256={fsha}")
    print(f"SUMMARY_SHA256={EXPECTED_SUMMARY_SHA256}")
    print(f"JOIN_SHA256={EXPECTED_JOIN_SHA256}")
    print("HH_STRICT=0.640000 HH_BROAD=0.880000")
    print("HL_STRICT=0.280000 HL_BROAD=0.560000")
    print("LH_STRICT=0.000000 LH_BROAD=0.041667")
    print("LL_STRICT=0.000000 LL_BROAD=0.080000")
    print("HH_VS_HL_STRICT_RD=0.360000 P=0.022241296")
    print("HH_VS_HL_BROAD_RD=0.320000 P=0.025476633")
    print("FUSION_EXECUTED=FALSE SIGN_SELECTED=FALSE THRESHOLDS_TUNED=FALSE")
    print("AUTOMATIC_MERGE=FALSE GEOMETRY_MUTATED=FALSE")
    print("NEXT=DECIDE_M1_ROLE_FROM_FROZEN_REVEAL_RESULTS")
    print(f"OUTPUT={out}")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
