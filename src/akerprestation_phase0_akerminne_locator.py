#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Strict locator for the frozen ÅkerMinne municipality output used by phase 0.

The first pilot version searched all Parquet files heuristically. That could
select a checkpoint/component artifact instead of the frozen final classified
field-year table. This locator accepts only the canonical final filename under
``skane/municipalities`` and validates its adjacent build manifest against the
same 2025 field source.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from akerprestation_phase0_overlay_core import find_akerminne_skane_roots, sha256_file

EXPECTED_YEARS = list(range(2015, 2026))
CANONICAL_FILENAME = "akerminne_year_summary_classified.parquet"


def _current_field_source_hash(repo_root: Path) -> str | None:
    cfg_path = repo_root / "config" / "local_paths.json"
    if not cfg_path.exists():
        return None
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        source = Path(str(cfg.get("skiften") or ""))
        if source.exists() and source.is_file():
            return sha256_file(source)
    except Exception:
        return None
    return None


def find_strict_frozen_akerminne_field_year_file(
    repo_root: Path,
    municipality_code: str,
    municipality: str,
) -> Path | None:
    """Return one validated canonical frozen municipality field-year artifact.

    Guardrails:
    - exact canonical final filename only;
    - only ``skane/municipalities`` outputs are eligible (no smoke/checkpoints);
    - adjacent build_manifest.json required;
    - municipality code/name must match;
    - manifest current source hash must equal today's frozen 2025 source hash;
    - exactly 11 years (2015-2025), one 2025 row per current field;
    - if several worktrees contain byte-different valid candidates, fail loudly.
    """
    field_source_hash = _current_field_source_hash(repo_root)
    candidates: list[tuple[str, Path]] = []

    for root in find_akerminne_skane_roots(repo_root):
        municipality_root = root / "municipalities"
        if not municipality_root.exists():
            continue
        for path in municipality_root.rglob(CANONICAL_FILENAME):
            manifest_path = path.parent / "build_manifest.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            except Exception:
                continue

            if str(manifest.get("municipality_code") or "") != str(municipality_code):
                continue
            if str(manifest.get("municipality") or "").strip().casefold() != str(municipality).strip().casefold():
                continue
            if field_source_hash is not None and str(manifest.get("current_source_sha256") or "") != field_source_hash:
                continue

            try:
                current_fields = int(manifest["current_fields"])
                field_years = int(manifest["field_years"])
            except Exception:
                continue
            if current_fields <= 0 or field_years != current_fields * 11:
                continue

            try:
                frame = pd.read_parquet(path, columns=["current_field_id", "history_year"])
            except Exception:
                continue
            if len(frame) != field_years:
                continue
            years = sorted(pd.to_numeric(frame["history_year"], errors="coerce").dropna().astype(int).unique().tolist())
            if years != EXPECTED_YEARS:
                continue
            ids = frame["current_field_id"].astype(str)
            if ids.nunique() != current_fields:
                continue
            current = frame[pd.to_numeric(frame["history_year"], errors="coerce") == 2025]
            if len(current) != current_fields or not current["current_field_id"].astype(str).is_unique:
                continue

            candidates.append((sha256_file(path), path))

    if not candidates:
        return None

    distinct_hashes = sorted({sha for sha, _ in candidates})
    if len(distinct_hashes) > 1:
        paths = ", ".join(str(path) for _, path in sorted(candidates, key=lambda x: str(x[1])))
        raise RuntimeError(
            "Ambiguous frozen ÅkerMinne artifacts: multiple byte-different canonical candidates passed validation: "
            + paths
        )

    return sorted((path for _, path in candidates), key=lambda p: str(p).lower())[0]
