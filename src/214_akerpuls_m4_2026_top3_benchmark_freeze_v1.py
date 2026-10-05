#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Formal freeze of the prospective ÅkerMinne/M4 Top-3 crop benchmark for 2026.

The benchmark was produced before official 2026 crop labels were used and
without 2026 Sentinel crop evidence. This freeze does not fit or predict
anything. It verifies and seals the already-built 128636-field Top-3 table.

Primary future benchmark population:
  CLEAN = no split proposal AND no merge proposal.

All fields remain in the sealed table so geometry-change subsets can be studied
separately without changing the original predictions.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"

SOURCE_DIR = Path(r"C:\AkerSyncRepo\work\akerpuls_final_skane_review_map_v1b_cropprior")
SOURCE_MANIFEST = SOURCE_DIR / "AKERPULS_FINAL_SKANE_REVIEW_MAP_V1B_CROPPRIOR_MANIFEST.json"
SOURCE_QA = SOURCE_DIR / "AKERPULS_FINAL_SKANE_REVIEW_MAP_V1B_CROPPRIOR_QA.json"
BENCHMARK_PARQUET = SOURCE_DIR / "AKERMINNE_M4_2026_TOP3_BENCHMARK.parquet"
BENCHMARK_CSV = SOURCE_DIR / "AKERMINNE_M4_2026_TOP3_BENCHMARK.csv.gz"

EXPECTED_SOURCE_GIT_HEAD = "fc81a4cde783a25c5558b977dcce98222682bb7c"
EXPECTED_POLICY_SHA = "52e0e46f1fe07735c510664f67353cc6fa2e7818cbb31e1542688a2f70755394"
EXPECTED_M4_FREEZE_SHA = "61766d03b238d792c773664d40493b184a69823f984f3b7915185dbcda330f95"
EXPECTED_M4_PRIOR_SHA = "c595553436047132bdf280a685add4e123f579722ba353cbd8906ee778c1e3b8"
EXPECTED_ROWS = 128636

DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_m4_2026_top3_benchmark_freeze_v1")
STATUS = "FROZEN_AKERPULS_M4_2026_TOP3_BENCHMARK_V1"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected {EXPECTED_BRANCH}, got {branch}")
    if subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip():
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def verify_source() -> tuple[dict, dict, pd.DataFrame, dict]:
    for p in (SOURCE_MANIFEST, SOURCE_QA, BENCHMARK_PARQUET, BENCHMARK_CSV):
        if not p.is_file():
            raise FileNotFoundError(p)

    m = read_json(SOURCE_MANIFEST)
    q = read_json(SOURCE_QA)

    if m.get("status") != "PASS_TO_FINAL_SKANE_REVIEW_MAP_V1B_CROPPRIOR":
        raise RuntimeError("Unexpected v1b manifest status")
    if m.get("git_head") != EXPECTED_SOURCE_GIT_HEAD:
        raise RuntimeError(f"Unexpected v1b source git head: {m.get('git_head')}")

    parents = m.get("parents", {})
    expected_parents = {
        "proposal_policy_freeze_sha256": EXPECTED_POLICY_SHA,
        "m4_2026_prior_freeze_sha256": EXPECTED_M4_FREEZE_SHA,
        "m4_2026_prior_parquet_sha256": EXPECTED_M4_PRIOR_SHA,
    }
    for k, v in expected_parents.items():
        if parents.get(k) != v:
            raise RuntimeError(f"Parent changed: {k}={parents.get(k)}")

    cc = m.get("crop_prior_contract", {})
    if cc.get("target_year") != 2026 or cc.get("history_through_year") != 2025:
        raise RuntimeError("Crop-prior year contract changed")
    if cc.get("top3_persisted_before_2026_validation") is not True:
        raise RuntimeError("Top-3 was not declared persisted before 2026 validation")
    if cc.get("2026_crop_labels_used") is not False:
        raise RuntimeError("2026 crop labels were used")
    if cc.get("2026_sentinel_used") is not False:
        raise RuntimeError("2026 Sentinel was used in crop prior")
    if "LEGACY_2025_PREFIX_STRIPPED_EXACTLY_ONCE" not in str(cc.get("id_bridge", "")):
        raise RuntimeError("Exact legacy-to-M4 ID bridge is not pinned")

    pol = m.get("policy_lock", {})
    if pol.get("canonical_geometry") != "OFFICIAL_2025_GEOMETRY":
        raise RuntimeError("Canonical geometry policy changed")
    if pol.get("merge_v1_proposal_only") is not True:
        raise RuntimeError("Merge-v1 proposal-only policy changed")
    if pol.get("automatic_boundary_removal") is not False or pol.get("geometry_mutated") is not False:
        raise RuntimeError("Geometry mutation guard changed")

    output_hashes = m.get("output_hashes", {})
    for rel, path in [
        ("AKERMINNE_M4_2026_TOP3_BENCHMARK.parquet", BENCHMARK_PARQUET),
        ("AKERMINNE_M4_2026_TOP3_BENCHMARK.csv.gz", BENCHMARK_CSV),
    ]:
        rec = output_hashes.get(rel)
        if not rec:
            raise RuntimeError(f"Manifest missing output hash for {rel}")
        got = sha(path)
        if rec.get("sha256") != got or int(rec.get("bytes", -1)) != int(path.stat().st_size):
            raise RuntimeError(f"Source output changed: {rel}")

    if q.get("status") != "PASS_TO_FINAL_SKANE_REVIEW_MAP_V1B_CROPPRIOR":
        raise RuntimeError("Unexpected v1b QA status")
    if int(q.get("m4_top3_fields", -1)) != EXPECTED_ROWS:
        raise RuntimeError("QA M4 field census changed")
    if q.get("crop_prior_uses_2026_crop_labels") is not False:
        raise RuntimeError("QA says 2026 labels were used")
    if q.get("crop_prior_uses_2026_sentinel") is not False:
        raise RuntimeError("QA says 2026 Sentinel was used")

    cols = [
        "parent_field_id_2025", "current_field_id",
        "top1_class", "top1_prob", "top2_class", "top2_prob", "top3_class", "top3_prob",
        "entropy", "valid_history_years",
        "split_proposal_touch", "merge_proposal_touch",
        "geometry_change_proposal", "clean_geometry_for_2026_benchmark", "geometry_status",
    ]
    d = pd.read_parquet(BENCHMARK_PARQUET, columns=cols)
    if len(d) != EXPECTED_ROWS:
        raise RuntimeError(f"Benchmark rows changed: {len(d)}")
    if d["current_field_id"].nunique() != EXPECTED_ROWS or d["parent_field_id_2025"].nunique() != EXPECTED_ROWS:
        raise RuntimeError("Benchmark IDs are not one-to-one")
    if d[cols].isna().any().any():
        raise RuntimeError("Benchmark contains nulls")

    for c in ("top1_prob", "top2_prob", "top3_prob"):
        x = pd.to_numeric(d[c], errors="raise")
        if not ((x >= 0.0) & (x <= 1.0)).all():
            raise RuntimeError(f"{c} outside [0,1]")
    if not ((d["top1_prob"] >= d["top2_prob"]) & (d["top2_prob"] >= d["top3_prob"])).all():
        raise RuntimeError("Top-3 probabilities are not nonincreasing")

    if not (d["parent_field_id_2025"].astype(str).str.slice(5) == d["current_field_id"].astype(str)).all():
        raise RuntimeError("Legacy 2025 prefix bridge no longer exact row-by-row")

    clean_expected = ~(d["split_proposal_touch"].astype(bool) | d["merge_proposal_touch"].astype(bool))
    if not (clean_expected == d["clean_geometry_for_2026_benchmark"].astype(bool)).all():
        raise RuntimeError("CLEAN benchmark definition changed")
    if not (d["geometry_change_proposal"].astype(bool) == ~clean_expected).all():
        raise RuntimeError("Geometry-change complement changed")

    counts = {
        "all_fields": int(len(d)),
        "clean_benchmark_fields": int(clean_expected.sum()),
        "geometry_proposal_touched_fields": int((~clean_expected).sum()),
        "split_touched_fields": int(d["split_proposal_touch"].astype(bool).sum()),
        "merge_touched_fields": int(d["merge_proposal_touch"].astype(bool).sum()),
        "split_merge_overlap_fields": int(
            (d["split_proposal_touch"].astype(bool) & d["merge_proposal_touch"].astype(bool)).sum()
        ),
    }
    for k in (
        "clean_benchmark_fields",
        "geometry_proposal_touched_fields",
        "split_touched_fields",
        "merge_touched_fields",
        "split_merge_overlap_fields",
    ):
        if int(q.get(k, -1)) != counts[k]:
            raise RuntimeError(f"QA/benchmark count mismatch: {k}")

    top1_counts = d["top1_class"].astype(str).value_counts().sort_index().to_dict()
    top3_contains_top1 = (d["top1_class"].astype(str) == d["top1_class"].astype(str)).all()
    if not top3_contains_top1:
        raise RuntimeError("Internal Top-3 guard failed")

    return m, q, d, {"counts": counts, "top1_counts": top1_counts}


def main() -> int:
    head = git_guard()
    out = DEFAULT_OUT
    if out.exists():
        raise RuntimeError(f"Freeze output already exists: {out}")

    m, q, d, diag = verify_source()

    parquet_sha = sha(BENCHMARK_PARQUET)
    csv_sha = sha(BENCHMARK_CSV)
    manifest_sha = sha(SOURCE_MANIFEST)
    qa_sha = sha(SOURCE_QA)

    freeze = {
        "schema_version": "akerpuls-m4-2026-top3-benchmark-freeze-v1",
        "status": STATUS,
        "frozen_utc": datetime.now(timezone.utc).isoformat(),
        "freeze_git_head": head,
        "source_git_head": EXPECTED_SOURCE_GIT_HEAD,
        "source_manifest_sha256": manifest_sha,
        "source_qa_sha256": qa_sha,
        "parents": {
            "proposal_policy_freeze_sha256": EXPECTED_POLICY_SHA,
            "m4_2026_prior_freeze_sha256": EXPECTED_M4_FREEZE_SHA,
            "m4_2026_prior_parquet_sha256": EXPECTED_M4_PRIOR_SHA,
        },
        "sealed_prediction_set": {
            "target_year": 2026,
            "rows": EXPECTED_ROWS,
            "benchmark_parquet_sha256": parquet_sha,
            "benchmark_csv_gz_sha256": csv_sha,
            "history_through_year": 2025,
            "2026_crop_labels_used": False,
            "2026_sentinel_used": False,
            "top3_predictions_frozen": True,
            "predictions_may_not_be_retuned_after_future_2026_ground_truth": True,
        },
        "benchmark_populations": {
            **diag["counts"],
            "primary_future_population": "CLEAN_BENCHMARK_FIELDS",
            "clean_definition": "NO_SPLIT_PROPOSAL_AND_NO_MERGE_PROPOSAL",
            "geometry_change_fields_retained_for_separate_analysis": True,
        },
        "future_validation_plan": {
            "A": "OFFICIAL_2026_CROP_INFORMATION",
            "B": "INDEPENDENT_2026_SATELLITE_CROP_DETECTION",
            "B_first_named_case": "RAPESEED__COMPARE_WITH_RAPSKARTAN_STYLE_MODEL",
            "metrics": [
                "TOP1_ACCURACY",
                "TOP3_RECALL",
                "CLASSWISE_PRECISION_RECALL",
                "CONFUSION_MATRIX",
                "MULTICLASS_LOG_LOSS",
                "MULTICLASS_BRIER_SCORE",
                "CALIBRATION",
            ],
            "primary_metrics_should_be_reported_on_clean_population": True,
        },
        "top1_class_counts_all_fields": diag["top1_counts"],
        "guards": {
            "model_fit_executed_in_freeze": False,
            "prediction_executed_in_freeze": False,
            "threshold_tuning_executed_in_freeze": False,
            "geometry_mutated": False,
            "2026_ground_truth_joined": False,
            "2026_satellite_joined": False,
        },
        "next": "WAIT_FOR_INDEPENDENT_2026_GROUND_TRUTH_OR_RUN_PREDECLARED_SATELLITE_VALIDATION_WITHOUT_CHANGING_SEALED_PRIOR",
    }

    out.mkdir(parents=True, exist_ok=False)
    fp = out / "AKERPULS_M4_2026_TOP3_BENCHMARK_FREEZE_V1.json"
    fp.write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fsha = sha(fp)
    (out / "AKERPULS_M4_2026_TOP3_BENCHMARK_FREEZE_V1.sha256").write_text(
        fsha + "  AKERPULS_M4_2026_TOP3_BENCHMARK_FREEZE_V1.json\n", encoding="utf-8"
    )

    print("AKERPULS M4 2026 TOP-3 PROSPECTIVE BENCHMARK FREEZE V1")
    print(f"STATUS={STATUS}")
    print(f"SOURCE_GIT_HEAD={EXPECTED_SOURCE_GIT_HEAD}")
    print(f"FREEZE_GIT_HEAD={head}")
    print(f"SOURCE_MANIFEST_SHA256={manifest_sha}")
    print(f"M4_2026_PRIOR_FREEZE_SHA256={EXPECTED_M4_FREEZE_SHA}")
    print(f"BENCHMARK_PARQUET_SHA256={parquet_sha}")
    print(f"BENCHMARK_CSV_GZ_SHA256={csv_sha}")
    print(f"FIELDS_ALL={diag['counts']['all_fields']}")
    print(f"CLEAN_BENCHMARK_FIELDS={diag['counts']['clean_benchmark_fields']}")
    print(f"GEOMETRY_PROPOSAL_TOUCHED_FIELDS={diag['counts']['geometry_proposal_touched_fields']}")
    print(f"SPLIT_TOUCHED_FIELDS={diag['counts']['split_touched_fields']}")
    print(f"MERGE_TOUCHED_FIELDS={diag['counts']['merge_touched_fields']}")
    print(f"SPLIT_MERGE_OVERLAP_FIELDS={diag['counts']['split_merge_overlap_fields']}")
    print("2026_CROP_LABELS_USED=FALSE 2026_SENTINEL_USED=FALSE")
    print("SEALED_PREDICTIONS_MAY_NOT_BE_RETUNED_AFTER_GROUND_TRUTH=TRUE")
    print("MODEL_FIT_EXECUTED_IN_FREEZE=FALSE PREDICTION_EXECUTED_IN_FREEZE=FALSE")
    print(f"TOP3_BENCHMARK_FREEZE_SHA256={fsha}")
    print("NEXT=WAIT_FOR_2026_GROUND_TRUTH_OR_PREDECLARED_SATELLITE_VALIDATION")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
