#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Independent verification of ÅkerPrestation phase 0 full-Skåne outputs."""
from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from akerprestation_phase0_discovery_core import load_json, sha256_file
from akerprestation_phase0_overlay_core import field_id

PHASE = ROOT / "data" / "derived" / "akerprestation_phase0"
OUT = PHASE / "skane"
QA_DIR = PHASE / "qa" / "skane"
MANIFEST = PHASE / "manifests" / "skane_phase0_manifest.json"
PROJECT_CONFIG = ROOT / "config" / "local_paths.json"
MUNICIPALITY_CONFIG = ROOT / "config" / "akerminne_skane_municipalities.json"
FREEZE_DOC = ROOT / "docs" / "AKERMINNE_V1_FREEZE.md"
EXPECTED_FIELDS = 128636
EXPECTED_MUNICIPALITIES = 33
VALID_CLASSES = set(range(1, 11))


def req(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def main() -> int:
    errors: list[str] = []
    qa = load_json(req(QA_DIR / "qa.json"))
    manifest = load_json(req(MANIFEST))
    context = pd.read_parquet(req(OUT / "field_static_context.parquet"))
    soil = pd.read_parquet(req(OUT / "field_soil_class_components.parquet"))
    sko = pd.read_parquet(req(OUT / "field_sko_components.parquet"))
    boundary = pd.read_parquet(req(OUT / "sko_boundary_fields.parquet"))
    municipality_qa = pd.read_csv(req(QA_DIR / "municipality_qa.csv"), encoding="utf-8-sig")
    class_csv = pd.read_csv(req(QA_DIR / "soil_class_by_municipality.csv"), encoding="utf-8-sig")
    sko_csv = pd.read_csv(req(QA_DIR / "sko_distribution.csv"), encoding="utf-8-sig")

    if qa.get("status") != "PASS":
        errors.append("qa.json status is not PASS")
    if manifest.get("status") != "PASS":
        errors.append("manifest status is not PASS")
    if len(context) != EXPECTED_FIELDS or context["current_field_id"].astype(str).nunique() != EXPECTED_FIELDS:
        errors.append("context is not 128,636 unique current_field_id rows")
    if len(municipality_qa) != EXPECTED_MUNICIPALITIES:
        errors.append("municipality_qa.csv does not contain 33 rows")
    if "status" not in municipality_qa or not (municipality_qa["status"].astype(str) == "PASS").all():
        errors.append("not all municipality QA rows are PASS")

    observed_classes = set(
        pd.to_numeric(soil["soil_class_normalized"], errors="coerce")
        .dropna().astype(int).unique().tolist()
    )
    if observed_classes != VALID_CLASSES:
        errors.append(f"observed normalized classes are {sorted(observed_classes)}, expected 1-10")
    if soil["soil_class_normalized"].isna().any():
        errors.append("unverified soil-class components present")
    if (sko["sko_id"].fillna("").astype(str).str.strip() == "").any():
        errors.append("blank/unverified SKO components present")
    if (context["sko_coverage_unique"] <= 1e-6).any():
        errors.append("at least one reference field has no SKO coverage")

    expected_boundary_ids = set(
        context.loc[context["crosses_sko_boundary"].fillna(False), "current_field_id"].astype(str)
    )
    boundary_ids = set(boundary["current_field_id"].astype(str))
    if boundary_ids != expected_boundary_ids:
        errors.append("sko_boundary_fields.parquet does not equal all raw SKO boundary fields")

    if not {"municipality_code", "municipality", "soil_class", "area_kind", "area_m2"}.issubset(class_csv.columns):
        errors.append("soil_class_by_municipality.csv schema incomplete")
    if not {"municipality_code", "municipality", "sko_id", "intersection_area_m2"}.issubset(sko_csv.columns):
        errors.append("sko_distribution.csv schema incomplete")
    if not req(QA_DIR / "problem_fields.geojson").exists():
        errors.append("problem_fields.geojson missing")
    if not req(OUT / "sko_boundary_fields.geojson").exists():
        errors.append("sko_boundary_fields.geojson missing")

    project = load_json(req(PROJECT_CONFIG))
    source_path = Path(project["skiften"])
    source = gpd.read_file(source_path)
    source_ids = {field_id(b, s) for b, s in zip(source["blockid"], source["skiftesbeteckning"])}
    context_ids = set(context["current_field_id"].astype(str))
    if len(source) != EXPECTED_FIELDS or len(source_ids) != EXPECTED_FIELDS:
        errors.append("current 2025 source is not 128,636 unique fields")
    if source_ids != context_ids:
        errors.append("context ID set differs from current 2025 source")

    if sha256_file(FREEZE_DOC) != str((manifest.get("akerminne_reference") or {}).get("freeze_contract_sha256") or ""):
        errors.append("ÅkerMinne freeze contract hash mismatch")
    if sha256_file(source_path) != str((manifest.get("sources") or {}).get("reference_fields_sha256") or ""):
        errors.append("reference field source hash mismatch")

    muni_cfg = load_json(req(MUNICIPALITY_CONFIG))
    municipalities = muni_cfg.get("municipalities") or []
    if len(municipalities) != EXPECTED_MUNICIPALITIES:
        errors.append("municipality config is not 33 rows")
    for row in municipalities:
        code = str(row["code"])
        name = str(row["name"])
        qa_candidates = list((QA_DIR / "municipalities").glob(f"{code}_*.json"))
        if len(qa_candidates) != 1:
            errors.append(f"{code} {name}: expected one municipality QA JSON, found {len(qa_candidates)}")
        for layer in ("soil_class", "sko"):
            cp = PHASE / "checkpoints" / name / layer / "checkpoint_manifest.json"
            if not cp.exists():
                errors.append(f"{code} {name}: missing {layer} checkpoint manifest")

    for rel, expected_hash in (manifest.get("outputs") or {}).items():
        path = PHASE / Path(rel)
        if not path.exists():
            errors.append(f"manifest output missing: {rel}")
        elif sha256_file(path) != expected_hash:
            errors.append(f"manifest output hash mismatch: {rel}")

    print("=" * 94)
    print("ÅkerPrestation phase 0 · VERIFY FULL SKÅNE")
    print("=" * 94)
    print(f"Context rows: {len(context):,}")
    print(f"Soil components: {len(soil):,}")
    print(f"SKO components: {len(sko):,}")
    print(f"Municipalities PASS: {(municipality_qa['status'].astype(str) == 'PASS').sum()}/{len(municipality_qa)}")
    print(f"Classes present: {sorted(observed_classes)}")
    print(f"Raw SKO boundary fields: {len(boundary):,}")
    print(f"Reference ID reconciliation: {len(context_ids & source_ids):,}/{EXPECTED_FIELDS:,}")

    if errors:
        for err in errors:
            print("ERROR_VERIFY_SKANE: " + err)
        print("VERIFY_AKERPRESTATION_PHASE0_SKANE: FAIL")
        return 1

    print("VERIFY_AKERPRESTATION_PHASE0_SKANE: PASS")
    print("STOPPUNKT C: no web/tag/merge/satellite/yield-model phase executed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
