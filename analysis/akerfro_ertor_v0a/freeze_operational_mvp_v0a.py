#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Formal freeze for ÅkerFrö operational MVP v0a: C8b + C9 + C9b + C10.

Creates a local immutable-style manifest with SHA-256 hashes of code/config
and central generated artifacts. Frozen ÄrtMatch v0a is referenced but not
re-frozen here.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
FREEZE_DIR = ROOT / "work" / "akerfro_ertor_v0a" / "operational_mvp_v0a_freeze"
MANIFEST = FREEZE_DIR / "akerfro_operational_mvp_v0a_freeze_manifest.json"

FILES = [
    # Contracts / implementation
    "config/akerfro_ertor_c8.json",
    "config/akerfro_ertor_c9.json",
    "config/akerfro_ertor_c9b.json",
    "config/akerfro_ertor_c10.json",
    "analysis/akerfro_ertor_v0a/build_artkandidat_c8.py",
    "analysis/akerfro_ertor_v0a/area_logistics_c9.py",
    "analysis/akerfro_ertor_v0a/area_logistics_robustness_c9b.py",
    "analysis/akerfro_ertor_v0a/operational_c10.py",
    # C8b
    "data/derived/akerfro_ertor_v0a/artkandidat_v0a_fields.parquet",
    "work/akerfro_ertor_v0a/artkandidat_c8/artkandidat_class_summary.csv",
    "work/akerfro_ertor_v0a/artkandidat_c8/predecessor_policy.csv",
    "work/akerfro_ertor_v0a/artkandidat_c8/artkandidat_c8_summary.json",
    # C9
    "work/akerfro_ertor_v0a/area_logistics_c9/artkandidat_c9_area_logistics_fields.parquet",
    "work/akerfro_ertor_v0a/area_logistics_c9/area_enrichment.csv",
    "work/akerfro_ertor_v0a/area_logistics_c9/distance_bjuv_enrichment.csv",
    "work/akerfro_ertor_v0a/area_logistics_c9/area_x_distance_enrichment.csv",
    "work/akerfro_ertor_v0a/area_logistics_c9/c9_summary.json",
    # C9b
    "work/akerfro_ertor_v0a/area_logistics_c9b/area_within_distance_enrichment.csv",
    "work/akerfro_ertor_v0a/area_logistics_c9b/distance_within_area_enrichment.csv",
    "work/akerfro_ertor_v0a/area_logistics_c9b/municipality_distance_composition.csv",
    "work/akerfro_ertor_v0a/area_logistics_c9b/sweet_zone_by_municipality.csv",
    "work/akerfro_ertor_v0a/area_logistics_c9b/lomo_logistic_by_municipality.csv",
    "work/akerfro_ertor_v0a/area_logistics_c9b/c9b_summary.json",
    # C10
    "data/derived/akerfro_ertor_v0a/artkandidat_v0a_operational_fields.parquet",
    "data/derived/akerfro_ertor_v0a/artkandidat_v0a_operational_top1000.csv",
    "work/akerfro_ertor_v0a/operational_c10/area_logistics_decile_diagnostic.csv",
    "work/akerfro_ertor_v0a/operational_c10/class_by_operational_band.csv",
    "work/akerfro_ertor_v0a/operational_c10/c10_summary.json",
]

EXPECTED_CLASSES = {
    "A_STRONG_CANDIDATE": 7847,
    "B_PHYSICAL_CANDIDATE": 14882,
    "C_ROTATION_CAUTION": 1424,
    "D_NOT_HIGH_PHYSICAL_MATCH": 104483,
}
EXPECTED_BANDS = {"HIGH": 20327, "MEDIUM": 34060, "LOW": 74249}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:
        return "UNKNOWN"


def validate_anchors() -> dict:
    c10 = ROOT / "data/derived/akerfro_ertor_v0a/artkandidat_v0a_operational_fields.parquet"
    df = pd.read_parquet(c10)
    if len(df) != 128636:
        raise RuntimeError(f"Population anchor failed: {len(df):,} != 128,636")

    classes = {str(k): int(v) for k, v in df["artkandidat_class"].value_counts().items()}
    if classes != EXPECTED_CLASSES:
        raise RuntimeError(f"C8b class anchor failed: {classes} != {EXPECTED_CLASSES}")

    bands = {str(k): int(v) for k, v in df["area_logistics_band"].value_counts().items()}
    if bands != EXPECTED_BANDS:
        raise RuntimeError(f"C10 operational-band anchor failed: {bands} != {EXPECTED_BANDS}")

    c9b = json.loads(
        (ROOT / "work/akerfro_ertor_v0a/area_logistics_c9b/c9b_summary.json")
        .read_text(encoding="utf-8")
    )
    if int(c9b["candidate_fields"]) != 22729:
        raise RuntimeError("C9b candidate-field anchor failed")
    if int(c9b["historical_positive_fields"]) != 590:
        raise RuntimeError("C9b historical-positive anchor failed")

    # Read-only lineage check for already frozen physical score.
    if not bool(
        json.loads(
            (ROOT / "work/akerfro_ertor_v0a/operational_c10/c10_summary.json")
            .read_text(encoding="utf-8")
        )["artmatch_frozen_read_only"]
    ):
        raise RuntimeError("C10 summary does not preserve frozen ÄrtMatch read-only status")

    return {
        "population_fields": 128636,
        "class_counts": classes,
        "operational_band_counts": bands,
        "c9b_candidate_fields": 22729,
        "c9b_historical_positive_fields": 590,
    }


def main() -> int:
    missing = [rel for rel in FILES if not (ROOT / rel).exists()]
    if missing:
        raise FileNotFoundError(
            "Cannot freeze; missing required files:\n  " + "\n  ".join(missing)
        )

    anchors = validate_anchors()
    entries = {}
    for rel in FILES:
        p = ROOT / rel
        entries[rel] = {
            "bytes": p.stat().st_size,
            "sha256": sha256(p),
        }

    FREEZE_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "akerfro-operational-mvp-v0a-freeze-manifest-v1",
        "freeze_name": "akerfro-ertor-operational-mvp-v0a",
        "status": "FORMALLY_FROZEN_LOCAL_ARTIFACT_SET",
        "scope": "C8b + C9 + C9b + C10 downstream of frozen ÄrtMatch v0a",
        "git": {
            "repository": "PiggeGnidde/akersync",
            "branch": "feature/akerfro-ertor-mvp-v0a",
            "head_at_freeze": git_head(),
        },
        "lineage": {
            "artmatch_v0a": "already formally frozen; read-only and not re-frozen here",
            "akerminne": "akerminne-v1.0",
        },
        "anchors": anchors,
        "policy_summary": {
            "candidate_year": 2026,
            "artmatch_high": "top 20% of scored fields, inherited from C8b",
            "rotation_gap_years": 6,
            "A_predecessor_min_positive_events": 50,
            "area_fit": "piecewise-linear broad 5-12 ha plateau",
            "bjuv_proximity": "monotone piecewise-linear straight-line distance proxy",
            "area_logistics": "0.55 AreaFit + 0.45 BjuvProximity",
            "ranking": "C8 class -> AreaLogistik -> frozen ÄrtMatch -> field id",
        },
        "guardrails": [
            "No frozen ÄrtMatch v0a file is modified by this freeze.",
            "C8b/C9/C9b/C10 are frozen as operational MVP policy and diagnostics, not agronomic truth.",
            "Historical pea enrichment is positive-unlabeled selection evidence, not causal yield evidence.",
            "Bjuv distance is straight-line logistics proxy, not road time.",
            "Contracts, irrigation/water risk and farmer-level management remain outside this freeze.",
        ],
        "files": entries,
    }
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("=" * 100)
    print("ÅkerFrö operational MVP v0a FORMAL FREEZE")
    print("=" * 100)
    print(f"Freeze: {manifest['freeze_name']}")
    print(f"Git HEAD: {manifest['git']['head_at_freeze']}")
    print(f"Files frozen: {len(entries)}")
    print(f"Population: {anchors['population_fields']:,}")
    print(f"A/B/C/D: {anchors['class_counts']}")
    print(f"Operational HIGH/MEDIUM/LOW: {anchors['operational_band_counts']}")
    print(f"Manifest: {MANIFEST}")
    print("=" * 100)
    print("ÅkerFrö operational MVP v0a FORMAL FREEZE: PASS")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
