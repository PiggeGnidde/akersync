#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Enrich generated ÅkerPass municipality JSON with frozen ÅkerPrestation phase 0 context.

This is intentionally a post-processing step. The legacy ÅkerPass public build is run and
verified first; only then are the frozen phase-0 reference attributes added. No ÅkerScore,
ÅkerVärde or ÅkerDrift values are recalculated or changed here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from common import MUN_CODES, load_config

PHASE0_VERSION = "akerprestation-phase0-v0a"
EXPECTED_FIELDS = 128_636
EXPECTED_CLASSES = set(range(1, 11))
HISTORIC_CLASS_COVERAGE_TOL = 1e-6

# Frozen phase-0 source domain contains 18 SKO IDs. 1011 occurs only as a tiny
# raw component and is never dominant on a 2025 reference field. The public
# field view therefore legitimately contains 17 dominant SKO IDs.
EXPECTED_SKO_SOURCE_IDS = {
    "0731", "1011", "1111", "1112", "1121", "1122", "1123", "1124", "1131",
    "1211", "1212", "1213", "1214", "1215", "1216", "1221", "1222", "1321",
}
EXPECTED_DOMINANT_SKO_IDS = EXPECTED_SKO_SOURCE_IDS - {"1011"}

REQUIRED_CONTEXT_COLUMNS = (
    "current_field_id", "municipality", "reference_year",
    "dominant_soil_class", "dominant_soil_class_share", "soil_class_count",
    "soil_class_coverage_unique", "unclassified_soil_share", "mixed_soil_class",
    "dominant_sko_id", "dominant_sko_share", "sko_count", "sko_coverage_unique",
    "crosses_sko_boundary", "context_status", "reason_flags", "source_manifest_id",
)


def _clean_float(value: Any, digits: int = 6) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def _clean_int(value: Any) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)


def _clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value)


def _clean_bool(value: Any) -> bool:
    if value is None or pd.isna(value):
        return False
    return bool(value)


def _coverage(value: Any) -> float:
    if value is None or pd.isna(value):
        return 0.0
    return float(value)


def published_historic_class(row: dict[str, Any]) -> int | None:
    """Return class only when phase-0 regards the field as actually covered.

    The frozen full-Skåne QA defines a fully missing historical class as
    soil_class_coverage_unique <= 1e-6. A microscopic positive polygon touch can
    still create a technical dominant_soil_class in the raw overlay summary;
    publishing that as the field's class would be misleading. Preserve the raw
    fact in the frozen phase-0 artifact, but suppress it in the public field view.
    """
    if _coverage(row.get("soil_class_coverage_unique")) <= HISTORIC_CLASS_COVERAGE_TOL:
        return None
    return _clean_int(row.get("dominant_soil_class"))


def load_context(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"Saknar fryst ÅkerPrestation fas 0-context: {path}. "
            "Kör/behåll den validerade Skåne fas 0-builden först."
        )
    frame = pd.read_parquet(path)
    missing = [c for c in REQUIRED_CONTEXT_COLUMNS if c not in frame.columns]
    if missing:
        raise RuntimeError("Phase 0 context saknar kolumner: " + ", ".join(missing))
    if len(frame) != EXPECTED_FIELDS:
        raise RuntimeError(f"Phase 0 context har {len(frame):,} rader; väntat {EXPECTED_FIELDS:,}")
    if frame["current_field_id"].duplicated().any():
        raise RuntimeError("Phase 0 context innehåller dubbla current_field_id")
    if set(frame["reference_year"].dropna().astype(int).unique()) != {2025}:
        raise RuntimeError("Phase 0 context har annan reference_year än 2025")

    classes = set(frame["dominant_soil_class"].dropna().astype(int).unique())
    if classes != EXPECTED_CLASSES:
        raise RuntimeError(f"Phase 0 dominant soil class domain är {sorted(classes)}, väntat 1–10")

    sko = frame["dominant_sko_id"].astype("string")
    if sko.isna().any() or (sko.str.len() == 0).any():
        raise RuntimeError("Phase 0 context innehåller skifte utan dominant SKO")
    observed_sko = set(sko.astype(str).unique())
    if observed_sko != EXPECTED_DOMINANT_SKO_IDS:
        raise RuntimeError(
            "Phase 0 dominant SKO domain avviker: "
            f"{sorted(observed_sko)}; väntat {sorted(EXPECTED_DOMINANT_SKO_IDS)}"
        )
    return frame


def enrich_properties(props: dict[str, Any], row: dict[str, Any]) -> None:
    soil_class = published_historic_class(row)
    soil_coverage = _coverage(row.get("soil_class_coverage_unique"))
    class_is_missing = soil_class is None
    sko_id = _clean_text(row.get("dominant_sko_id"))
    if sko_id not in EXPECTED_SKO_SOURCE_IDS:
        raise RuntimeError(f"Ogiltigt dominant SKO-ID för {props.get('id')}: {sko_id!r}")

    props["historic_class"] = soil_class
    props["historic_class_status"] = (
        "class_1_10" if soil_class is not None else "not_classified_in_historic_reference"
    )
    props["historic_class_status_label"] = (
        "Historisk klass 1–10 identifierad"
        if soil_class is not None
        else "Ingen historisk klass i referensunderlaget"
    )
    props["historic_class_dominant_share"] = (
        None if class_is_missing else _clean_float(row.get("dominant_soil_class_share"))
    )
    props["historic_class_count"] = (
        0 if class_is_missing else _clean_int(row.get("soil_class_count"))
    )
    props["historic_class_coverage"] = _clean_float(soil_coverage)
    props["historic_class_unclassified_share"] = _clean_float(row.get("unclassified_soil_share"))
    props["historic_class_mixed"] = (
        False if class_is_missing else _clean_bool(row.get("mixed_soil_class"))
    )

    # Keep SKO as text so a leading zero, e.g. 0731, can never be lost.
    props["sko_id"] = sko_id
    props["sko_dominant_share"] = _clean_float(row.get("dominant_sko_share"))
    props["sko_count"] = _clean_int(row.get("sko_count"))
    props["sko_coverage"] = _clean_float(row.get("sko_coverage_unique"))
    props["crosses_sko_boundary"] = _clean_bool(row.get("crosses_sko_boundary"))

    props["phase0_context_status"] = _clean_text(row.get("context_status"))
    props["phase0_context_reason_flags"] = _clean_text(row.get("reason_flags"))
    props["phase0_source_manifest_id"] = _clean_text(row.get("source_manifest_id"))
    models = props.setdefault("model_versions", {})
    models["akerprestation_phase0"] = PHASE0_VERSION


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/local_paths.json")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    config = load_config(root / args.config)
    build_dir = root / config.get("build_dir", "data/derived")
    dist_dir = root / config.get("dist_dir", "dist")
    context_path = build_dir / "akerprestation_phase0" / "skane" / "field_static_context.parquet"
    context = load_context(context_path)
    lookup = context.set_index("current_field_id", drop=False).to_dict(orient="index")

    manifest_path = dist_dir / "municipalities.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Saknar {manifest_path}; kör legacy public build först")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    municipalities = manifest.get("municipalities") or {}
    if set(municipalities) != set(MUN_CODES):
        raise RuntimeError("Publikt kommunmanifest innehåller inte exakt Skånes 33 kommuner")

    seen: set[str] = set()
    class_counts = {i: 0 for i in range(1, 11)}
    missing_class = 0
    boundary_sko = 0
    dominant_sko_seen: set[str] = set()

    for municipality, meta in municipalities.items():
        path = dist_dir / meta["file"]
        document = json.loads(path.read_text(encoding="utf-8"))
        features = (document.get("fields") or {}).get("features") or []
        if len(features) != int(meta.get("fields", -1)):
            raise RuntimeError(f"{municipality}: fältantal i JSON avviker från manifest")

        for feature in features:
            props = feature.get("properties") or {}
            field_id = str(props.get("id") or feature.get("id") or "")
            row = lookup.get(field_id)
            if row is None:
                raise RuntimeError(f"{municipality} {field_id}: saknas i fryst phase 0 context")
            if field_id in seen:
                raise RuntimeError(f"Publik export innehåller dubbelt skifte: {field_id}")
            context_municipality = _clean_text(row.get("municipality"))
            if context_municipality != municipality:
                raise RuntimeError(
                    f"{field_id}: kommun mismatch public={municipality!r}, phase0={context_municipality!r}"
                )
            enrich_properties(props, row)
            feature["properties"] = props
            seen.add(field_id)
            cls = props["historic_class"]
            if cls is None:
                missing_class += 1
            else:
                class_counts[int(cls)] += 1
            dominant_sko_seen.add(props["sko_id"])
            boundary_sko += int(props["crosses_sko_boundary"])

        document["static_context_version"] = PHASE0_VERSION
        path.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"  {municipality:16s} {len(features):6,d} skiften · phase0 context OK")

    expected_ids = set(context["current_field_id"].astype(str))
    if seen != expected_ids:
        missing = len(expected_ids - seen)
        extra = len(seen - expected_ids)
        raise RuntimeError(f"Phase 0/public ID reconciliation failed: missing={missing}, extra={extra}")
    if dominant_sko_seen != EXPECTED_DOMINANT_SKO_IDS:
        raise RuntimeError("Publik dominant SKO-domän ändrades under enrichment")

    manifest["akerprestation_phase0_version"] = PHASE0_VERSION
    manifest["historic_class_domain"] = "1-10"
    manifest["historic_class_missing_coverage_tolerance"] = HISTORIC_CLASS_COVERAGE_TOL
    manifest["sko_id_type"] = "string"
    manifest["sko_source_id_count"] = len(EXPECTED_SKO_SOURCE_IDS)
    manifest["sko_dominant_id_count"] = len(EXPECTED_DOMINANT_SKO_IDS)
    manifest["sko_dominant_ids"] = sorted(EXPECTED_DOMINANT_SKO_IDS)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("AKERPASS PHASE0 ENRICH: OK")
    print(f"  Public/context IDs: {len(seen):,}/{EXPECTED_FIELDS:,}")
    print(f"  Historisk klass saknas explicit: {missing_class:,}")
    print(f"  Missing-class tolerance: coverage <= {HISTORIC_CLASS_COVERAGE_TOL:g}")
    print("  Dominanta klasser: " + ", ".join(f"{k}:{v:,}" for k, v in class_counts.items()))
    print(f"  Råa SKO-gränsfält: {boundary_sko:,}")
    print(f"  SKO source domain: {len(EXPECTED_SKO_SOURCE_IDS)} IDs")
    print(f"  Dominant SKO field domain: {len(EXPECTED_DOMINANT_SKO_IDS)} IDs · 1011 is source-only/non-dominant")
    print("  SKO 0731: ledande nolla bevaras som text")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
