#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Merge frozen/validated derived data into municipality public web chunks."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd

from common import CSV_MUN_TO_UI, MUN_CODES, load_config


SCORE_VERSION = "akerscore-soil-v0c"
VALUE_VERSION = "akervarde-v1.0-rc1"
DRIFT_VERSION = "akerdrift-fast-v2-hybrid-rc1"
DATASET_VERSION = "akerpass-public-v1"
CROP_YEAR = 2025

# Jordbruksverket crop codes that explicitly describe land outside the arable
# target population. Codes 49/50/57 are grass on arable land and therefore do
# not belong here.
PASTURE_MEADOW_CODES = {52, 53, 55, 61, 89, 90, 95}
OTHER_NON_ARABLE_CODES = {314}

GEOMETRY_FIELDS = (
    "area_ha", "rectangularity", "convexity", "compactness_4piA_P2",
    "mbr_aspect_ratio", "hole_count", "hole_area_ha", "component_count",
    "mbr_long_m", "mbr_short_m", "mbr_long_axis_deg_from_north",
    "erl_proxy_m", "perimeter_per_ha_m",
)
TOPOGRAPHY_FIELDS = (
    "elev_mean_m", "elev_p05_m", "elev_p95_m", "relief_p95_p05_m",
    "slope_mean_deg", "slope_p90_deg", "slope_p95_deg", "slope_lt_1_pct",
    "slope_gt_3_pct", "local_low50_lt_m0p25_pct", "dem_coverage_pct",
)
HYDROLOGY_FIELDS = (
    "twi_coverage_pct", "twi_mean", "twi_sd", "twi_p50", "twi_p90", "twi_p95",
    "twi_ge_farmland_p90_pct", "twi_ge_farmland_p95_pct", "ln_sca_p90",
    "hydro_slope_mean_deg", "hydro_slope_p90_deg", "distance_to_mosaic_bbox_edge_m",
)
DRIFT_FIELDS = (
    "geometry_score", "drift_terrain_factor", "drift_slope_difficulty",
    "drift_slope_mean_deg", "drift_slope_p90_deg", "drift_slope_p95_deg",
    "drift_slope_gt5_share", "drift_slope_gt10_share", "drift_slope_gt16_7_share",
    "drift_slope_coverage", "drift_twi_mean", "drift_twi_p90_share",
    "drift_twi_p95_share", "drift_twi_coverage", "pa_ratio", "fe_geom", "erl",
    "rectangularity", "convexity", "compactness", "mbr_aspect",
)

# Public output is allow-listed below. This deny-list is a second line of defence.
FORBIDDEN_PUBLIC_KEYS = re.compile(
    r"(^|_)(pred_kr_ha|base_kr_ha|predicted_price|estimated_sek|kopeskilling|"
    r"purchase_price|price_kr|value_kr|rate_per_ha)(_|$)", re.IGNORECASE
)


def safe_slug(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")


def number(value: Any, digits: int = 5):
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(result):
        return None
    return round(result, digits)


def first_number(*values: Any, digits: int = 5):
    for value in values:
        result = number(value, digits)
        if result is not None:
            return result
    return None


def text_id(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    result = str(value)
    return result[:-2] if result.endswith(".0") else result


def ui_municipality(value: Any) -> str:
    name = str(value)
    return CSV_MUN_TO_UI.get(name, name)


def key(blockid: Any, skifte: Any) -> str:
    return f"{text_id(blockid)}|{text_id(skifte)}"


def read_csv(path: Path, required: tuple[str, ...] = ()) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_csv(path, encoding="utf-8-sig", dtype={
        "blockid": str, "skiftesbeteckning": str, "kommun": str,
        "municipality": str, "region_kod": str,
    })
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise RuntimeError(f"{path} saknar kolumner: {', '.join(missing)}")
    return frame


def read_parquet(path: Path, required: tuple[str, ...] = ()) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_parquet(path)
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise RuntimeError(f"{path} saknar kolumner: {', '.join(missing)}")
    return frame


def rows_by_field(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    return {
        key(row.get("blockid"), row.get("skiftesbeteckning")): row.to_dict()
        for _, row in frame.iterrows()
    }


def rows_by_block(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    return {text_id(row.get("blockid")): row.to_dict() for _, row in frame.iterrows()}


def selected_numbers(row: dict[str, Any] | None, columns: tuple[str, ...]) -> dict[str, Any]:
    row = row or {}
    return {column: number(row.get(column)) for column in columns}


def soil_details(stats: dict[str, Any] | None) -> dict[str, Any]:
    stats = stats or {}

    def continuous(kind: str) -> dict[str, Any]:
        values = stats.get(kind) or [None] * 8
        values = list(values) + [None] * max(0, 8 - len(values))
        return {
            "mean_pct": number(values[0], 2),
            "sd_pct": number(values[1], 2),
            "p10_pct": number(values[2], 2),
            "p50_pct": number(values[3], 2),
            "p90_pct": number(values[4], 2),
            "inner10_mean_pct": number(values[5], 2),
            "coverage_pct": number(values[6], 2),
            "pixels_valid": int(values[7]) if number(values[7]) is not None else None,
        }

    organic = list(stats.get("organic") or [])
    organic += [None] * max(0, 12 - len(organic))
    return {
        "clay": continuous("clay"),
        "silt": continuous("silt"),
        "sand": continuous("sand"),
        "organic": {
            "mode_code": number(organic[0], 0),
            "ge20_share_pct": number(organic[1], 2),
            "coverage_pct": number(organic[2], 2),
            "pixels_valid": int(organic[3]) if number(organic[3]) is not None else None,
        },
    }


def assert_public_keys(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for field, child in value.items():
            if FORBIDDEN_PUBLIC_KEYS.search(str(field)):
                raise RuntimeError(f"Monetärt/internt fält läckte till publik export: {path}.{field}")
            assert_public_keys(child, f"{path}.{field}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_public_keys(child, f"{path}[{index}]")


def crop_names(path: Path) -> dict[str, str]:
    frame = read_csv(path, ("crop_code", "crop_name_reference_2026"))
    return {
        text_id(row["crop_code"]): str(row["crop_name_reference_2026"])
        for _, row in frame.iterrows()
    }


def land_use(crop_code: str) -> dict[str, str | int]:
    """Conservative 2025 land-use gate for the public arable-value index."""
    try:
        code = int(float(crop_code))
    except (TypeError, ValueError):
        return {
            "year": CROP_YEAR,
            "group": "unknown",
            "label": "Okänd markanvändning",
            "arable_applicability": "unknown",
            "arable_reason": "Grödkod 2025 saknas; åkermark kan inte verifieras.",
            "akervarde_applicability": "unknown",
            "akervarde_reason": "Grödkod 2025 saknas; åkermark kan inte verifieras.",
        }
    if code in PASTURE_MEADOW_CODES:
        return {
            "year": CROP_YEAR,
            "group": "pasture",
            "label": "Betesmark/slåtteräng (inte åker)",
            "arable_applicability": "not_applicable",
            "arable_reason": "Skiftet är registrerat som betesmark/slåtteräng 2025 och ligger utanför ÅkerPass målpopulation för åkermark.",
            "akervarde_applicability": "not_applicable",
            "akervarde_reason": "Betesmark/slåtteräng ligger utanför ÅkerVärdes målpopulation.",
        }
    if code in OTHER_NON_ARABLE_CODES:
        return {
            "year": CROP_YEAR,
            "group": "other_non_arable",
            "label": "Annan markanvändning (inte åker)",
            "arable_applicability": "not_applicable",
            "arable_reason": "Markanvändningen 2025 ligger utanför ÅkerPass målpopulation för åkermark.",
            "akervarde_applicability": "not_applicable",
            "akervarde_reason": "Markanvändningen ligger utanför ÅkerVärdes målpopulation.",
        }
    return {
        "year": CROP_YEAR,
        "group": "arable",
        "label": "Åkermark",
        "arable_applicability": "applicable",
        "arable_reason": "",
        "akervarde_applicability": "applicable",
        "akervarde_reason": "",
    }


def score_status(score_row: dict[str, Any]) -> tuple[str, str]:
    if number(score_row.get("akerscore_soil_p50")) is not None:
        return "ok", ""
    total = number(score_row.get("soil_pixels_total"), 0)
    valid = number(score_row.get("soil_pixels_valid"), 0)
    if total is not None and total <= 0:
        return "no_mapped_soil_pixels", "Skiftet innehåller ingen jordpixel vars centrum ligger inom skiftesgränsen."
    if valid is not None and valid < 3:
        return "insufficient_valid_soil_pixels", "Färre än tre giltiga 20-meters jordpixlar finns för skiftet."
    return "score_missing", "ÅkerScore kunde inte beräknas från tillgängliga jorddata."


def build_field_feature(
    source: dict[str, Any], municipality: str, soil: dict[str, Any],
    geometry: dict[str, dict[str, Any]], score: dict[str, dict[str, Any]],
    value: dict[str, dict[str, Any]], drift: dict[str, dict[str, Any]],
    topography: dict[str, dict[str, Any]],
    hydrology: dict[str, dict[str, Any]], crops: dict[str, str],
) -> dict[str, Any]:
    original = source.get("properties") or {}
    blockid = text_id(original.get("blockid"))
    skifte = text_id(original.get("skiftesbeteckning"))
    field_key = key(blockid, skifte)
    missing_sources = [
        label for label, lookup in (
            ("Geometry V1a", geometry), ("ÅkerScore v0c", score),
            ("ÅkerVärde", value), ("ÅkerDrift Hybrid RC1", drift),
        )
        if field_key not in lookup
    ]
    if missing_sources:
        raise RuntimeError(f"{municipality} {field_key}: saknas i " + ", ".join(missing_sources))
    geom = geometry.get(field_key, {})
    score_row = score.get(field_key, {})
    value_row = value.get(field_key, {})
    drift_row = drift.get(field_key, {})
    original_crop = original.get("grdkod_mar")
    crop_code = text_id(original_crop if number(original_crop) is not None else geom.get("crop_code"))
    use = land_use(crop_code)
    score_state, score_reason = score_status(score_row)
    arable_is_applicable = use["arable_applicability"] == "applicable"
    if not arable_is_applicable:
        score_state = (
            "not_applicable_land_use"
            if use["arable_applicability"] == "not_applicable"
            else "unknown_land_use"
        )
        score_reason = use["arable_reason"]
    value_is_applicable = use["akervarde_applicability"] == "applicable"
    historic_class = number(score_row.get("historic_class_qa"), 0)
    historic_class_status = "class_5_10" if historic_class is not None else "not_in_imported_class_5_10"
    area = first_number(geom.get("area_ha"), score_row.get("area_ha"), original.get("ansokt_areal_ha"), digits=4)

    props = {
        "id": field_key,
        "block_id": blockid,
        "skifte_id": skifte,
        "kommun": municipality,
        "area_ha": area,
        "akerscore": number(score_row.get("akerscore_soil_p50"), 2) if arable_is_applicable else None,
        "akerscore_p10": number(score_row.get("akerscore_soil_p10"), 2) if arable_is_applicable else None,
        "akerscore_p90": number(score_row.get("akerscore_soil_p90"), 2) if arable_is_applicable else None,
        "akervarde": number(value_row.get("akervarde"), 2) if value_is_applicable else None,
        "akervarde_p10": number(value_row.get("akervarde_p10"), 2) if value_is_applicable else None,
        "akervarde_p90": number(value_row.get("akervarde_p90"), 2) if value_is_applicable else None,
        "akervarde_applicability": use["akervarde_applicability"],
        "akervarde_applicability_reason": use["akervarde_reason"],
        "akerdrift": number(drift_row.get("akerdrift_score"), 2) if arable_is_applicable else None,
        "akerdrift_status": (
            str(drift_row.get("drift_status") or "MISSING")
            if arable_is_applicable
            else (
                "NOT_APPLICABLE_LAND_USE"
                if use["arable_applicability"] == "not_applicable"
                else "UNKNOWN_LAND_USE"
            )
        ),
        "akerdrift_applicability": use["arable_applicability"],
        "akerdrift_applicability_reason": use["arable_reason"],
        "akerdrift_details": ({
            **selected_numbers(drift_row, DRIFT_FIELDS),
            "drift_twi_status": str(drift_row.get("drift_twi_status") or "MISSING"),
            "score_source": str(drift_row.get("drift_score_source") or "NOT_SCORED"),
            "fast_v1_score": number(drift_row.get("fast_v1_akerdrift_score"), 2),
            "hybrid_delta_vs_v1": number(drift_row.get("score_delta_hybrid_minus_v1"), 2),
        } if arable_is_applicable else {
            "score_source": "NOT_APPLICABLE_LAND_USE"
            if use["arable_applicability"] == "not_applicable"
            else "UNKNOWN_LAND_USE"
        }),
        "akerscore_status": score_state,
        "akerscore_status_reason": score_reason,
        "historic_class": historic_class,
        "historic_class_status": historic_class_status,
        "historic_class_status_label": (
            "Historisk klass 5–10 identifierad"
            if historic_class is not None
            else "Ej klass 5–10 i importerat 1971-underlag"
        ),
        "crop_year": CROP_YEAR,
        "crop_code": crop_code or None,
        "crop_name": crops.get(crop_code),
        "land_use_group": use["group"],
        "land_use_label": use["label"],
        "arable_applicability": use["arable_applicability"],
        "arable_applicability_reason": use["arable_reason"],
        "soil": soil_details(soil.get(field_key)),
        "topography": selected_numbers(topography.get(blockid), TOPOGRAPHY_FIELDS),
        "hydrology": selected_numbers(hydrology.get(blockid), HYDROLOGY_FIELDS),
        "geometry_metrics": selected_numbers(geom, GEOMETRY_FIELDS),
        "qa": {
            "soil_coverage_pct": number(score_row.get("soil_coverage_pct"), 2),
            "soil_pixels_total": number(score_row.get("soil_pixels_total"), 0),
            "soil_pixels_valid": number(score_row.get("soil_pixels_valid"), 0),
            "inside_block_pct": number(original.get("inside_pct"), 2),
            "alignment_warning": bool(original.get("alignment_warning", False)),
        },
        "model_versions": {
            "akerscore": SCORE_VERSION,
            "akervarde": str(value_row.get("akervarde_model_version") or VALUE_VERSION),
            "akerdrift": str(drift_row.get("drift_model_version") or DRIFT_VERSION),
            "dataset": DATASET_VERSION,
        },
        "data_scope": {
            "soil": "skifte", "geometry": "skifte", "akerdrift": "skifte",
            "topography": "block", "hydrology": "block",
        },
    }
    return {"type": "Feature", "id": field_key, "properties": props, "geometry": source.get("geometry")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/local_paths.json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / args.config)
    build_dir = root / config.get("build_dir", "data/derived")
    dist_dir = root / config.get("dist_dir", "dist")
    public_dir = build_dir / "akerpass_public_v1"
    derived_chunks = public_dir / "municipalities"
    dist_chunks = dist_dir / "data" / "municipalities"
    derived_chunks.mkdir(parents=True, exist_ok=True)
    dist_chunks.mkdir(parents=True, exist_ok=True)

    geometry_payload_path = build_dir / "geometry_payload.json"
    soil_payload_path = build_dir / "soil_payload.json"
    if not geometry_payload_path.exists() or not soil_payload_path.exists():
        raise FileNotFoundError("Saknar geometry_payload.json eller soil_payload.json. Kör ÅkerSync-databygget först.")
    geometry_payload = json.loads(geometry_payload_path.read_text(encoding="utf-8"))
    soil_payload = json.loads(soil_payload_path.read_text(encoding="utf-8"))

    geometry_frame = read_csv(build_dir / "geometry_v1a_skiften.csv", ("blockid", "skiftesbeteckning", "kommun"))
    score_frame = read_csv(
        build_dir / "akerscore_soil_v0c" / "akerscore_soil_skiften.csv",
        ("blockid", "skiftesbeteckning", "akerscore_soil_p10", "akerscore_soil_p50", "akerscore_soil_p90"),
    )
    value_frame = read_csv(
        public_dir / "akervarde_public_skiften.csv",
        ("blockid", "skiftesbeteckning", "akervarde", "akervarde_p10", "akervarde_p90"),
    )
    drift_frame = read_parquet(
        build_dir / "akerdrift_fast_v2_hybrid_rc1" / "akerdrift_fast_v2_hybrid_rc1_skane.parquet",
        (
            "block_id", "skifte_id", "akerdrift_score", "drift_status",
            "drift_model_version", "drift_score_source",
        ),
    ).rename(columns={"block_id": "blockid", "skifte_id": "skiftesbeteckning"})
    topo_frame = read_csv(build_dir / "topography_features_blocks.csv", ("blockid",))
    hydro_frame = read_csv(build_dir / "hydrology_features_final.csv", ("blockid",))

    geometry_lookup = rows_by_field(geometry_frame)
    score_lookup = rows_by_field(score_frame)
    value_lookup = rows_by_field(value_frame)
    drift_lookup = rows_by_field(drift_frame)
    topography_lookup = rows_by_block(topo_frame)
    hydrology_lookup = rows_by_block(hydro_frame)
    crops = crop_names(root / "data" / "reference" / "grodkoder_2026_reference.csv")

    manifest: dict[str, Any] = {}
    total_fields = 0
    total_blocks = 0
    missing_score = 0
    missing_value = 0
    missing_drift = 0
    value_not_applicable = 0
    arable_not_applicable = 0
    for municipality, code in MUN_CODES.items():
        if municipality not in geometry_payload:
            raise RuntimeError(f"geometry_payload saknar kommunen {municipality}")
        source = geometry_payload[municipality]
        municipality_soil = (soil_payload.get(municipality) or {}).get("skiften") or {}
        fields = []
        for feature in source["skiften"]["features"]:
            public_feature = build_field_feature(
                feature, municipality, municipality_soil, geometry_lookup, score_lookup,
                value_lookup, drift_lookup, topography_lookup, hydrology_lookup, crops,
            )
            applicability = public_feature["properties"]["arable_applicability"]
            if applicability != "applicable":
                arable_not_applicable += 1
            elif public_feature["properties"]["akerscore"] is None:
                missing_score += 1
            if public_feature["properties"]["akervarde_applicability"] != "applicable":
                value_not_applicable += 1
            elif public_feature["properties"]["akervarde"] is None:
                missing_value += 1
            if applicability == "applicable" and public_feature["properties"]["akerdrift"] is None:
                missing_drift += 1
            fields.append(public_feature)

        blocks = []
        for feature in source["blocks"]["features"]:
            blockid = text_id((feature.get("properties") or {}).get("blockid"))
            blocks.append({
                "type": "Feature", "id": blockid,
                "properties": {"block_id": blockid},
                "geometry": feature.get("geometry"),
            })

        document = {
            "schema_version": 1,
            "dataset_version": DATASET_VERSION,
            "municipality": municipality,
            "fields": {"type": "FeatureCollection", "features": fields},
            "blocks": {"type": "FeatureCollection", "features": blocks},
        }
        assert_public_keys(document)
        filename = f"{code}_{safe_slug(municipality)}.json"
        derived_path = derived_chunks / filename
        derived_path.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        shutil.copyfile(derived_path, dist_chunks / filename)
        manifest[municipality] = {
            "code": code,
            "file": f"data/municipalities/{filename}",
            "fields": len(fields),
            "blocks": len(blocks),
        }
        total_fields += len(fields)
        total_blocks += len(blocks)
        print(f"  {municipality:16s} {len(fields):6,d} skiften · {len(blocks):5,d} block")

    if len(manifest) != 33:
        raise RuntimeError(f"Förväntade 33 kommuner, fick {len(manifest)}")
    manifest_doc = {
        "schema_version": 1,
        "dataset_version": DATASET_VERSION,
        "akerdrift_model_version": DRIFT_VERSION,
        "municipality_count": len(manifest),
        "field_count": total_fields,
        "block_count": total_blocks,
        "municipalities": manifest,
    }
    for path in (public_dir / "municipalities.json", dist_dir / "municipalities.json"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"PUBLIC DATA: OK · 33 kommuner · {total_fields:,} skiften · {total_blocks:,} block")
    print(
        f"Saknade ÅkerScore: {missing_score:,} · "
        f"ÅkerScore/ÅkerDrift ej tillämpligt eller okänd markanvändning: {arable_not_applicable:,} · "
        f"saknade ÅkerVärde inom målpopulation: {missing_value:,} · "
        f"ÅkerVärde ej tillämpligt/okänd markanvändning: {value_not_applicable:,} · "
        f"saknade ÅkerDrift: {missing_drift:,}"
    )
    print("Monetära publika fält: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
