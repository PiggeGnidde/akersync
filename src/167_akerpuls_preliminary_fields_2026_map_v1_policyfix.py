#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibility fix for ÅkerPuls preliminary fields 2026 map v1.

The formal preliminary-geometry v1 freeze stores the frozen policy under the
`product_policy` key. The original map builder accidentally looked for `policy`.
This wrapper replaces only that frozen-input verifier and then delegates all map
construction/QA to src/166 unchanged.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "src" / "166_akerpuls_preliminary_fields_2026_map_v1.py"


def load_base():
    spec = importlib.util.spec_from_file_location("akerpuls_map_v1_base", BASE)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def fixed_verify_frozen_inputs(mod, d2c: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Path]]:
    prelim_path = d2c / mod.PRELIM_FREEZE_REL
    proposal_path = d2c / mod.PROPOSAL_FREEZE_REL
    for p in (prelim_path, proposal_path):
        if not p.is_file():
            raise FileNotFoundError(p)
    if mod.sha256_file(prelim_path) != mod.EXPECTED_PRELIM_V1_FREEZE_SHA256:
        raise RuntimeError("ÅkerPuls preliminary geometry v1 freeze SHA changed")
    if mod.sha256_file(proposal_path) != mod.EXPECTED_PROPOSAL_FREEZE_SHA256:
        raise RuntimeError("P95 proposal freeze SHA changed")

    prelim = mod.read_json(prelim_path)
    prop = mod.read_json(proposal_path)
    if prelim.get("status") != "FROZEN_AKERPULS_PRELIMINARY_GEOMETRY_V1":
        raise RuntimeError("Unexpected preliminary geometry v1 freeze status")
    if prop.get("status") != "FROZEN_P95_SPLIT_LINE_PROPOSALS_V1":
        raise RuntimeError("Unexpected P95 proposal freeze status")
    if int(prop.get("p95_fields", -1)) != mod.EXPECTED_P95:
        raise RuntimeError("P95 census changed")
    if int(prop.get("line_available_fields", -1)) != mod.EXPECTED_SPLIT_LINES:
        raise RuntimeError("LINE_AVAILABLE census changed")
    if int(prop.get("no_shared_interface_fields", -1)) != mod.EXPECTED_NO_GEOMETRY:
        raise RuntimeError("NO_SHARED_INTERFACE census changed")

    # Formal v1 freeze schema: the policy is stored under `product_policy`.
    policy = prelim.get("product_policy", {})
    if policy.get("canonical_geometry") != "OFFICIAL_2025_GEOMETRY":
        raise RuntimeError("V1 canonical geometry policy changed")
    if policy.get("smoothing") is not False or policy.get("gap_filling") is not False:
        raise RuntimeError("V1 raw geometry policy changed")
    if policy.get("automatic_geometry_replacement") is not False:
        raise RuntimeError("V1 automatic replacement policy changed")

    hashes = prop.get("source_output_hashes", {})
    required = {
        "p95_split_proposal_summary.csv",
        "p95_primary_split_line_review.gpkg",
        "p95_official_2025_parents_review.gpkg",
        "p95_raw_k2_interface_review.gpkg",
        "p95_b2_child_evidence_review.gpkg",
    }
    if set(hashes) != required:
        raise RuntimeError(f"Proposal output set changed: {sorted(hashes)}")
    paths: dict[str, Path] = {}
    for name, rec in hashes.items():
        p = Path(rec["path"])
        if not p.is_file():
            raise FileNotFoundError(p)
        if mod.sha256_file(p) != rec.get("sha256") or int(p.stat().st_size) != int(rec.get("bytes", -1)):
            raise RuntimeError(f"Frozen proposal artifact changed: {name}")
        paths[name] = p
    return prelim, prop, paths


def main() -> int:
    mod = load_base()
    mod.verify_frozen_inputs = lambda d2c: fixed_verify_frozen_inputs(mod, d2c)
    return int(mod.main())


if __name__ == "__main__":
    raise SystemExit(main())
