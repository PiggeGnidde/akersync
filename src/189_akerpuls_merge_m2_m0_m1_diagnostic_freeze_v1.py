#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Formal freeze of the descriptive M2 comparison between frozen M0 and M1.

This stage verifies and freezes the already-completed diagnostic. It performs no
new comparison, fusion, sign choice, human-label analysis, threshold tuning,
automatic merge or geometry mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
EXPECTED_SOURCE_GIT_HEAD = "2762f33752bb06a9b0e46426b224dccd6757bf65"

SOURCE_DIR = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m2_m0_m1_diagnostic_v1")
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m2_m0_m1_diagnostic_freeze_v1")
STATUS = "FROZEN_AKERPULS_MERGE_M2_M0_M1_DIAGNOSTIC_V1"

EXPECTED_M0_FREEZE_SHA256 = "fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051"
EXPECTED_M1_FREEZE_SHA256 = "5d39f6fea78260bd46cfa2aa99f8043abb02f1f67f57b73a9e30ae7273d9c20f"
EXPECTED_JOIN_PARQUET_SHA256 = "e4cfed6a9e2488a91eeaeea5535492d040ff972287b62bdb07fad702fba7137d"
EXPECTED_SUMMARY_SHA256 = "98c25b7c3a72282557e81f9b653f47336c71d798af75d4f649e158959c88b8d4"

EXPECTED_PAIRS = 27146
EXPECTED_ASSESSABLE = 22358
EXPECTED_STATUS_COUNTS = {"MERGE_CANDIDATE": 2398, "KEEP_BOUNDARY": 19960, "UNCERTAIN": 4788}

EXPECTED = {
    "p_samecrop_spearman": 0.275425,
    "js_similarity_spearman": 0.287809,
    "probability_overlap_spearman": 0.285985,
    "top1_prob_product_spearman": 0.134569,
    "entropy_mean_spearman": -0.111011,
    "valid_history_years_min_spearman": -0.028966,
    "candidate_top1_same_rate": 0.565888,
    "keep_top1_same_rate": 0.271493,
    "uncertain_top1_same_rate": 0.296366,
    "candidate_p_same_p50": 0.234514,
    "keep_p_same_p50": 0.089193,
    "uncertain_p_same_p50": 0.107105,
    "tail90_both": 433,
    "tail90_jaccard": 0.107205,
    "tail95_both": 93,
    "tail95_jaccard": 0.043397,
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def close(a, b, tol=5e-7):
    return abs(float(a) - float(b)) <= tol


def verify_source(src: Path) -> dict:
    summary_path = src / "M2_M0_M1_DIAGNOSTIC_SUMMARY_V1.json"
    join_path = src / "M2_M0_M1_DIAGNOSTIC_JOIN.parquet"
    decile_path = src / "M2_M1_P_SAMECROP_DECILES.csv"
    ctab_path = src / "M2_ASSESSABLE_M0_M1_DECILE_CROSSTAB.csv"
    manifest_path = src / "SHA256_MANIFEST.txt"
    for p in (summary_path, join_path, decile_path, ctab_path, manifest_path):
        if not p.is_file():
            raise FileNotFoundError(p)

    if sha256_file(summary_path) != EXPECTED_SUMMARY_SHA256:
        raise RuntimeError("M2 summary SHA changed")
    if sha256_file(join_path) != EXPECTED_JOIN_PARQUET_SHA256:
        raise RuntimeError("M2 joined Parquet SHA changed")

    s = load_json(summary_path)
    if s.get("status") != "PASS_M2_M0_M1_DIAGNOSTIC_STOP":
        raise RuntimeError(f"Unexpected M2 source status: {s.get('status')}")
    if s.get("git_head") != EXPECTED_SOURCE_GIT_HEAD:
        raise RuntimeError(f"Unexpected M2 source git head: {s.get('git_head')}")

    parents = s.get("parents", {})
    if parents.get("m0_freeze_sha256") != EXPECTED_M0_FREEZE_SHA256:
        raise RuntimeError("M2 M0 parent freeze changed")
    if parents.get("m1_freeze_sha256") != EXPECTED_M1_FREEZE_SHA256:
        raise RuntimeError("M2 M1 parent freeze changed")

    census = s.get("census", {})
    if int(census.get("pairs", -1)) != EXPECTED_PAIRS:
        raise RuntimeError("M2 pair census changed")
    if int(census.get("assessable", -1)) != EXPECTED_ASSESSABLE:
        raise RuntimeError("M2 assessable census changed")
    if census.get("m0_status_counts") != EXPECTED_STATUS_COUNTS:
        raise RuntimeError("M2 M0-status census changed")

    corr = s.get("association_assessable_only", {})
    corr_checks = {
        "p_samecrop": EXPECTED["p_samecrop_spearman"],
        "js_similarity_01": EXPECTED["js_similarity_spearman"],
        "probability_overlap_mass": EXPECTED["probability_overlap_spearman"],
        "top1_prob_product": EXPECTED["top1_prob_product_spearman"],
        "entropy_mean": EXPECTED["entropy_mean_spearman"],
        "valid_history_years_min": EXPECTED["valid_history_years_min_spearman"],
    }
    for key, expected in corr_checks.items():
        got = corr.get(key, {}).get("spearman_with_satellite_merge_score")
        if got is None or not close(got, expected):
            raise RuntimeError(f"M2 correlation changed for {key}: {got}")

    by = s.get("m1_descriptive_by_m0_status", {})
    checks = [
        ("MERGE_CANDIDATE", "top1_same_rate", EXPECTED["candidate_top1_same_rate"]),
        ("KEEP_BOUNDARY", "top1_same_rate", EXPECTED["keep_top1_same_rate"]),
        ("UNCERTAIN", "top1_same_rate", EXPECTED["uncertain_top1_same_rate"]),
    ]
    for status, key, expected in checks:
        got = by.get(status, {}).get(key)
        if got is None or not close(got, expected):
            raise RuntimeError(f"M2 descriptive changed: {status}/{key}={got}")
    p50checks = [
        ("MERGE_CANDIDATE", EXPECTED["candidate_p_same_p50"]),
        ("KEEP_BOUNDARY", EXPECTED["keep_p_same_p50"]),
        ("UNCERTAIN", EXPECTED["uncertain_p_same_p50"]),
    ]
    for status, expected in p50checks:
        got = by.get(status, {}).get("p_samecrop", {}).get("p50")
        if got is None or not close(got, expected):
            raise RuntimeError(f"M2 p_samecrop median changed: {status}={got}")

    tails = s.get("fixed_rank_tail_overlap_assessable_only", {})
    t90 = tails.get("0.9", {})
    t95 = tails.get("0.95", {})
    if int(t90.get("both_high_n", -1)) != EXPECTED["tail90_both"] or not close(t90.get("jaccard_high_sets"), EXPECTED["tail90_jaccard"]):
        raise RuntimeError("M2 P90 tail-overlap diagnostic changed")
    if int(t95.get("both_high_n", -1)) != EXPECTED["tail95_both"] or not close(t95.get("jaccard_high_sets"), EXPECTED["tail95_jaccard"]):
        raise RuntimeError("M2 P95 tail-overlap diagnostic changed")

    guards = s.get("guards", {})
    for k in ("fusion_executed", "fusion_score_created", "sign_selected", "human_labels_used", "thresholds_tuned", "automatic_merge", "geometry_mutated"):
        if guards.get(k) is not False:
            raise RuntimeError(f"M2 guard changed: {k}={guards.get(k)}")

    return {
        "summary_sha256": sha256_file(summary_path),
        "join_parquet_sha256": sha256_file(join_path),
        "deciles_csv_sha256": sha256_file(decile_path),
        "decile_crosstab_csv_sha256": sha256_file(ctab_path),
        "source_manifest_sha256": sha256_file(manifest_path),
        "summary": s,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-dir", default=str(SOURCE_DIR))
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    head = git_guard()
    src = Path(args.source_dir)
    out = Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Freeze output already exists: {out}")

    verified = verify_source(src)
    s = verified["summary"]

    freeze = {
        "schema_version": "akerpuls-merge-m2-m0-m1-diagnostic-freeze-v1",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "freeze_git_head": head,
        "source_git_head": EXPECTED_SOURCE_GIT_HEAD,
        "parents": {
            "m0_freeze_sha256": EXPECTED_M0_FREEZE_SHA256,
            "m1_freeze_sha256": EXPECTED_M1_FREEZE_SHA256,
        },
        "source_hashes": {
            "summary_sha256": verified["summary_sha256"],
            "join_parquet_sha256": verified["join_parquet_sha256"],
            "deciles_csv_sha256": verified["deciles_csv_sha256"],
            "decile_crosstab_csv_sha256": verified["decile_crosstab_csv_sha256"],
            "source_manifest_sha256": verified["source_manifest_sha256"],
        },
        "census": s["census"],
        "association_assessable_only": s["association_assessable_only"],
        "m1_descriptive_by_m0_status": s["m1_descriptive_by_m0_status"],
        "fixed_rank_tail_overlap_assessable_only": s["fixed_rank_tail_overlap_assessable_only"],
        "interpretation_limits": s["interpretation_limits"],
        "contract": {
            "diagnostic_only": True,
            "fusion_executed": False,
            "fusion_score_created": False,
            "sign_selected": False,
            "human_labels_used": False,
            "thresholds_tuned": False,
            "automatic_merge": False,
            "geometry_mutated": False,
        },
        "next": "BUILD_PREDECLARED_BLIND_100_PAIR_MERGE_BOUNDARY_AUDIT_ACROSS_M0_M1_DISAGREEMENT_STRATA",
    }

    out.mkdir(parents=True, exist_ok=False)
    freeze_path = out / "AKERPULS_MERGE_M2_M0_M1_DIAGNOSTIC_FREEZE_V1.json"
    freeze_path.write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    freeze_sha = sha256_file(freeze_path)
    (out / "AKERPULS_MERGE_M2_M0_M1_DIAGNOSTIC_FREEZE_V1.sha256").write_text(
        freeze_sha + "  AKERPULS_MERGE_M2_M0_M1_DIAGNOSTIC_FREEZE_V1.json\n", encoding="utf-8"
    )
    shutil.copyfile(src / "SHA256_MANIFEST.txt", out / "SOURCE_M2_SHA256_MANIFEST.txt")

    print("AKERPULS MERGE M2 M0-vs-M1 DIAGNOSTIC FORMAL FREEZE")
    print(f"STATUS={STATUS}")
    print(f"SOURCE_GIT_HEAD={EXPECTED_SOURCE_GIT_HEAD}")
    print(f"FREEZE_GIT_HEAD={head}")
    print(f"M0_FREEZE_SHA256={EXPECTED_M0_FREEZE_SHA256}")
    print(f"M1_FREEZE_SHA256={EXPECTED_M1_FREEZE_SHA256}")
    print(f"M2_DIAGNOSTIC_FREEZE_SHA256={freeze_sha}")
    print(f"PAIRS={EXPECTED_PAIRS} ASSESSABLE={EXPECTED_ASSESSABLE}")
    print(f"P_SAMECROP_SPEARMAN_WITH_M0={EXPECTED['p_samecrop_spearman']:.6f}")
    print(f"P90_TAIL_BOTH={EXPECTED['tail90_both']} JACCARD={EXPECTED['tail90_jaccard']:.6f}")
    print(f"P95_TAIL_BOTH={EXPECTED['tail95_both']} JACCARD={EXPECTED['tail95_jaccard']:.6f}")
    print("FUSION_EXECUTED=FALSE SIGN_SELECTED=FALSE HUMAN_LABELS_USED=FALSE THRESHOLDS_TUNED=FALSE")
    print("AUTOMATIC_MERGE=FALSE GEOMETRY_MUTATED=FALSE")
    print("NEXT=BUILD_PREDECLARED_BLIND_100_PAIR_MERGE_BOUNDARY_AUDIT_ACROSS_M0_M1_DISAGREEMENT_STRATA")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
