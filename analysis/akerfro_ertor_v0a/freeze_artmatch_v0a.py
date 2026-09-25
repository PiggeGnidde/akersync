#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freeze / verify ÅkerFrö ÄrtMatch v0a.

A formal freeze means:
- the locked C6 product policy and anchors validate,
- key scientific lineage + product artifacts are snapshotted,
- SHA-256 hashes are recorded in a manifest,
- VERIFY fails if any frozen source or snapshot changes.

This intentionally does NOT freeze ÄrtKandidat, UI, rotation policy, logistics,
or future water-risk modules.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "akerfro_ertor_v0a.json"
FREEZE_DIR = ROOT / "work" / "akerfro_ertor_v0a" / "freeze_artmatch_v0a"
SNAPSHOT_DIR = FREEZE_DIR / "snapshot"
MANIFEST = FREEZE_DIR / "artmatch_v0a_freeze_manifest.json"

SOURCE_PATHS = [
    Path("config/akerfro_ertor_v0a.json"),
    Path("analysis/akerfro_ertor_v0a/build_artmatch_c6.py"),
    Path("analysis/akerfro_ertor_v0a/residual_texture_c5b.py"),
    Path("data/derived/akerfro_ertor_v0a/artmatch_v0a_fields.parquet"),
    Path("data/derived/akerfro_ertor_v0a/artmatch_v0a_distribution.csv"),
    Path("data/derived/akerfro_ertor_v0a/artmatch_v0a_decile_enrichment.csv"),
    Path("data/derived/akerfro_ertor_v0a/artmatch_v0a_texture_coefficients.csv"),
    Path("data/derived/akerfro_ertor_v0a/artmatch_v0a_summary.json"),
    Path("work/akerfro_ertor_v0a/literature_tiebreak_c4b/c4b_summary.json"),
    Path("work/akerfro_ertor_v0a/residual_texture_c5b/c5b_summary.json"),
    Path("work/akerfro_ertor_v0a/residual_texture_c5b/cv_summary.csv"),
]


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
        ).strip()
    except Exception:
        return "UNKNOWN"


def assert_close(name: str, value: float, lo: float, hi: float) -> None:
    if not (lo <= value <= hi):
        raise RuntimeError(f"{name}: {value} outside frozen range [{lo}, {hi}]")


def validate_contract() -> dict:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    contract = cfg["artmatch_v0a_freeze_contract"]
    policy = cfg["artmatch_v0a_candidate"]

    expected_weights = contract["expected_weights"]
    policy_weights = policy["weights"]
    if policy_weights != expected_weights:
        raise RuntimeError(
            f"Policy weights changed: {policy_weights} != {expected_weights}"
        )

    summary_path = ROOT / "data/derived/akerfro_ertor_v0a/artmatch_v0a_summary.json"
    fields_path = ROOT / "data/derived/akerfro_ertor_v0a/artmatch_v0a_fields.parquet"
    enrichment_path = ROOT / "data/derived/akerfro_ertor_v0a/artmatch_v0a_decile_enrichment.csv"

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    fields = pd.read_parquet(fields_path)
    enrich = pd.read_csv(enrichment_path)

    n_fields = len(fields)
    n_pos = int(fields["is_positive"].sum())
    n_scored = int(fields["artmatch_score"].notna().sum())
    n_insufficient = int(fields["artmatch_status"].eq("INSUFFICIENT_CORE").sum())
    n_pos_scored = int((fields["is_positive"] & fields["artmatch_score"].notna()).sum())

    anchors = {
        "population_fields": n_fields,
        "historical_positive_fields": n_pos,
        "scored_fields": n_scored,
        "insufficient_core_fields": n_insufficient,
        "scored_historical_positive_fields": n_pos_scored,
    }
    expected = {
        "population_fields": int(contract["expected_population_fields"]),
        "historical_positive_fields": int(contract["expected_historical_positive_fields"]),
        "scored_fields": int(contract["expected_scored_fields"]),
        "insufficient_core_fields": int(contract["expected_insufficient_core_fields"]),
        "scored_historical_positive_fields": int(contract["expected_scored_historical_positive_fields"]),
    }
    if anchors != expected:
        raise RuntimeError(f"C6 anchor mismatch: {anchors} != {expected}")

    score = pd.to_numeric(fields["artmatch_score"], errors="coerce").dropna()
    if len(score) and ((score < 0).any() or (score > 100).any()):
        raise RuntimeError("ÄrtMatch score outside locked 0..100 range")

    weights = summary["weights"]
    normalized_summary_weights = {
        "slope": float(weights["slope"]),
        "akerscore": float(weights["akerscore"]),
        "texture_residual": float(weights["texture"]),
    }
    if normalized_summary_weights != expected_weights:
        raise RuntimeError(
            f"C6 summary weights changed: {normalized_summary_weights} != {expected_weights}"
        )

    auc = float(summary["raw_historical_selection_rank_auc"])
    auc_lo, auc_hi = contract["raw_historical_selection_rank_auc_range"]
    assert_close("raw historical-selection rank AUC", auc, float(auc_lo), float(auc_hi))

    twin_acc = float(summary["near_twin_product_pairwise"]["pairwise_accuracy"])
    twin_lo, twin_hi = contract["near_twin_pairwise_accuracy_range"]
    assert_close("near-twin product pairwise accuracy", twin_acc, float(twin_lo), float(twin_hi))

    top = enrich.loc[enrich["score_decile"].astype(int).eq(10)]
    if len(top) != 1:
        raise RuntimeError("Expected exactly one top score decile row")
    top_pos = int(top.iloc[0]["n_historical_positive"])
    if top_pos != int(contract["top_decile_historical_positive_count"]):
        raise RuntimeError(
            f"Top-decile historical positive count {top_pos} != "
            f"{contract['top_decile_historical_positive_count']}"
        )

    # Architecture boundary is part of the freeze contract.
    if policy["semantics"] != contract["semantics_locked"]:
        raise RuntimeError("ÄrtMatch semantics changed")
    if policy["excluded_to_artkandidat"] != contract["excluded_to_artkandidat_locked"]:
        raise RuntimeError("ÄrtMatch / ÄrtKandidat boundary changed")

    return {
        "anchors": anchors,
        "weights": expected_weights,
        "raw_historical_selection_rank_auc": auc,
        "near_twin_product_pairwise_accuracy": twin_acc,
        "top_decile_historical_positive_count": top_pos,
        "score_min": float(score.min()),
        "score_p50": float(score.median()),
        "score_max": float(score.max()),
    }


def snapshot_name(rel: Path) -> str:
    return "__".join(rel.parts)


def make_manifest(validation: dict) -> dict:
    missing = [str(p) for p in SOURCE_PATHS if not (ROOT / p).exists()]
    if missing:
        raise FileNotFoundError("Missing freeze source(s): " + ", ".join(missing))

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for rel in SOURCE_PATHS:
        src = ROOT / rel
        snap_rel = Path("snapshot") / snapshot_name(rel)
        dst = FREEZE_DIR / snap_rel
        shutil.copy2(src, dst)
        src_hash = sha256_file(src)
        dst_hash = sha256_file(dst)
        if src_hash != dst_hash:
            raise RuntimeError(f"Snapshot hash mismatch for {rel}")
        entries.append({
            "source_path": rel.as_posix(),
            "snapshot_path": snap_rel.as_posix(),
            "sha256": src_hash,
            "size_bytes": int(src.stat().st_size),
        })

    return {
        "schema_version": "akerfro-artmatch-v0a-freeze-1",
        "freeze_name": "ÅkerFrö ÄrtMatch v0a",
        "source_git_head": git_head(),
        "semantics": "relative physical/structural pea-match ranking; not probability",
        "formula": "0.65*slope_component + 0.25*akerscore_component + 0.10*texture_residual_component",
        "scope_frozen": [
            "C6 score formula and weights",
            "component semantics",
            "C5b quadratic ILR residual texture lineage",
            "C6 derived field product and validation summaries",
            "ÄrtMatch versus ÄrtKandidat architecture boundary",
        ],
        "scope_not_frozen": [
            "ÄrtKandidat",
            "rotation scenarios",
            "field area policy",
            "processor/logistics",
            "current crop/contracts",
            "drought/irrigation/water-risk",
            "UI/web presentation",
        ],
        "validation": validation,
        "files": entries,
    }


def freeze() -> None:
    validation = validate_contract()
    if MANIFEST.exists():
        print("Freeze manifest already exists; verifying existing freeze instead.")
        verify()
        return

    FREEZE_DIR.mkdir(parents=True, exist_ok=True)
    manifest = make_manifest(validation)
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("=" * 110)
    print("ÅkerFrö ÄrtMatch v0a FORMAL FREEZE: PASS")
    print("=" * 110)
    print(f"Git HEAD: {manifest['source_git_head']}")
    print(f"Files frozen: {len(manifest['files'])}")
    print(f"Manifest: {MANIFEST}")
    print(f"Scored fields: {validation['anchors']['scored_fields']:,}")
    print(f"Historical positives scored: {validation['anchors']['scored_historical_positive_fields']:,}")
    print(f"Raw rank AUC: {validation['raw_historical_selection_rank_auc']:.3f}")
    print(f"Near-twin product accuracy: {100*validation['near_twin_product_pairwise_accuracy']:.2f}%")
    print("=" * 110)


def verify() -> None:
    if not MANIFEST.exists():
        raise FileNotFoundError(f"Freeze manifest missing: {MANIFEST}")

    current_validation = validate_contract()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    frozen_validation = manifest["validation"]

    # Exact anchors and locked metrics must still satisfy current contract.
    if current_validation["anchors"] != frozen_validation["anchors"]:
        raise RuntimeError("Current anchor set differs from frozen manifest")

    errors = []
    for item in manifest["files"]:
        src = ROOT / item["source_path"]
        snap = FREEZE_DIR / item["snapshot_path"]
        expected = item["sha256"]
        if not src.exists():
            errors.append(f"MISSING SOURCE {item['source_path']}")
        elif sha256_file(src) != expected:
            errors.append(f"SOURCE HASH CHANGED {item['source_path']}")
        if not snap.exists():
            errors.append(f"MISSING SNAPSHOT {item['snapshot_path']}")
        elif sha256_file(snap) != expected:
            errors.append(f"SNAPSHOT HASH CHANGED {item['snapshot_path']}")

    if errors:
        raise RuntimeError("FREEZE VERIFY FAIL:\n  " + "\n  ".join(errors))

    print("=" * 110)
    print("ÅkerFrö ÄrtMatch v0a FREEZE VERIFY: PASS")
    print("=" * 110)
    print(f"Manifest Git HEAD: {manifest['source_git_head']}")
    print(f"Verified frozen files: {len(manifest['files'])}")
    print(f"Manifest: {MANIFEST}")
    print("=" * 110)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["freeze", "verify"], required=True)
    args = ap.parse_args()
    if args.mode == "freeze":
        freeze()
    else:
        verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
