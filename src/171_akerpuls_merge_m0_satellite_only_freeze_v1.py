#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Formal freeze of ÅkerPuls Merge M0 satellite-only full-Skåne result.

This stage verifies and freezes the already-completed M0 result. It does NOT rerun
satellite analysis and does NOT load ÅkerMinne/M4. The purpose is to establish an
immutable baseline before any pair prior or fusion is calculated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DEFAULT = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_v1")
OUT_DEFAULT = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_freeze_v1")
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
EXPECTED_SOURCE_GIT_HEAD = "f93964d6460b813ff90e6139b9c58b0e579aba52"
EXPECTED_PARENT_PRELIM_FREEZE = "c2f4fd7ee03124f330d3a06a1d1465592399072ed5729a38e5a66ac27dcef376"
EXPECTED_OFFICIAL_GEOM_SHA = "63f256c012a8f8aab75f22699bc729e60036913429caeb070306f57c19b31706"
EXPECTED_VRT_INDEX_SHA = "0210f78b9780f6b586be0c89109e5a696202167b5283d5bae6b20a24d23c8979"
SOURCE_STATUS = "PASS_TO_M0_SATELLITE_MERGE_REVIEW_STOP"
FREEZE_STATUS = "FROZEN_AKERPULS_MERGE_M0_SATELLITE_ONLY_V1"

EXPECTED = {
    "same_block_touching_pairs": 27146,
    "assessable_pairs": 22358,
    "merge_candidate": 2398,
    "keep_boundary": 19960,
    "uncertain": 4788,
    "cross_analysis_cell_pairs": 348,
}
EXPECTED_Q = {
    "p50": 0.5210865,
    "p90": 0.7905281999999999,
    "p95": 0.8424368,
    "p99": 0.90247635,
}
REQUIRED_OUTPUTS = {
    "m0_satellite_merge_pairs.csv",
    "m0_satellite_merge_boundaries.gpkg",
    "M0_SATELLITE_ONLY_MERGE_SUMMARY_V1.json",
    "M0_SATELLITE_ONLY_MERGE_REPORT_V1.md",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def verify_source(source: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest_path = source / "m0_satellite_merge_manifest.json"
    summary_path = source / "M0_SATELLITE_ONLY_MERGE_SUMMARY_V1.json"
    csv_path = source / "m0_satellite_merge_pairs.csv"
    gpkg_path = source / "m0_satellite_merge_boundaries.gpkg"
    report_path = source / "M0_SATELLITE_ONLY_MERGE_REPORT_V1.md"
    for p in (manifest_path, summary_path, csv_path, gpkg_path, report_path):
        if not p.is_file():
            raise FileNotFoundError(p)

    manifest = read_json(manifest_path)
    if manifest.get("schema_version") != "akerpuls-merge-m0-satellite-only-manifest-v1":
        raise RuntimeError("Unexpected M0 source manifest schema")
    if manifest.get("status") != SOURCE_STATUS:
        raise RuntimeError(f"Unexpected M0 source status {manifest.get('status')}")
    if manifest.get("git_head") != EXPECTED_SOURCE_GIT_HEAD:
        raise RuntimeError(f"M0 source git head changed: {manifest.get('git_head')}")
    if manifest.get("history_prior_used") is not False or manifest.get("m4_prior_used") is not False:
        raise RuntimeError("M0 source unexpectedly used history/M4")
    if manifest.get("fusion_used") is not False or manifest.get("automatic_merge") is not False or manifest.get("geometry_mutation") is not False:
        raise RuntimeError("M0 source guard changed")

    hashes = manifest.get("output_hashes", {})
    if set(hashes) != REQUIRED_OUTPUTS:
        raise RuntimeError(f"M0 source output set changed: {sorted(hashes)}")
    for name, rec in hashes.items():
        p = source / rec.get("relative_path", name)
        if not p.is_file():
            raise FileNotFoundError(p)
        if sha256_file(p) != rec.get("sha256") or int(p.stat().st_size) != int(rec.get("bytes", -1)):
            raise RuntimeError(f"M0 frozen-source artifact changed: {name}")

    summary = read_json(summary_path)
    if summary.get("status") != SOURCE_STATUS:
        raise RuntimeError("M0 summary status changed")
    if summary.get("git_head") != EXPECTED_SOURCE_GIT_HEAD:
        raise RuntimeError("M0 summary git head changed")
    if summary.get("parent_preliminary_geometry_v1_freeze_sha256") != EXPECTED_PARENT_PRELIM_FREEZE:
        raise RuntimeError("M0 parent preliminary-geometry freeze changed")
    if summary.get("official_2025_geometry_sha256") != EXPECTED_OFFICIAL_GEOM_SHA:
        raise RuntimeError("M0 official geometry lineage changed")
    if summary.get("vrt_index_sha256") != EXPECTED_VRT_INDEX_SHA:
        raise RuntimeError("M0 VRT lineage changed")
    scope = summary.get("scope", {})
    if scope.get("candidate_universe") != "TOUCHING_2025_SKIFTEN_WITHIN_SAME_2025_BLOCK" or scope.get("same_block_only") is not True:
        raise RuntimeError("M0 candidate-universe contract changed")
    if scope.get("satellite_only") is not True or scope.get("history_prior_used") is not False or scope.get("m4_prior_used") is not False or scope.get("fusion_used") is not False:
        raise RuntimeError("M0 source is not pure satellite-only")

    census = summary.get("census", {})
    for k, v in EXPECTED.items():
        if int(census.get(k, -1)) != v:
            raise RuntimeError(f"M0 census changed: {k}={census.get(k)} expected={v}")
    q = summary.get("satellite_score_quantiles_assessable", {})
    for k, v in EXPECTED_Q.items():
        if abs(float(q.get(k, float("nan"))) - v) > 1e-12:
            raise RuntimeError(f"M0 score quantile changed: {k}={q.get(k)} expected={v}")
    guards = summary.get("guards", {})
    required_false = ["network_calls", "history_prior_execution", "m4_prior_execution", "fusion_execution", "thresholds_tuned", "automatic_merge", "official_geometry_replaced", "automatic_geometry_mutation"]
    if any(guards.get(k) is not False for k in required_false):
        raise RuntimeError("M0 summary guard changed")

    df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype={"field_a": str, "field_b": str})
    if len(df) != EXPECTED["same_block_touching_pairs"]:
        raise RuntimeError(f"M0 CSV row count changed: {len(df)}")
    if not {"field_a", "field_b", "m0_status", "satellite_merge_score"}.issubset(df.columns):
        raise RuntimeError("M0 CSV schema missing required columns")
    key = df.field_a.astype(str) + "||" + df.field_b.astype(str)
    if key.duplicated().any():
        raise RuntimeError("M0 CSV has duplicate pair keys")
    counts = df.m0_status.astype(str).value_counts().to_dict()
    expected_counts = {
        "MERGE_CANDIDATE": EXPECTED["merge_candidate"],
        "KEEP_BOUNDARY": EXPECTED["keep_boundary"],
        "UNCERTAIN": EXPECTED["uncertain"],
    }
    if counts != expected_counts:
        raise RuntimeError(f"M0 CSV status counts changed: {counts}")

    source_hashes = {
        "source_manifest_sha256": sha256_file(manifest_path),
        "source_summary_sha256": sha256_file(summary_path),
        "source_pairs_csv_sha256": sha256_file(csv_path),
        "source_boundaries_gpkg_sha256": sha256_file(gpkg_path),
        "source_report_sha256": sha256_file(report_path),
    }
    return manifest, summary, source_hashes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-dir", default=str(SOURCE_DEFAULT))
    ap.add_argument("--output-dir", default=str(OUT_DEFAULT))
    args = ap.parse_args()
    head = git_guard()
    source = Path(args.source_dir)
    out = Path(args.output_dir)

    print("MERGE_M0_FREEZE_PROGRESS=VERIFY_EXACT_SATELLITE_ONLY_SOURCE", flush=True)
    _manifest, _summary, source_hashes = verify_source(source)

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=False)

    freeze = {
        "schema_version": "akerpuls-merge-m0-satellite-only-freeze-v1",
        "status": FREEZE_STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "freeze_git_head": head,
        "source_git_head": EXPECTED_SOURCE_GIT_HEAD,
        "parent_preliminary_geometry_v1_freeze_sha256": EXPECTED_PARENT_PRELIM_FREEZE,
        "official_2025_geometry_sha256": EXPECTED_OFFICIAL_GEOM_SHA,
        "vrt_index_sha256": EXPECTED_VRT_INDEX_SHA,
        "source_hashes": source_hashes,
        "census": dict(EXPECTED),
        "satellite_score_quantiles_assessable": dict(EXPECTED_Q),
        "candidate_rate_among_assessable": EXPECTED["merge_candidate"] / EXPECTED["assessable_pairs"],
        "candidate_rate_all_pairs": EXPECTED["merge_candidate"] / EXPECTED["same_block_touching_pairs"],
        "uncertain_rate_all_pairs": EXPECTED["uncertain"] / EXPECTED["same_block_touching_pairs"],
        "contract": {
            "candidate_universe": "TOUCHING_2025_SKIFTEN_WITHIN_SAME_2025_BLOCK",
            "satellite_only": True,
            "history_prior_used": False,
            "m4_prior_used": False,
            "fusion_used": False,
            "thresholds_tuned": False,
            "automatic_merge": False,
            "geometry_mutation": False,
            "candidate_is_review_only_not_adopted_merge": True,
        },
        "next": "M1_AKERMINNE_M4_PAIR_PRIOR_ON_EXACT_FROZEN_M0_PAIR_UNIVERSE",
    }
    freeze_path = out / "AKERPULS_MERGE_M0_SATELLITE_ONLY_FREEZE_V1.json"
    write_json(freeze_path, freeze)
    freeze_sha = sha256_file(freeze_path)

    manifest = {
        "schema_version": "akerpuls-merge-m0-satellite-only-freeze-manifest-v1",
        "status": FREEZE_STATUS,
        "freeze_sha256": freeze_sha,
        "source_hashes": source_hashes,
        "next": freeze["next"],
    }
    write_json(out / "akerpuls_merge_m0_satellite_only_freeze_manifest.json", manifest)

    print("AKERPULS MERGE M0 SATELLITE-ONLY FREEZE")
    print(f"STATUS={FREEZE_STATUS}")
    print(f"SOURCE_GIT_HEAD={EXPECTED_SOURCE_GIT_HEAD}")
    print(f"SAME_BLOCK_TOUCHING_PAIRS={EXPECTED['same_block_touching_pairs']} ASSESSABLE={EXPECTED['assessable_pairs']}")
    print(f"MERGE_CANDIDATE={EXPECTED['merge_candidate']} KEEP_BOUNDARY={EXPECTED['keep_boundary']} UNCERTAIN={EXPECTED['uncertain']}")
    print(f"CANDIDATE_RATE_ASSESSABLE={EXPECTED['merge_candidate']/EXPECTED['assessable_pairs']:.6f} CANDIDATE_RATE_ALL={EXPECTED['merge_candidate']/EXPECTED['same_block_touching_pairs']:.6f}")
    print(f"M0_FREEZE_SHA256={freeze_sha}")
    print("HISTORY_PRIOR_USED=FALSE M4_PRIOR_USED=FALSE FUSION_USED=FALSE THRESHOLDS_TUNED=FALSE")
    print("AUTOMATIC_MERGE=FALSE GEOMETRY_MUTATION=FALSE")
    print("NEXT=M1_AKERMINNE_M4_PAIR_PRIOR_ON_EXACT_FROZEN_M0_PAIR_UNIVERSE")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
