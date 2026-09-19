#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Formal freeze of ÅkerPuls Merge M1 M4 pair-prior V1B.

Freezes the already-generated independent history/context pair features on the
exact frozen 27,146 M0 pair universe. This stage does NOT read M0 satellite
scores/status and does NOT perform fusion, label analysis, threshold tuning,
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

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
EXPECTED_SOURCE_GIT_HEAD = "7741eecd6500265e8476f65894e3aa85d5b45255"

SOURCE_DIR = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m1_m4_pair_prior_v1b")
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m1_m4_pair_prior_freeze_v1")
STATUS = "FROZEN_AKERPULS_MERGE_M1_M4_PAIR_PRIOR_V1"

EXPECTED_M0_FREEZE_SHA256 = "fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051"
EXPECTED_M4_FREEZE_SHA256 = "61766d03b238d792c773664d40493b184a69823f984f3b7915185dbcda330f95"

EXPECTED_PARQUET_SHA256 = "a2e6c2d091ad3b71b9112dea2627704c2d966fdb178a295db6af66df0c55a9f4"
EXPECTED_CSV_GZ_SHA256 = "7ba95180ff0c08a40af60ddd52e0ccd7fe97afa4e790f2c0e462dddef4a4c27e"
EXPECTED_SUMMARY_SHA256 = "a639d1acf7e761ce99053195387ef50878020be951f6689cc4e8f0590d532520"

EXPECTED_PAIRS = 27146
EXPECTED_TOP1_SAME = 8195
EXPECTED_TOP3_OVERLAP_COUNTS = {0: 8257, 1: 6151, 2: 7686, 3: 5052}


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


def verify_source(src: Path) -> dict:
    parquet = src / "M1_M4_PAIR_PRIOR.parquet"
    csv_gz = src / "M1_M4_PAIR_PRIOR.csv.gz"
    summary_path = src / "M1_M4_PAIR_PRIOR_SUMMARY_V1.json"
    manifest_path = src / "SHA256_MANIFEST.txt"
    for p in (parquet, csv_gz, summary_path, manifest_path):
        if not p.is_file():
            raise FileNotFoundError(p)

    checks = {
        "M1_M4_PAIR_PRIOR.parquet": (parquet, EXPECTED_PARQUET_SHA256),
        "M1_M4_PAIR_PRIOR.csv.gz": (csv_gz, EXPECTED_CSV_GZ_SHA256),
        "M1_M4_PAIR_PRIOR_SUMMARY_V1.json": (summary_path, EXPECTED_SUMMARY_SHA256),
    }
    hashes = {}
    for name, (path, expected) in checks.items():
        got = sha256_file(path)
        if got != expected:
            raise RuntimeError(f"M1 source artefact SHA changed for {name}: {got}")
        hashes[name] = got

    summary = load_json(summary_path)
    if summary.get("status") != "PASS_TO_M1_M4_PAIR_PRIOR_V1B_FREEZE_REVIEW":
        raise RuntimeError(f"Unexpected M1 source status: {summary.get('status')}")
    if summary.get("git_head") != EXPECTED_SOURCE_GIT_HEAD:
        raise RuntimeError(f"Unexpected M1 source git head: {summary.get('git_head')}")

    pu = summary.get("pair_universe", {})
    if pu.get("definition") != "EXACT_FROZEN_M0_27146_PAIR_UNIVERSE":
        raise RuntimeError("M1 pair-universe definition changed")
    if int(pu.get("pairs", -1)) != EXPECTED_PAIRS:
        raise RuntimeError("M1 pair census changed")
    if pu.get("m0_freeze_sha256") != EXPECTED_M0_FREEZE_SHA256:
        raise RuntimeError("M1 does not pin the expected M0 freeze")
    if pu.get("m0_id_schema") != "2025|BLOCKID|SKIFTESBETECKNING":
        raise RuntimeError("Unexpected M0 field-ID schema")
    if pu.get("m4_id_schema") != "BLOCKID|SKIFTESBETECKNING":
        raise RuntimeError("Unexpected M4 field-ID schema")
    if pu.get("id_namespace_bridge") != "strip exact leading 2025| from frozen M0/D2A IDs to match ÅkerMinne/M4 current_field_id":
        raise RuntimeError("M1 ID namespace bridge changed")

    m4 = summary.get("m4_prior", {})
    if m4.get("m4_2026_prior_freeze_sha256") != EXPECTED_M4_FREEZE_SHA256:
        raise RuntimeError("M1 does not pin the expected M4 2026 prior freeze")
    if int(m4.get("target_year", -1)) != 2026 or int(m4.get("fields", -1)) != 128636 or int(m4.get("classes", -1)) != 16:
        raise RuntimeError("M1 M4-prior population/target contract changed")

    desc = summary.get("descriptive_only", {})
    if int(desc.get("top1_same_count", -1)) != EXPECTED_TOP1_SAME:
        raise RuntimeError("M1 top1-same census changed")
    got_top3 = {int(k): int(v) for k, v in desc.get("top3_overlap_counts", {}).items()}
    if got_top3 != EXPECTED_TOP3_OVERLAP_COUNTS:
        raise RuntimeError(f"M1 top3-overlap census changed: {got_top3}")

    guards = summary.get("guards", {})
    required_false = [
        "m0_satellite_features_read", "m0_status_read", "m0_satellite_score_read",
        "merge_label_used", "fusion_executed", "sign_assumption_for_merge",
        "thresholds_tuned", "automatic_merge", "geometry_mutated",
    ]
    if any(guards.get(k) is not False for k in required_false):
        raise RuntimeError(f"M1 independence guard changed: {guards}")

    cols = [
        "pair_key", "field_a_m0", "field_b_m0", "field_a_m4", "field_b_m4",
        "p_samecrop", "js_divergence_natlog", "js_similarity_01",
        "probability_overlap_mass", "top1_same", "top3_overlap_count",
    ]
    df = pd.read_parquet(parquet, columns=cols)
    if len(df) != EXPECTED_PAIRS or df["pair_key"].nunique() != EXPECTED_PAIRS:
        raise RuntimeError("M1 Parquet pair census/uniqueness changed")
    if not bool(df["field_a_m0"].astype(str).str.startswith("2025|").all()):
        raise RuntimeError("M1 field_a_m0 namespace changed")
    if not bool(df["field_b_m0"].astype(str).str.startswith("2025|").all()):
        raise RuntimeError("M1 field_b_m0 namespace changed")
    if not bool((df["field_a_m0"].astype(str).str.slice(5) == df["field_a_m4"].astype(str)).all()):
        raise RuntimeError("M1 A-side ID bridge is not exact prefix stripping")
    if not bool((df["field_b_m0"].astype(str).str.slice(5) == df["field_b_m4"].astype(str)).all()):
        raise RuntimeError("M1 B-side ID bridge is not exact prefix stripping")
    expected_key = df["field_a_m0"].astype(str) + "||" + df["field_b_m0"].astype(str)
    if not bool((expected_key == df["pair_key"].astype(str)).all()):
        raise RuntimeError("M1 pair_key changed")
    if int(df["top1_same"].sum()) != EXPECTED_TOP1_SAME:
        raise RuntimeError("M1 Parquet top1-same census changed")
    got_top3_df = {int(k): int(v) for k, v in df["top3_overlap_count"].value_counts().sort_index().items()}
    if got_top3_df != EXPECTED_TOP3_OVERLAP_COUNTS:
        raise RuntimeError("M1 Parquet top3-overlap census changed")
    if not ((df["p_samecrop"] >= 0) & (df["p_samecrop"] <= 1)).all():
        raise RuntimeError("M1 p_samecrop outside [0,1]")
    if not ((df["js_divergence_natlog"] >= -1e-7) & (df["js_divergence_natlog"] <= np.log(2.0) + 1e-7)).all():
        raise RuntimeError("M1 JS divergence outside [0,ln2]")
    if not ((df["js_similarity_01"] >= -1e-6) & (df["js_similarity_01"] <= 1 + 1e-6)).all():
        raise RuntimeError("M1 JS similarity outside [0,1]")
    if not ((df["probability_overlap_mass"] >= -1e-7) & (df["probability_overlap_mass"] <= 1 + 1e-7)).all():
        raise RuntimeError("M1 probability-overlap mass outside [0,1]")

    return {
        "source_hashes": hashes,
        "source_manifest_sha256": sha256_file(manifest_path),
        "top1_same_count": EXPECTED_TOP1_SAME,
        "top1_same_rate": EXPECTED_TOP1_SAME / EXPECTED_PAIRS,
        "top3_overlap_counts": {str(k): v for k, v in EXPECTED_TOP3_OVERLAP_COUNTS.items()},
        "p_samecrop_quantiles": desc.get("p_samecrop_quantiles"),
        "js_divergence_quantiles": desc.get("js_divergence_quantiles"),
        "js_similarity_quantiles": desc.get("js_similarity_quantiles"),
        "probability_overlap_mass_quantiles": desc.get("probability_overlap_mass_quantiles"),
        "entropy_mean_quantiles": desc.get("entropy_mean_quantiles"),
        "valid_history_years_min_quantiles": desc.get("valid_history_years_min_quantiles"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-dir", default=str(SOURCE_DIR))
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    freeze_git_head = git_guard()
    src = Path(args.source_dir)
    out = Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Freeze output already exists: {out}")

    verified = verify_source(src)

    freeze = {
        "schema_version": "akerpuls-merge-m1-m4-pair-prior-freeze-v1",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "freeze_git_head": freeze_git_head,
        "source_git_head": EXPECTED_SOURCE_GIT_HEAD,
        "source_dir": str(src),
        "parent_freezes": {
            "m0_satellite_only_freeze_sha256": EXPECTED_M0_FREEZE_SHA256,
            "m4_2026_prior_freeze_sha256": EXPECTED_M4_FREEZE_SHA256,
        },
        "source_hashes": verified["source_hashes"],
        "source_manifest_sha256": verified["source_manifest_sha256"],
        "pair_universe": {
            "pairs": EXPECTED_PAIRS,
            "definition": "EXACT_FROZEN_M0_27146_PAIR_UNIVERSE",
            "m0_id_schema": "2025|BLOCKID|SKIFTESBETECKNING",
            "m4_id_schema": "BLOCKID|SKIFTESBETECKNING",
            "id_bridge": "STRIP_EXACT_LEADING_2025_PIPE",
        },
        "descriptive_only": {
            "top1_same_count": verified["top1_same_count"],
            "top1_same_rate": verified["top1_same_rate"],
            "top3_overlap_counts": verified["top3_overlap_counts"],
            "p_samecrop_quantiles": verified["p_samecrop_quantiles"],
            "js_divergence_quantiles": verified["js_divergence_quantiles"],
            "js_similarity_quantiles": verified["js_similarity_quantiles"],
            "probability_overlap_mass_quantiles": verified["probability_overlap_mass_quantiles"],
            "entropy_mean_quantiles": verified["entropy_mean_quantiles"],
            "valid_history_years_min_quantiles": verified["valid_history_years_min_quantiles"],
        },
        "contract": {
            "history_context_only": True,
            "m0_satellite_features_read": False,
            "m0_status_read": False,
            "m0_satellite_score_read": False,
            "merge_label_used": False,
            "fusion_executed": False,
            "sign_assumption_for_merge": False,
            "thresholds_tuned": False,
            "automatic_merge": False,
            "geometry_mutated": False,
            "candidate_or_merge_decision_created": False,
        },
        "next": "M2_DIAGNOSTIC_COMPARE_FROZEN_M0_AND_M1_WITHOUT_RETUNING_OR_AUTOMATIC_MERGE",
    }

    out.mkdir(parents=True, exist_ok=False)
    freeze_path = out / "AKERPULS_MERGE_M1_M4_PAIR_PRIOR_FREEZE_V1.json"
    freeze_path.write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    freeze_sha = sha256_file(freeze_path)
    (out / "AKERPULS_MERGE_M1_M4_PAIR_PRIOR_FREEZE_V1.sha256").write_text(
        freeze_sha + "  AKERPULS_MERGE_M1_M4_PAIR_PRIOR_FREEZE_V1.json\n", encoding="utf-8"
    )
    shutil.copyfile(src / "SHA256_MANIFEST.txt", out / "SOURCE_M1_SHA256_MANIFEST.txt")

    print("AKERPULS MERGE M1 M4 PAIR PRIOR FORMAL FREEZE")
    print(f"STATUS={STATUS}")
    print(f"SOURCE_GIT_HEAD={EXPECTED_SOURCE_GIT_HEAD}")
    print(f"FREEZE_GIT_HEAD={freeze_git_head}")
    print(f"M0_FREEZE_SHA256={EXPECTED_M0_FREEZE_SHA256}")
    print(f"M4_2026_PRIOR_FREEZE_SHA256={EXPECTED_M4_FREEZE_SHA256}")
    print(f"M1_PAIR_PRIOR_FREEZE_SHA256={freeze_sha}")
    print(f"PAIRS={EXPECTED_PAIRS} TOP1_SAME={EXPECTED_TOP1_SAME} RATE={EXPECTED_TOP1_SAME/EXPECTED_PAIRS:.6f}")
    print("TOP3_OVERLAP_COUNTS=" + " | ".join(f"{k}:{v}" for k, v in EXPECTED_TOP3_OVERLAP_COUNTS.items()))
    print(f"PARQUET_SHA256={EXPECTED_PARQUET_SHA256}")
    print(f"CSV_GZ_SHA256={EXPECTED_CSV_GZ_SHA256}")
    print(f"SUMMARY_SHA256={EXPECTED_SUMMARY_SHA256}")
    print("M0_SATELLITE_FEATURES_READ=FALSE M0_STATUS_READ=FALSE M0_SCORE_READ=FALSE")
    print("FUSION_EXECUTED=FALSE SIGN_ASSUMPTION_FOR_MERGE=FALSE THRESHOLDS_TUNED=FALSE")
    print("AUTOMATIC_MERGE=FALSE GEOMETRY_MUTATED=FALSE")
    print("NEXT=M2_DIAGNOSTIC_COMPARE_FROZEN_M0_AND_M1_WITHOUT_RETUNING_OR_AUTOMATIC_MERGE")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
