#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build one municipality for the resumable ÅkerMinne Skåne batch.

The 2025 field geometry is the fixed reference. Historical 2015-2024 fields
are mapped geographically using the frozen v1a matching thresholds. Official
year-specific crop names are loaded from the materialized verified tables.
Final statuses use the frozen Skurup thresholds.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from common import load_config, sha256_file
from akerminne_mapping_core import MatchingConfig
from akerminne_history_core import CropRegistry, build_history_year, build_reference_year
from akerminne_status_core import HistoryStatusConfig, apply_history_status

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "akerminne_v1a.json"
DEFAULT_LOCAL = ROOT / "config" / "akerminne_local.json"
DEFAULT_PROJECT = ROOT / "config" / "local_paths.json"
DEFAULT_SKANE = ROOT / "data" / "derived" / "akerminne_v1a" / "skane"
EXPECTED_YEARS = list(range(2015, 2026))
SCHEMA_VERSION = "akerminne-municipality-v1a-r1"


def _slug(text: str) -> str:
    trans = str.maketrans({"å": "a", "ä": "a", "ö": "o", "Å": "a", "Ä": "a", "Ö": "o"})
    s = str(text).translate(trans).lower()
    return "".join(ch if ch.isalnum() else "_" for ch in s).strip("_")


def _read_region(path: Path, code: str, layer: str | None = None) -> gpd.GeoDataFrame:
    kwargs: dict[str, Any] = {}
    if layer:
        kwargs["layer"] = layer
    try:
        g = gpd.read_file(path, where=f"CAST(region_kod AS TEXT) LIKE '{code}%'", **kwargs)
        if len(g):
            return g
    except Exception:
        pass
    g = gpd.read_file(path, **kwargs)
    if "region_kod" not in g.columns:
        raise RuntimeError(f"region_kod missing in {path}")
    return g[g["region_kod"].astype(str).str.startswith(code)].copy()


def read_current(project_cfg: dict[str, Any], code: str) -> gpd.GeoDataFrame:
    spath = Path(project_cfg["skiften"])
    try:
        return _read_region(spath, code)
    except RuntimeError:
        bpath = Path(project_cfg["blocks"])
        blocks = _read_region(bpath, code)
        allowed = set(blocks["blockid"].astype(str))
        bbox = tuple(float(v) for v in blocks.total_bounds)
        g = gpd.read_file(spath, bbox=bbox)
        return g[g["blockid"].astype(str).isin(allowed)].copy()


def historical_path(raw_root: Path, municipality: str, year: int) -> Path:
    safe = municipality.lower().replace(" ", "_")
    return raw_root / "akerminne_v1a" / str(year) / f"arslager_skifte_{safe}_{year}.gpkg"


def _atomic_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp.parquet")
    tmp.unlink(missing_ok=True)
    df.to_parquet(tmp, index=False)
    check = pd.read_parquet(tmp)
    if len(check) != len(df) or list(check.columns) != list(df.columns):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Parquet write verification failed: {path}")
    path.unlink(missing_ok=True)
    tmp.replace(path)


def _atomic_json(doc: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    path.unlink(missing_ok=True)
    tmp.replace(path)


def _checkpoint_paths(out_dir: Path, year: int) -> tuple[Path, Path, Path]:
    d = out_dir / "checkpoints" / str(year)
    return d / "year_summary.parquet", d / "components.parquet", d / "checkpoint_manifest.json"


def _checkpoint_valid(summary_path: Path, comp_path: Path, manifest_path: Path, expected: dict[str, Any]) -> bool:
    try:
        if not summary_path.exists() or not comp_path.exists() or not manifest_path.exists():
            return False
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for key, value in expected.items():
            if manifest.get(key) != value:
                return False
        s = pd.read_parquet(summary_path)
        c = pd.read_parquet(comp_path)
        if len(s) != int(manifest["summary_rows"]) or len(c) != int(manifest["component_rows"]):
            return False
        return {"current_field_id", "history_year", "coverage_raw", "status"}.issubset(s.columns)
    except Exception:
        return False


def _crop_table_hash(crop_dir: Path, year: int) -> str:
    path = crop_dir / f"crop_codes_{year}.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    return sha256_file(path)


def _unknown_rows(components: pd.DataFrame) -> pd.DataFrame:
    cols = ["history_year", "crop_code_raw", "crop_subcategory_raw", "component_rows", "current_field_count", "intersection_m2"]
    if components.empty or "crop_known" not in components.columns:
        return pd.DataFrame(columns=cols)
    x = components[(~components["crop_known"]) & components["crop_code_raw"].notna()].copy()
    if x.empty:
        return pd.DataFrame(columns=cols)
    return (
        x.groupby(["history_year", "crop_code_raw", "crop_subcategory_raw"], dropna=False)
        .agg(component_rows=("current_field_id", "size"), current_field_count=("current_field_id", "nunique"), intersection_m2=("intersection_m2", "sum"))
        .reset_index()
        .sort_values(["history_year", "crop_code_raw", "crop_subcategory_raw"], kind="mergesort")
    )


def _validate_final(classified: pd.DataFrame, components: pd.DataFrame, current_fields: int, status_cfg: HistoryStatusConfig) -> None:
    expected_rows = current_fields * len(EXPECTED_YEARS)
    if len(classified) != expected_rows:
        raise RuntimeError(f"Expected {expected_rows:,} field-years, got {len(classified):,}")
    years = sorted(map(int, classified["history_year"].unique()))
    if years != EXPECTED_YEARS:
        raise RuntimeError(f"Expected years {EXPECTED_YEARS}, got {years}")
    counts = classified.groupby("current_field_id")["history_year"].nunique()
    if len(counts) != current_fields or not (counts == 11).all():
        raise RuntimeError("Every current field must have exactly 11 year rows")
    current = classified[classified["history_year"] == 2025]
    if len(current) != current_fields or not (current["status"] == "SINGLE_CROP").all():
        raise RuntimeError("Invalid 2025 reference rows")
    if (current["coverage_display"].astype(float) - 1.0).abs().max() > 1e-9:
        raise RuntimeError("All 2025 reference rows must have coverage 1")
    allowed = {"SINGLE_CROP", "MIXED_CROPS", "PARTIAL_COVERAGE", "NO_PUBLIC_MATCH"}
    bad = sorted(set(classified["status"].astype(str)) - allowed)
    if bad:
        raise RuntimeError(f"Unexpected statuses: {bad}")
    h = classified[classified["history_year"] < 2025]
    no = h[h["status"] == "NO_PUBLIC_MATCH"]
    if len(no) and (no["coverage_display"].astype(float) >= status_cfg.minimum_match_coverage).any():
        raise RuntimeError("NO_PUBLIC_MATCH above frozen minimum coverage")
    partial = h[h["status"] == "PARTIAL_COVERAGE"]
    if len(partial):
        c = partial["coverage_display"].astype(float)
        if ((c < status_cfg.minimum_match_coverage) | (c >= status_cfg.complete_coverage_min)).any():
            raise RuntimeError("PARTIAL_COVERAGE outside frozen coverage interval")
    if len(components) and components["history_year"].astype(int).min() < 2015:
        raise RuntimeError("Component year below ÅkerMinne contract")


def _write_report(manifest: dict[str, Any], path: Path) -> None:
    lines = [
        f"# ÅkerMinne v1a – {manifest['municipality']} ({manifest['municipality_code']})", "",
        f"Generated: `{manifest['generated_at_utc']}`", "",
        f"- Current 2025 fields: **{manifest['current_fields']:,}**",
        f"- Field-years: **{manifest['field_years']:,}**",
        f"- Raw crop components: **{manifest['component_rows']:,}**",
        f"- Unknown official crop combinations: **{manifest['unknown_crop_combinations']:,}**", "",
        "## Historical status 2015–2024", "",
    ]
    for key in ("SINGLE_CROP", "MIXED_CROPS", "PARTIAL_COVERAGE", "NO_PUBLIC_MATCH"):
        lines.append(f"- `{key}`: {manifest['historical_status_counts'].get(key, 0):,}")
    lines += ["", "## Identity mapping 2015–2024", ""]
    for key, value in sorted(manifest["historical_identity_counts"].items()):
        lines.append(f"- `{key}`: {value:,}")
    lines += ["", "## Guardrails", "", "- 2025 is the fixed current-field reference and is not self-intersected.", "- Strict 1:1, split/merge and tie rules are the frozen ÅkerMinne v1a rules.", "- Raw positive intersections are preserved.", "- Frozen status thresholds are 1% material match, 95% complete coverage, 5% second crop, 1% web-visible crop component.", "- Crop names are year-specific and never fall back across years.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--municipality", required=True)
    ap.add_argument("--municipality-code", required=True)
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--local-config", default=str(DEFAULT_LOCAL))
    ap.add_argument("--project-local-config", default=str(DEFAULT_PROJECT))
    ap.add_argument("--skane-root", default=str(DEFAULT_SKANE))
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--force-year", type=int)
    args = ap.parse_args()

    municipality, code = str(args.municipality), str(args.municipality_code)
    if len(code) != 4 or not code.isdigit():
        raise ValueError("municipality-code must be four digits")
    cfg = load_config(args.config)
    local_cfg = load_config(args.local_config)
    project_cfg = load_config(args.project_local_config)
    skane_root = Path(args.skane_root)
    crop_dir = skane_root / "reference" / "crop_codes"
    registry, registry_meta = CropRegistry.from_directory(crop_dir)
    if registry_meta.get("loaded_years") != EXPECTED_YEARS:
        raise RuntimeError(f"Official crop registry must load all 2015-2025; got {registry_meta.get('loaded_years')}")

    mc = cfg.get("identity_matching") or {}
    matching_cfg = MatchingConfig(float(mc.get("strict_min_fraction", .9)), float(mc.get("relaxed_max_fraction", .5)), float(mc.get("tie_relative_fraction", .02)))
    matching_cfg.validate()
    status_cfg = HistoryStatusConfig.from_dict(cfg.get("history_status") or {})

    current = read_current(project_cfg, code)
    if len(current) == 0:
        raise RuntimeError(f"{municipality} ({code}): zero current 2025 fields")
    current_source = Path(project_cfg["skiften"])
    current_hash = sha256_file(current_source)
    raw_root = Path(local_cfg["raw_root"])
    out_dir = skane_root / "municipalities" / f"{code}_{_slug(municipality)}"
    out_dir.mkdir(parents=True, exist_ok=True)
    all_summary, all_components = [], []
    force_year = int(args.force_year) if args.force_year is not None else None

    print("=" * 78)
    print(f"ÅkerMinne v1a · municipality build · {municipality} ({code})")
    print("=" * 78)
    print(f"Current fields: {len(current):,}; reference year: 2025")

    year_manifests: dict[str, Any] = {}
    for year in EXPECTED_YEARS:
        t0 = time.perf_counter()
        source = current_source if year == 2025 else historical_path(raw_root, municipality, year)
        if not source.exists():
            raise FileNotFoundError(f"{year}: historical source missing: {source}")
        source_hash = current_hash if year == 2025 else sha256_file(source)
        crop_hash = _crop_table_hash(crop_dir, year)
        s_path, c_path, m_path = _checkpoint_paths(out_dir, year)
        expected = {"schema_version": "akerminne-skane-checkpoint-v1a-r1", "municipality": municipality, "municipality_code": code, "history_year": year, "source_sha256": source_hash, "current_source_sha256": current_hash, "crop_table_sha256": crop_hash}
        use_cache = bool(args.resume and force_year != year and _checkpoint_valid(s_path, c_path, m_path, expected))
        if use_cache:
            summary, components = pd.read_parquet(s_path), pd.read_parquet(c_path)
            manifest = json.loads(m_path.read_text(encoding="utf-8"))
            print(f"{year}: checkpoint OK · {len(summary):,} fields · {len(components):,} components")
        else:
            if year == 2025:
                summary, components, qa = build_reference_year(current, municipality, registry, 2025)
            else:
                historical = _read_region(source, code)
                summary, components, _edges, qa = build_history_year(current, historical, year, municipality, matching_cfg, registry, 2025)
            if len(summary) != len(current):
                raise RuntimeError(f"{year}: expected {len(current):,} fields, got {len(summary):,}")
            _atomic_parquet(summary, s_path)
            _atomic_parquet(components, c_path)
            manifest = {**expected, "summary_rows": int(len(summary)), "component_rows": int(len(components)), "summary_sha256": sha256_file(s_path), "components_sha256": sha256_file(c_path), "qa": {"current_repaired": int((qa.get("current") or {}).get("repaired", 0)), "current_failed": int((qa.get("current") or {}).get("failed", 0)), "historical_repaired": int((qa.get("historical") or {}).get("repaired", 0)), "historical_failed": int((qa.get("historical") or {}).get("failed", 0))}, "generated_at_utc": datetime.now(timezone.utc).isoformat()}
            _atomic_json(manifest, m_path)
            print(f"{year}: built · {len(summary):,} fields · {len(components):,} components")
        all_summary.append(summary)
        all_components.append(components)
        year_manifests[str(year)] = {"summary_rows": int(len(summary)), "component_rows": int(len(components)), "elapsed_seconds": round(time.perf_counter() - t0, 3), "source": str(source), "source_sha256": source_hash}

    raw_summary = pd.concat(all_summary, ignore_index=True)
    components_all = pd.concat(all_components, ignore_index=True) if all_components else pd.DataFrame()
    classified, crop_areas = apply_history_status(raw_summary, components_all, status_cfg)
    _validate_final(classified, components_all, len(current), status_cfg)

    classified_path = out_dir / "akerminne_year_summary_classified.parquet"
    components_path = out_dir / "akerminne_components.parquet"
    crop_areas_path = out_dir / "akerminne_crop_areas_grouped.parquet"
    _atomic_parquet(classified, classified_path)
    _atomic_parquet(components_all, components_path)
    _atomic_parquet(crop_areas, crop_areas_path)
    unknown = _unknown_rows(components_all)
    unknown_path = out_dir / "unknown_crop_codes.csv"
    unknown.to_csv(unknown_path, index=False, encoding="utf-8-sig")

    historical = classified[classified["history_year"] < 2025]
    status_counts = {str(k): int(v) for k, v in historical["status"].value_counts().sort_index().items()}
    identity_counts = {str(k): int(v) for k, v in historical["identity_match_confidence"].value_counts().sort_index().items()}
    manifest = {"schema_version": SCHEMA_VERSION, "generated_at_utc": datetime.now(timezone.utc).isoformat(), "municipality": municipality, "municipality_code": code, "reference_year": 2025, "years": EXPECTED_YEARS, "current_fields": int(len(current)), "field_years": int(len(classified)), "component_rows": int(len(components_all)), "grouped_crop_rows": int(len(crop_areas)), "unknown_crop_combinations": int(len(unknown)), "known_component_rows": int(components_all["crop_known"].sum()) if len(components_all) else 0, "historical_status_counts": status_counts, "historical_identity_counts": identity_counts, "matching_config": matching_cfg.__dict__, "history_status_config": status_cfg.__dict__, "crop_registry_loaded_years": registry_meta.get("loaded_years", []), "current_source": str(current_source), "current_source_sha256": current_hash, "outputs": {"classified_summary": str(classified_path), "components": str(components_path), "grouped_crop_areas": str(crop_areas_path), "unknown_crop_codes": str(unknown_path)}, "year_builds": year_manifests}
    manifest_path = out_dir / "build_manifest.json"
    _atomic_json(manifest, manifest_path)
    report_path = out_dir / "report.md"
    _write_report(manifest, report_path)

    print("=" * 78)
    print(f"AKERMINNE MUNICIPALITY: PASS · {municipality} ({code})")
    print("=" * 78)
    print(f"Fields/field-years: {len(current):,}/{len(classified):,}")
    print(f"Components: {len(components_all):,}; unknown official combinations: {len(unknown):,}")
    print(f"Status 2015-2024: {status_counts}")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
