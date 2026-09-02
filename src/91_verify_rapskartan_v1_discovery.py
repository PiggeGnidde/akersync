#!/usr/bin/env python3
"""Independent STOPPUNKT A verifier for Rapskartan Skåne V1."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from rapskartan_v1_discovery_core import (
    EXPECTED_CURRENT_FIELDS,
    UPSTREAM_COMMIT,
    UPSTREAM_TAG,
    cutoff_contract,
    repository_snapshot,
    sha256_file,
    verify_repository_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    manifest = json.loads((out / "discovery_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "PASS":
        raise RuntimeError(f"Discovery manifest is not PASS: {manifest.get('status')}")
    if manifest.get("upstream_tag") != UPSTREAM_TAG or manifest.get("upstream_commit") != UPSTREAM_COMMIT:
        raise RuntimeError("Manifest upstream freeze mismatch")
    for record in manifest.get("artifacts", []):
        path = out / record["path"]
        if not path.exists() or path.stat().st_size != int(record["bytes"]) or sha256_file(path) != record["sha256"]:
            raise RuntimeError(f"Manifest artifact mismatch: {record['path']}")

    scope = manifest.get("scope") or {}
    if not scope.get("discovery_only"):
        raise RuntimeError("Manifest is not discovery-only")
    forbidden_true = [
        "row_level_2025_ground_truth_exported", "classifier_created", "features_created", "threshold_selected",
        "mass_download_run", "sentinel1_touched", "web_touched", "deployment",
    ]
    if any(scope.get(key) for key in forbidden_true):
        raise RuntimeError("Forbidden later-phase scope flag is true")

    snapshot = repository_snapshot(ROOT)
    repository_errors = verify_repository_snapshot(snapshot)
    if repository_errors:
        raise RuntimeError(f"Repository verification failed: {repository_errors}")
    if manifest.get("feature_head") != snapshot.get("head"):
        raise RuntimeError("Discovery feature HEAD differs from current HEAD")

    crop = json.loads((out / "crop_code_contract.json").read_text(encoding="utf-8"))
    if crop.get("status") != "PASS":
        raise RuntimeError("Crop-code contract is not PASS")
    pairs_2025 = {(x["crop_code_raw"], x["crop_subcategory_raw"]) for x in crop["positive_mappings"] if x["year"] == 2025}
    if pairs_2025 != {("20", None), ("80", "20")}:
        raise RuntimeError(f"Unexpected 2025 positive code paths: {pairs_2025}")

    inventory = pd.read_csv(out / "crop_ground_truth_inventory.csv")
    forbidden_columns = {"current_field_id", "field_id", "geometry", "geom", "wkt"}
    if forbidden_columns & set(inventory.columns):
        raise RuntimeError("Aggregate inventory contains row-level/spatial columns")
    if inventory.target_year.astype(int).tolist() != list(range(2015, 2026)):
        raise RuntimeError("Inventory years mismatch")
    current = inventory[inventory.target_year.astype(int) == 2025]
    if len(current) != 1 or int(current.iloc[0].unique_current_reference_fields) != EXPECTED_CURRENT_FIELDS:
        raise RuntimeError("2025 inventory field count mismatch")
    if int(current.iloc[0].winter_rapeseed_fields) <= 0 or float(current.iloc[0].winter_rapeseed_area_ha) <= 0:
        raise RuntimeError("2025 winter rapeseed aggregate is empty")

    geometry = json.loads((out / "geometry_lineage.json").read_text(encoding="utf-8"))
    if geometry["current_2025"]["hash_status"] != "PASS" or len(geometry["complete_years"]) < 3:
        raise RuntimeError("Geometry lineage is not sufficient for the next bounded pilot")
    access = json.loads((out / "satellite_access.json").read_text(encoding="utf-8"))
    if access["stac"]["status"] != "PASS" or access["process"]["status"] != "PASS":
        raise RuntimeError("Sentinel-2 catalogue/pixel access smoke is not PASS")
    cutoff = json.loads((out / "temporal_cutoff_contract.json").read_text(encoding="utf-8"))
    if cutoff != cutoff_contract():
        raise RuntimeError("Temporal cutoff contract mismatch")

    print("=" * 88)
    print("RAPSKARTAN SKANE V1 STOPPUNKT A VERIFIER: PASS")
    print("=" * 88)
    print(f"Upstream: {UPSTREAM_TAG} -> {UPSTREAM_COMMIT}")
    print(f"Feature HEAD: {snapshot['head']}")
    print(f"2025 winter rapeseed: {int(current.iloc[0].winter_rapeseed_fields):,} fields / {float(current.iloc[0].winter_rapeseed_area_ha):,.2f} ha")
    print(f"2025 positive raw code paths: {current.iloc[0].positive_raw_code_pairs}")
    print(f"Complete historical geometry years: {geometry['complete_years']}")
    print("Sentinel-2 STAC + authenticated 32x32 L2A pixel access: PASS")
    print("2025 row-level labels / classifier / mass download / S1 / web: NO")
    print("STOPPUNKT A")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

