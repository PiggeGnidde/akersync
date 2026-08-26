#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "akerminne_v1a.json"
DEFAULT_QA = ROOT / "data" / "derived" / "akerminne_v1a" / "qa"
DEFAULT_PILOT = ROOT / "data" / "derived" / "akerminne_v1a" / "pilot_skurup"
DEFAULT_OUT = ROOT / "dist" / "data" / "akerminne" / "1264_skurup.json"
SCHEMA_VERSION = "akerminne-web-v1a"
STATUS_VERSION = "akerminne-status-v1a"
EXPECTED_YEARS = list(range(2015, 2026))


def _raw(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text or None


def crop_key(year: int, code: Any, subcategory: Any) -> str:
    return f"{int(year)}|{_raw(code) or ''}|{_raw(subcategory) or ''}"


def _round(value: Any, digits: int = 5) -> float:
    return round(float(value or 0.0), digits)


def _name_lookup(components: pd.DataFrame) -> dict[str, str]:
    if components.empty:
        return {}
    required = {"history_year", "crop_code_raw", "crop_subcategory_raw", "crop_name"}
    missing = sorted(required - set(components.columns))
    if missing:
        raise ValueError(f"components missing columns {missing}")
    names: dict[str, str] = {}
    for row in components[list(required)].drop_duplicates().itertuples(index=False):
        key = crop_key(row.history_year, row.crop_code_raw, row.crop_subcategory_raw)
        name = str(row.crop_name)
        previous = names.get(key)
        if previous is not None and previous != name:
            raise ValueError(f"conflicting crop names for {key}: {previous!r} vs {name!r}")
        names[key] = name
    return dict(sorted(names.items()))


def build_payload(
    classified: pd.DataFrame,
    crop_areas: pd.DataFrame,
    components: pd.DataFrame,
    history_status_cfg: dict[str, Any],
    municipality: str = "Skurup",
    municipality_code: str = "1264",
    reference_year: int = 2025,
) -> dict[str, Any]:
    required_s = {
        "history_year", "current_field_id", "status", "coverage_display",
        "dominant_crop_code_raw", "dominant_crop_subcategory_raw",
        "first_crop_share_grouped", "second_crop_share",
        "identity_match_confidence", "material_overlap_anomaly",
    }
    required_c = {
        "history_year", "current_field_id", "crop_code_raw",
        "crop_subcategory_raw", "crop_share_current", "crop_rank",
    }
    missing_s = sorted(required_s - set(classified.columns))
    missing_c = sorted(required_c - set(crop_areas.columns))
    if missing_s:
        raise ValueError(f"classified missing columns {missing_s}")
    if missing_c:
        raise ValueError(f"crop_areas missing columns {missing_c}")

    years = sorted(int(v) for v in classified["history_year"].unique())
    if years != EXPECTED_YEARS:
        raise RuntimeError(f"expected years {EXPECTED_YEARS}, got {years}")
    counts = classified.groupby("current_field_id")["history_year"].nunique()
    if counts.empty or not (counts == len(EXPECTED_YEARS)).all():
        raise RuntimeError("every current field must have exactly 11 history years")

    visible_min = float(history_status_cfg.get("web_component_min_share", 0.01))
    visible: dict[tuple[int, str], list[list[Any]]] = {}
    kept = crop_areas[pd.to_numeric(crop_areas["crop_share_current"], errors="coerce").fillna(0.0) >= visible_min].copy()
    kept = kept.sort_values(["history_year", "current_field_id", "crop_rank"], kind="mergesort")
    for (year, field_id), group in kept.groupby(["history_year", "current_field_id"], sort=False):
        visible[(int(year), str(field_id))] = [
            [
                crop_key(int(year), row.crop_code_raw, row.crop_subcategory_raw),
                _round(row.crop_share_current, 5),
            ]
            for row in group.itertuples(index=False)
        ]

    fields: dict[str, list[dict[str, Any]]] = {}
    classified = classified.sort_values(["current_field_id", "history_year"], kind="mergesort")
    for field_id, group in classified.groupby("current_field_id", sort=True):
        history: list[dict[str, Any]] = []
        for row in group.itertuples(index=False):
            year = int(row.history_year)
            status = str(row.status)
            coverage = _round(row.coverage_display, 5)
            item: dict[str, Any] = {
                "y": year,
                "s": status,
                "c": coverage,
                "i": str(row.identity_match_confidence),
            }
            if status != "NO_PUBLIC_MATCH":
                code = _raw(row.dominant_crop_code_raw)
                sub = _raw(row.dominant_crop_subcategory_raw)
                if code is not None:
                    item["d"] = crop_key(year, code, sub)
                item["ds"] = _round(row.first_crop_share_grouped, 5)
                item["ss"] = _round(row.second_crop_share, 5)
                comps = visible.get((year, str(field_id)))
                if comps:
                    item["x"] = comps
            if bool(row.material_overlap_anomaly):
                item["m"] = True
            history.append(item)
        if [r["y"] for r in history] != EXPECTED_YEARS:
            raise RuntimeError(f"{field_id}: incomplete year sequence")
        fields[str(field_id)] = history

    return {
        "schema_version": SCHEMA_VERSION,
        "status_version": STATUS_VERSION,
        "municipality": municipality,
        "municipality_code": str(municipality_code),
        "reference_year": int(reference_year),
        "years": EXPECTED_YEARS,
        "field_count": len(fields),
        "thresholds": {
            "minimum_match": float(history_status_cfg.get("minimum_match_coverage", 0.01)),
            "complete_coverage": float(history_status_cfg.get("complete_coverage_min", 0.95)),
            "mixed_secondary_crop": float(history_status_cfg.get("mixed_secondary_crop_min_share", 0.05)),
            "visible_component": visible_min,
        },
        "crop_names": _name_lookup(components),
        "fields": fields,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--qa-dir", default=str(DEFAULT_QA))
    ap.add_argument("--pilot-dir", default=str(DEFAULT_PILOT))
    ap.add_argument("--output", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    qa = Path(args.qa_dir)
    pilot = Path(args.pilot_dir)
    classified_path = qa / "akerminne_year_summary_classified.parquet"
    crop_areas_path = qa / "akerminne_crop_areas_grouped.parquet"
    components_path = pilot / "akerminne_components.parquet"
    for path in (classified_path, crop_areas_path, components_path):
        if not path.exists():
            raise FileNotFoundError(path)

    classified = pd.read_parquet(classified_path)
    crop_areas = pd.read_parquet(crop_areas_path)
    components = pd.read_parquet(components_path)
    payload = build_payload(
        classified,
        crop_areas,
        components,
        config.get("history_status") or {},
        municipality=str(config.get("pilot_municipality", "Skurup")),
        municipality_code=str(config.get("pilot_municipality_code", "1264")),
        reference_year=int(config.get("reference_year", 2025)),
    )
    if payload["field_count"] != 2944:
        raise RuntimeError(f"expected 2,944 Skurup fields, got {payload['field_count']:,}")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".tmp.json")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    check = json.loads(tmp.read_text(encoding="utf-8"))
    if check.get("field_count") != payload["field_count"] or len(check.get("fields", {})) != payload["field_count"]:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("ÅkerMinne web payload verification failed")
    output.unlink(missing_ok=True)
    tmp.replace(output)
    print("AKERMINNE WEB DATA: OK")
    print(f"  Skurup fields: {payload['field_count']:,}")
    print(f"  Field-years: {payload['field_count'] * len(payload['years']):,}")
    print(f"  Crop labels: {len(payload['crop_names']):,}")
    print(f"  Output: {output} ({output.stat().st_size / 1024 / 1024:.2f} MiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
