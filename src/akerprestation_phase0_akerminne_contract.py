#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Contract-backed ÅkerMinne join verification for phase 0.

Use the actual frozen municipality parquet when it is still present. If no
canonical frozen municipality parquet exists anywhere in active worktrees,
fall back to the immutable ``akerminne-v1.0`` contract plus the exact 2025
reference-field identity domain already verified at STOPPUNKT A.

This fallback does NOT fabricate historical rows. It only proves that the new
static context keys are the same current-2025 keys used by frozen ÅkerMinne.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable

import geopandas as gpd
import pandas as pd

from akerprestation_phase0_discovery_core import (
    EXPECTED_BASE_COMMIT,
    EXPECTED_BASE_TAG,
    EXPECTED_REFERENCE_FIELDS,
)
from akerprestation_phase0_akerminne_locator import CANONICAL_FILENAME
from akerprestation_phase0_overlay_core import (
    field_id,
    find_akerminne_skane_roots,
    sha256_file,
)

EXPECTED_FIELD_YEARS = 1_414_996
EXPECTED_COMPONENTS = 2_935_686
EXPECTED_YEARS = list(range(2015, 2026))
FREEZE_DOC = Path("docs") / "AKERMINNE_V1_FREEZE.md"


def _git(repo_root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo_root, text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def _canonical_history_artifacts(repo_root: Path) -> list[Path]:
    found: list[Path] = []
    for root in find_akerminne_skane_roots(repo_root):
        d = root / "municipalities"
        if d.exists():
            found.extend(d.rglob(CANONICAL_FILENAME))
    return sorted(set(found), key=lambda p: str(p).lower())


def _freeze_contract_text(repo_root: Path) -> str:
    tag_commit = _git(repo_root, "rev-list", "-n", "1", EXPECTED_BASE_TAG).strip()
    if tag_commit != EXPECTED_BASE_COMMIT:
        raise RuntimeError(
            f"{EXPECTED_BASE_TAG} resolves to {tag_commit}, expected {EXPECTED_BASE_COMMIT}"
        )
    text = _git(repo_root, "show", f"{EXPECTED_BASE_TAG}:{FREEZE_DOC.as_posix()}")
    required = [
        "Current/reference geometry: Jordbruksverket 2025 current fields.",
        "Current 2025 fields: **128,636**.",
        "Field-years: **1,414,996**",
        "Raw historical overlap/crop components: **2,935,686**.",
        "History years: 2015–2025 inclusive.",
        "Every current field must therefore have exactly 11 rows, 2015 through 2025.",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        raise RuntimeError("Frozen ÅkerMinne contract is missing expected statements: " + repr(missing))
    return text


def _reference_hash_from_discovery(repo_root: Path) -> tuple[str, dict[str, Any], dict[str, Any]]:
    phase = repo_root / "data" / "derived" / "akerprestation_phase0"
    manifest_path = phase / "manifests" / "discovery_manifest.json"
    summary_path = phase / "discovery" / "repository_summary.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    hashes = (manifest.get("sources") or {}).get("source_hashes") or []
    row = next((x for x in hashes if x.get("label") == "2025_reference_fields"), None)
    if row is None:
        raise RuntimeError("Discovery manifest lacks 2025_reference_fields source hash")
    ref = summary.get("local_data_discovery", {}).get("reference_field_schema", {})
    if int(ref.get("feature_count") or -1) != EXPECTED_REFERENCE_FIELDS:
        raise RuntimeError("Discovery reference-field count no longer matches frozen 128,636")
    key_qa = ref.get("key_diagnostics") or {}
    if key_qa.get("status") != "OK" or int(key_qa.get("unique_key_count") or -1) != EXPECTED_REFERENCE_FIELDS:
        raise RuntimeError("Discovery reference-field key QA is not the frozen unique 128,636 domain")
    return str(row["sha256"]), manifest, summary


def _current_municipality_ids(repo_root: Path, municipality_code: str) -> tuple[set[str], str]:
    cfg = json.loads((repo_root / "config" / "local_paths.json").read_text(encoding="utf-8-sig"))
    source = Path(str(cfg.get("skiften") or ""))
    if not source.exists():
        raise FileNotFoundError(source)
    try:
        frame = gpd.read_file(source, where=f"CAST(region_kod AS TEXT) LIKE '{municipality_code}%'")
    except Exception:
        frame = gpd.read_file(source)
        frame = frame[frame["region_kod"].astype(str).str.startswith(str(municipality_code))].copy()
    ids = {field_id(b, s) for b, s in zip(frame["blockid"], frame["skiftesbeteckning"])}
    if len(ids) != len(frame):
        raise RuntimeError("Current municipality source contains duplicate phase-0 field IDs")
    return ids, sha256_file(source)


def discover_frozen_or_contract(
    repo_root: Path,
    municipality_code: str,
    municipality: str,
    pilot_ids: set[str],
    strict_discover: Callable[[Path, str, str, set[str]], tuple[dict[str, Any], pd.DataFrame | None, str | None]],
) -> tuple[dict[str, Any], pd.DataFrame | None, str | None]:
    """Prefer real frozen parquet; otherwise prove the current-field join from the freeze contract."""
    qa, frame, before = strict_discover(repo_root, municipality_code, municipality, pilot_ids)
    if frame is not None:
        qa = dict(qa)
        qa["verification_mode"] = "frozen_history_artifact"
        qa["frozen_history_artifact_available"] = True
        return qa, frame, before

    # Never paper over an invalid retained artifact. Contract fallback is only
    # allowed when the canonical historical output is genuinely absent.
    retained = _canonical_history_artifacts(repo_root)
    if retained:
        qa = dict(qa)
        qa["verification_mode"] = "failed_retained_artifact_validation"
        qa["retained_canonical_candidates"] = [str(p) for p in retained]
        return qa, None, None

    contract_text = _freeze_contract_text(repo_root)
    doc_path = repo_root / FREEZE_DOC
    if not doc_path.exists():
        return {"status": "FAIL", "reason": f"Working-tree freeze contract missing: {doc_path}"}, None, None
    if doc_path.read_text(encoding="utf-8") != contract_text:
        return {"status": "FAIL", "reason": "Working-tree freeze contract differs from immutable akerminne-v1.0 tag"}, None, None

    discovery_hash, discovery_manifest, _summary = _reference_hash_from_discovery(repo_root)
    current_ids, current_source_hash = _current_municipality_ids(repo_root, municipality_code)
    if current_source_hash != discovery_hash:
        return {
            "status": "FAIL",
            "reason": "Current 2025 field source hash differs from STOPPUNKT A discovery hash",
            "current_source_sha256": current_source_hash,
            "discovery_source_sha256": discovery_hash,
        }, None, None
    if current_ids != set(pilot_ids):
        return {
            "status": "FAIL",
            "reason": "Pilot IDs are not exactly the current 2025 municipality ID domain",
            "pilot_reference_ids": len(pilot_ids),
            "current_municipality_ids": len(current_ids),
            "missing_from_pilot": sorted(current_ids - set(pilot_ids))[:100],
            "extra_in_pilot": sorted(set(pilot_ids) - current_ids)[:100],
        }, None, None

    # Current-only frame intentionally contains no invented historical records.
    identity_frame = pd.DataFrame({
        "current_field_id": sorted(current_ids),
        "history_year": [2025] * len(current_ids),
    })
    contract_hash = sha256_file(doc_path)
    qa = {
        "status": "PASS",
        "verification_mode": "freeze_contract_reference_identity",
        "artifact": str(doc_path),
        "artifact_kind": "immutable_freeze_contract_not_history_parquet",
        "artifact_sha256_before": contract_hash,
        "frozen_history_artifact_available": False,
        "frozen_history_artifact_reason": "Canonical generated ÅkerMinne municipality parquet is not retained locally and data/derived is Git-ignored.",
        "warning": "WARN_FROZEN_AKERMINNE_HISTORY_ARTIFACT_NOT_RETAINED: join verified against immutable freeze contract and exact 2025 reference identity domain; historical rows were not re-created.",
        "freeze_tag": EXPECTED_BASE_TAG,
        "freeze_commit": EXPECTED_BASE_COMMIT,
        "freeze_contract_current_fields": EXPECTED_REFERENCE_FIELDS,
        "freeze_contract_field_years": EXPECTED_FIELD_YEARS,
        "freeze_contract_components": EXPECTED_COMPONENTS,
        "years": EXPECTED_YEARS,
        "pilot_reference_ids": len(pilot_ids),
        "matched_pilot_ids": len(pilot_ids),
        "unmatched_pilot_ids": [],
        "current_2025_rows": len(current_ids),
        "join_is_one_to_one": True,
        "expected_11_year_rows": True,
        "expected_11_year_rows_evidence": "immutable akerminne-v1.0 freeze contract",
        "historical_rows_loaded": 0,
        "historical_manual_checks_available": False,
        "reference_field_source_sha256": current_source_hash,
        "discovery_manifest_id": discovery_manifest.get("manifest_id"),
    }
    print(qa["warning"], flush=True)
    return qa, identity_frame, contract_hash
