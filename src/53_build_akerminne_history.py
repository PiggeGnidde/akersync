#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build full ÅkerMinne v1a raw Skurup history 2015-2025 with per-year checkpoints."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from common import load_config, sha256_file
from akerminne_mapping_core import MatchingConfig
from akerminne_history_core import (
    CropRegistry,
    build_history_year,
    build_reference_year,
    component_share_distribution,
    raw_text,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "akerminne_v1a.json"
DEFAULT_LOCAL = ROOT / "config" / "akerminne_local.json"
DEFAULT_PROJECT = ROOT / "config" / "local_paths.json"
DEFAULT_OUT = ROOT / "data" / "derived" / "akerminne_v1a"
DEFAULT_CROP_DIR = ROOT / "data" / "reference" / "akerminne_crop_codes"


def parse_years(text: str) -> list[int]:
    years: set[int] = set()
    for part in str(text).split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            a, b = [int(x.strip()) for x in part.split(":", 1)]
            step = 1 if b >= a else -1
            years.update(range(a, b + step, step))
        else:
            years.add(int(part))
    out = sorted(years)
    bad = [y for y in out if y < 2015 or y > 2025]
    if not out or bad:
        raise ValueError(f"År måste ligga inom 2015-2025; fick {out}")
    return out


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
        raise RuntimeError(f"region_kod saknas i {path}")
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


def hist_path(raw_root: Path, municipality: str, year: int) -> Path:
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
        raise RuntimeError(f"Parquet-verifiering misslyckades: {path}")
    path.unlink(missing_ok=True)
    tmp.replace(path)


def _atomic_json(doc: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    path.unlink(missing_ok=True)
    tmp.replace(path)


def _quantiles(s: pd.Series) -> dict[str, float | None]:
    if len(s) == 0:
        return {str(q): None for q in (0, .1, .25, .5, .75, .9, .99, 1)}
    return {str(q): float(s.quantile(q)) for q in (0, .1, .25, .5, .75, .9, .99, 1)}


def _git_head() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return None


def _crop_table_hash(crop_dir: Path, year: int) -> str | None:
    matches = sorted([p for p in crop_dir.glob("*.csv") if str(year) in p.stem]) if crop_dir.exists() else []
    return sha256_file(matches[0]) if len(matches) == 1 else None


def _checkpoint_paths(out_root: Path, municipality: str, year: int) -> tuple[Path, Path, Path]:
    d = out_root / "checkpoints" / municipality / str(year)
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
        required = {"current_field_id", "history_year", "coverage_raw", "dominant_crop_code_raw", "status"}
        return required.issubset(s.columns)
    except Exception:
        return False


def _unknown_rows(components_all: pd.DataFrame) -> pd.DataFrame:
    x = components_all[(~components_all["crop_known"]) & components_all["crop_code_raw"].notna()].copy()
    if x.empty:
        return pd.DataFrame(columns=[
            "history_year", "crop_code_raw", "crop_subcategory_raw",
            "component_rows", "current_field_count", "intersection_m2",
        ])
    out = (
        x.groupby(["history_year", "crop_code_raw", "crop_subcategory_raw"], dropna=False)
        .agg(
            component_rows=("current_field_id", "size"),
            current_field_count=("current_field_id", "nunique"),
            intersection_m2=("intersection_m2", "sum"),
        )
        .reset_index()
    )
    return out.sort_values(["history_year", "crop_code_raw", "crop_subcategory_raw"], kind="mergesort")


def write_report(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# ÅkerMinne v1a – full Skurup raw history – STOPPUNKT C", "",
        f"Generated: `{report['generated_at_utc']}`", "",
        "Geometry + raw crop history are complete. SINGLE/MIXED/PARTIAL thresholds are deliberately not frozen in this stage.", "",
        "## Crop dictionaries", "",
        f"Loaded official year tables: `{', '.join(map(str, report['crop_registry']['loaded_years'])) or 'none'}`", "",
        "Missing year tables never fall back to another year; names are emitted as `Okänd grödkod <kod> (<år>)`.", "",
        "## Results", "",
        "| Year | fields | components | matched | no match | overlap anomaly | unknown-code fields | coverage P50 | dominant share P50 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year in report["years"]:
        r = report["years"][year]
        lines.append(
            f"| {year} | {r['summary_rows']} | {r['component_rows']} | {r['matched_fields']} | {r['no_public_match']} | "
            f"{r['overlap_anomaly_count']} | {r['unknown_code_fields']} | {r['coverage_quantiles']['0.5']:.4f} | {r['dominant_share_quantiles']['0.5']:.4f} |"
        )
    lines += ["", "## Small-component distribution (descriptive; no sliver threshold applied)", ""]
    for year in report["years"]:
        d = report["years"][year]["component_share_distribution"]
        if not d or d.get("rows", 0) == 0:
            lines.append(f"- {year}: no components")
        else:
            lines.append(
                f"- {year}: {d['rows']} components; <0.1%={d['below_0_1pct']}, <0.5%={d['below_0_5pct']}, "
                f"<1%={d['below_1pct']}, <2%={d['below_2pct']}, <5%={d['below_5pct']}."
            )
    lines += [
        "", "## Guardrails", "",
        "- Raw component areas are preserved; no sliver is discarded.",
        "- `coverage_raw` is preserved even above 1 and flagged as `DUPLICATE_OVERLAP`.",
        "- 2025 is the reference year and is represented as an exact self-match, not by intersecting the layer with itself.",
        "- `RAW_PENDING_THRESHOLDS` means crop/coverage metrics are available but SINGLE/MIXED/PARTIAL thresholds await STOPPUNKT C review.",
        "- Missing official crop dictionaries are a naming/provenance blocker, not a geometry blocker.",
        "", "## STOPPUNKT C", "",
        "Return this report plus the runner log. Do not continue to reference-sample QA or UI before review.", "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--local-config", default=str(DEFAULT_LOCAL))
    parser.add_argument("--project-local-config", default=str(DEFAULT_PROJECT))
    parser.add_argument("--municipality", default="Skurup")
    parser.add_argument("--years", default="2015:2025")
    parser.add_argument("--output-root", default=str(DEFAULT_OUT))
    parser.add_argument("--crop-codes-dir", default=str(DEFAULT_CROP_DIR))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force-year", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    local_cfg = load_config(args.local_config)
    project_cfg = load_config(args.project_local_config)
    years = parse_years(args.years)
    force = set()
    if args.force_year is not None:
        years = sorted(set(years + [args.force_year]))
        force.add(args.force_year)
    if args.municipality != cfg["pilot_municipality"]:
        raise ValueError(f"Phase 3 är låst till pilotkommun {cfg['pilot_municipality']}")

    code = str(cfg["pilot_municipality_code"])
    reference_year = int(cfg["reference_year"])
    out_root = Path(args.output_root)
    raw_root = Path(local_cfg["raw_root"])
    crop_dir = Path(args.crop_codes_dir)
    registry, registry_meta = CropRegistry.from_directory(crop_dir)
    mc = cfg.get("identity_matching") or {}
    matching_cfg = MatchingConfig(
        float(mc.get("strict_min_fraction", .9)),
        float(mc.get("relaxed_max_fraction", .5)),
        float(mc.get("tie_relative_fraction", .02)),
    )
    matching_cfg.validate()

    current = read_current(project_cfg, code)
    current_source = Path(project_cfg["skiften"])
    current_hash = sha256_file(current_source)
    print("=" * 78)
    print("ÅkerMinne v1a · full Skurup raw history · STOPPUNKT C")
    print("=" * 78)
    print(f"Municipality: {args.municipality} ({code}); current fields={len(current):,}; years={years}")
    print(f"Crop tables loaded: {registry_meta.get('loaded_years', [])}")

    if args.dry_run:
        for year in years:
            source = current_source if year == reference_year else hist_path(raw_root, args.municipality, year)
            print(f"{year}: {'OK' if source.exists() else 'MISSING'} {source}")
        return 0

    all_summary: list[pd.DataFrame] = []
    all_components: list[pd.DataFrame] = []
    report: dict[str, Any] = {
        "schema_version": "akerminne-phase3-v1a",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git_head(),
        "municipality": args.municipality,
        "municipality_code": code,
        "reference_year": reference_year,
        "current_source": str(current_source),
        "current_source_sha256": current_hash,
        "matching_config": {
            "strict_min_fraction": matching_cfg.strict_min_fraction,
            "relaxed_max_fraction": matching_cfg.relaxed_max_fraction,
            "tie_relative_fraction": matching_cfg.tie_relative_fraction,
        },
        "crop_registry": registry_meta,
        "years": {},
    }

    for year in years:
        t0 = time.perf_counter()
        source = current_source if year == reference_year else hist_path(raw_root, args.municipality, year)
        if not source.exists():
            raise FileNotFoundError(f"År {year}: källfil saknas: {source}. Kör historisk downloader först.")
        source_hash = current_hash if year == reference_year else sha256_file(source)
        crop_hash = _crop_table_hash(crop_dir, year)
        summary_path, comp_path, manifest_path = _checkpoint_paths(out_root, args.municipality, year)
        expected = {
            "history_year": year,
            "source_sha256": source_hash,
            "current_source_sha256": current_hash,
            "crop_table_sha256": crop_hash,
        }

        if args.resume and year not in force and _checkpoint_valid(summary_path, comp_path, manifest_path, expected):
            summary = pd.read_parquet(summary_path)
            components = pd.read_parquet(comp_path)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            print(f"{year}: checkpoint OK · {len(summary):,} fields · {len(components):,} components")
        else:
            if year == reference_year:
                summary, components, qa = build_reference_year(current, args.municipality, registry, reference_year)
            else:
                historical = _read_region(source, code)
                summary, components, _edges, qa = build_history_year(
                    current, historical, year, args.municipality, matching_cfg, registry, reference_year
                )
            _atomic_parquet(summary, summary_path)
            _atomic_parquet(components, comp_path)
            qa_summary = {
                "current_repaired": int((qa.get("current") or {}).get("repaired", 0)),
                "current_failed": int((qa.get("current") or {}).get("failed", 0)),
                "historical_repaired": int((qa.get("historical") or {}).get("repaired", 0)),
                "historical_failed": int((qa.get("historical") or {}).get("failed", 0)),
            }
            manifest = {
                **expected,
                "schema_version": "akerminne-checkpoint-v1a",
                "municipality": args.municipality,
                "summary_rows": int(len(summary)),
                "component_rows": int(len(components)),
                "summary_sha256": sha256_file(summary_path),
                "components_sha256": sha256_file(comp_path),
                "qa": qa_summary,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            _atomic_json(manifest, manifest_path)
            print(f"{year}: built · {len(summary):,} fields · {len(components):,} components")

        if len(summary) != len(current):
            raise RuntimeError(f"{year}: expected {len(current):,} summary rows, got {len(summary):,}")
        all_summary.append(summary)
        all_components.append(components)
        report["years"][str(year)] = {
            "summary_rows": int(len(summary)),
            "component_rows": int(len(components)),
            "matched_fields": int((summary["component_count"] > 0).sum()),
            "no_public_match": int((summary["component_count"] == 0).sum()),
            "overlap_anomaly_count": int(summary["overlap_anomaly"].sum()),
            "unknown_code_fields": int(summary["reason_flags"].str.contains("UNKNOWN_CODE", regex=False).sum()),
            "coverage_quantiles": _quantiles(summary["coverage_raw"]),
            "dominant_share_quantiles": _quantiles(summary["dominant_crop_share"]),
            "component_share_distribution": component_share_distribution(components),
            "source": str(source),
            "source_sha256": source_hash,
            "crop_table_sha256": crop_hash,
            "geometry_qa": manifest.get("qa", {}),
            "identity_match_counts": {
                str(k): int(v) for k, v in summary["identity_match_confidence"].value_counts().sort_index().items()
            },
            "elapsed_seconds": round(time.perf_counter() - t0, 3),
        }

    summary_all = pd.concat(all_summary, ignore_index=True)
    components_all = pd.concat(all_components, ignore_index=True) if all_components else pd.DataFrame()
    expected_rows = len(current) * len(years)
    if len(summary_all) != expected_rows:
        raise RuntimeError(f"Combined summary: expected {expected_rows:,}, got {len(summary_all):,}")

    pilot = out_root / "pilot_skurup"
    pilot.mkdir(parents=True, exist_ok=True)
    summary_out = pilot / "akerminne_year_summary.parquet"
    components_out = pilot / "akerminne_components.parquet"
    _atomic_parquet(summary_all, summary_out)
    _atomic_parquet(components_all, components_out)
    unknown = _unknown_rows(components_all)
    unknown_out = pilot / "unknown_crop_codes.csv"
    unknown.to_csv(unknown_out, index=False, encoding="utf-8")

    report["combined"] = {
        "summary_rows": int(len(summary_all)),
        "expected_summary_rows": int(expected_rows),
        "component_rows": int(len(components_all)),
        "summary_path": str(summary_out),
        "summary_sha256": sha256_file(summary_out),
        "components_path": str(components_out),
        "components_sha256": sha256_file(components_out),
        "unknown_crop_code_rows": int(len(unknown)),
        "unknown_crop_codes_path": str(unknown_out),
    }
    run_manifest = out_root / "manifests" / "run_manifest_phase3.json"
    _atomic_json(report, run_manifest)
    report_md = pilot / "phase3_report.md"
    write_report(report, report_md)

    print("=" * 78)
    print("PHASE 3 RAW HISTORY: PASS")
    print("=" * 78)
    print(f"Summary rows: {len(summary_all):,} = {len(current):,} fields x {len(years)} years")
    print(f"Components: {len(components_all):,}; unknown crop combinations: {len(unknown):,}")
    print("Report:", report_md)
    print("STOPPUNKT C remains active")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
