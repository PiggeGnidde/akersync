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
EXPECTED_SKO_IDS = {
    "0731", "1011", "1111", "1112", "1121", "1122", "1123", "1124", "1131",
    "1211", "1212", "1213", "1214", "1215", "1216", "1221", "1222", "1321",
}

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
    if observed_sko != EXPECTED_SKO_IDS:
        raise RuntimeError(f"Phase 0 dominant SKO domain avviker: {sorted(observed_sko)}")
    return frame


def enrich_properties(props: dict[str, Any], row: dict[str, Any]) -> None:
    soil_class = _clean_int(row.get("dominant_soil_class"))
    sko_id = str(row.get("dominant_sko_id") or "")
    if sko_id not in EXPECTED_SKO_IDS:
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
    props["historic_class_dominant_share"] = _clean_float(row.get("dominant_soil_class_share"))
    props["historic_class_count"] = _clean_int(row.get("soil_class_count"))
    props["historic_class_coverage"] = _clean_float(row.get("soil_class_coverage_unique"))
    props["historic_class_unclassified_share"] = _clean_float(row.get("unclassified_soil_share"))
    props["historic_class_mixed"] = bool(row.get("mixed_soil_class", False))

    # Keep SKO as text so a leading zero, e.g. 0731, can never be lost.
    props["sko_id"] = sko_id
    props["sko_dominant_share"] = _clean_float(row.get("dominant_sko_share"))
    props["sko_count"] = _clean_int(row.get("sko_count"))
    props["sko_coverage"] = _clean_float(row.get("sko_coverage_unique"))
    props["crosses_sko_boundary"] = bool(row.get("crosses_sko_boundary", False))

    props["phase0_context_status"] = str(row.get("context_status") or "")
    props["phase0_context_reason_flags"] = str(row.get("reason_flags") or "")
    props["phase0_source_manifest_id"] = str(row.get("source_manifest_id") or "")
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
            context_municipality = str(row.get("municipality") or "")
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
            boundary_sko += int(props["crosses_sko_boundary"])

        document["static_context_version"] = PHASE0_VERSION
        path.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"  {municipality:16s} {len(features):6,d} skiften · phase0 context OK")

    expected_ids = set(context["current_field_id"].astype(str))
    if seen != expected_ids:
        missing = len(expected_ids - seen)
        extra = len(seen - expected_ids)
        raise RuntimeError(f"Phase 0/public ID reconciliation failed: missing={missing}, extra={extra}")

    manifest["akerprestation_phase0_version"] = PHASE0_VERSION
    manifest["historic_class_domain"] = "1-10"
    manifest["sko_id_type"] = "string"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Keep the derived public manifest synchronized with dist when present.
    derived_manifest = build_dir / "akerpass_public_v1" / "municipalities.json"
    if derived_manifest.exists():
        derived_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("AKERPASS PHASE0 ENRICH: OK")
    print(f"  Public/context IDs: {len(seen):,}/{EXPECTED_FIELDS:,}")
    print(f"  Historisk klass saknas explicit: {missing_class:,}")
    print("  Dominanta klasser: " + ", ".join(f"{k}:{v:,}" for k, v in class_counts.items()))
    print(f"  Råa SKO-gränsfält: {boundary_sko:,}")
    print(f"  SKO-ID:n: {len(EXPECTED_SKO_IDS)} · ledande noll bevaras som text")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
