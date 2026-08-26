#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""STOPPUNKT B: geometry-only 2015/2020 -> 2025 Skurup mapping prototype."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from common import load_config, sha256_file
from akerminne_mapping_core import MatchingConfig, map_fields

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "akerminne_v1a.json"
DEFAULT_LOCAL = ROOT / "config" / "akerminne_local.json"
DEFAULT_PROJECT_LOCAL = ROOT / "config" / "local_paths.json"
DEFAULT_OUT = ROOT / "data" / "derived" / "akerminne_v1a" / "mapping_prototype"


def _read_region(path: Path, code: str, layer: str | None = None) -> gpd.GeoDataFrame:
    kwargs: dict[str, Any] = {}
    if layer:
        kwargs["layer"] = layer
    try:
        g = gpd.read_file(path, where=f"CAST(region_kod AS TEXT) LIKE '{code}%'") if not kwargs else gpd.read_file(path, where=f"CAST(region_kod AS TEXT) LIKE '{code}%'", **kwargs)
        if len(g):
            return g
    except Exception:
        pass
    g = gpd.read_file(path, **kwargs)
    if "region_kod" not in g.columns:
        raise RuntimeError(f"region_kod saknas i {path}; pilotfil eller blockkoppling krävs")
    return g[g["region_kod"].astype(str).str.startswith(code)].copy()


def read_current_skurup(project_cfg: dict[str, Any], municipality_code: str) -> gpd.GeoDataFrame:
    spath = Path(project_cfg["skiften"])
    if not spath.exists():
        raise FileNotFoundError(spath)
    try:
        return _read_region(spath, municipality_code)
    except RuntimeError:
        bpath = Path(project_cfg["blocks"])
        blocks = _read_region(bpath, municipality_code)
        allowed = set(blocks["blockid"].astype(str))
        bbox = tuple(float(v) for v in blocks.total_bounds)
        g = gpd.read_file(spath, bbox=bbox)
        return g[g["blockid"].astype(str).isin(allowed)].copy()


def historical_path(raw_root: Path, year: int) -> Path:
    return raw_root / "akerminne_v1a" / str(year) / f"arslager_skifte_skurup_{year}.gpkg"


def _atomic_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp.parquet")
    tmp.unlink(missing_ok=True)
    df.to_parquet(tmp, index=False)
    check = pd.read_parquet(tmp)
    if list(check.columns) != list(df.columns) or len(check) != len(df):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Parquet-verifiering misslyckades för {path.name}")
    path.unlink(missing_ok=True)
    tmp.replace(path)


def _quantiles(series: pd.Series) -> dict[str, float]:
    return {str(q): float(series.quantile(q)) for q in (0, .1, .25, .5, .75, .9, .99, 1)}


def write_markdown(report: dict[str, Any], path: Path) -> None:
    m = report["matching_config"]
    lines = [
        "# ÅkerMinne v1a – mapping prototype – STOPPUNKT B",
        "",
        f"Generated: `{report['generated_at_utc']}`",
        "",
        "This stage is geometry/identity only. Crop enrichment and UI are not implemented.",
        "",
        "## Matching contract",
        "",
        f"- Reference year: `{report['reference_year']}`",
        f"- Municipality: `{report['municipality']}`",
        f"- Strict 1:1 threshold: `min(F_C,F_H) >= {m['strict_min_fraction']}`",
        f"- Relaxed A/B threshold: `max(F_C,F_H) >= {m['relaxed_max_fraction']}`",
        f"- Primary correspondence: maximum exact intersection area; centroid distance is tie-break metadata only.",
        f"- Near-tie flag: relative difference <= `{m['tie_relative_fraction']}`",
        "- Same administrative id never overrides geometry topology.",
        "- All positive raw intersections are retained even when they fail the relaxed match threshold.",
        "",
        "## Results",
        "",
        "| Historical year | Current fields | Historical fields | Positive overlaps | direct_id | 1:1 strict | 1:1 relaxed | split | merge | ambiguous | unmatched | coverage P50 | anomalies >1 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for y in report["years"]:
        r = report["years"][y]
        c = r["match_counts"]
        lines.append(
            f"| {y} | {r['current_fields']} | {r['historical_fields']} | {r['positive_area_pairs']} | "
            f"{c.get('direct_id',0)} | {c.get('one_to_one_strict',0)} | {c.get('one_to_one_relaxed',0)} | "
            f"{c.get('split',0)} | {c.get('merge',0)} | {c.get('ambiguous',0)} | {c.get('unmatched',0)} | "
            f"{r['coverage_quantiles']['0.5']:.4f} | {r['overlap_anomaly_count']} |"
        )
    lines += [
        "",
        "## Interpretation guardrails",
        "",
        "- `split`: one historical polygon is geometrically linked to multiple 2025 polygons.",
        "- `merge`: multiple historical polygons are geometrically linked to one 2025 polygon.",
        "- `ambiguous`: many-to-many topology or a near-tied primary overlap.",
        "- `unmatched`: no positive overlap, or all overlaps are below the configured relaxed criterion.",
        "- `coverage_raw` is not clipped and may exceed 1 when historical polygons overlap; those cases are flagged.",
        "",
        "## STOPPUNKT B",
        "",
        "Return this report and the console/log output. Do not start full 2015–2025 processing until these real-data distributions have been reviewed.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--local-config", default=str(DEFAULT_LOCAL))
    ap.add_argument("--project-local-config", default=str(DEFAULT_PROJECT_LOCAL))
    ap.add_argument("--years", default="2015,2020")
    ap.add_argument("--output", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    cfg = load_config(args.config)
    local_cfg = load_config(args.local_config)
    project_cfg = load_config(args.project_local_config)
    years = [int(x.strip()) for x in args.years.split(",") if x.strip()]
    if not years:
        raise ValueError("Minst ett historiskt år krävs")

    mc = cfg.get("identity_matching") or {}
    matching_cfg = MatchingConfig(
        strict_min_fraction=float(mc.get("strict_min_fraction", 0.90)),
        relaxed_max_fraction=float(mc.get("relaxed_max_fraction", 0.50)),
        tie_relative_fraction=float(mc.get("tie_relative_fraction", 0.02)),
    )
    matching_cfg.validate()

    municipality = str(cfg["pilot_municipality"])
    municipality_code = str(cfg["pilot_municipality_code"])
    reference_year = int(cfg["reference_year"])
    raw_root = Path(local_cfg["raw_root"])
    outdir = Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print("ÅkerMinne v1a · geometry mapping prototype · STOPPUNKT B")
    print("=" * 78)
    print(f"Municipality: {municipality} ({municipality_code})")
    print(f"Reference year: {reference_year}")
    print(f"Historical years: {', '.join(map(str, years))}")
    print(f"Thresholds: strict min={matching_cfg.strict_min_fraction:.2f}; relaxed max={matching_cfg.relaxed_max_fraction:.2f}; tie={matching_cfg.tie_relative_fraction:.2f}")

    current = read_current_skurup(project_cfg, municipality_code)
    print(f"2025 current fields: {len(current):,}")

    report: dict[str, Any] = {
        "schema_version": "akerminne-mapping-prototype-v1a",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "municipality": municipality,
        "municipality_code": municipality_code,
        "reference_year": reference_year,
        "historical_years": years,
        "matching_config": {
            "strict_min_fraction": matching_cfg.strict_min_fraction,
            "relaxed_max_fraction": matching_cfg.relaxed_max_fraction,
            "tie_relative_fraction": matching_cfg.tie_relative_fraction,
            "strict_rule": "min(F_C,F_H)",
            "relaxed_rule": "max(F_C,F_H)",
            "primary_rule": "maximum_intersection_area",
            "centroid_role": "tie_break_metadata_only",
        },
        "years": {},
    }

    for year in years:
        hpath = historical_path(raw_root, year)
        if not hpath.exists():
            raise FileNotFoundError(f"Historisk pilotfil saknas: {hpath}. Kör RUN_AKERMINNE_PILOT_DATA.bat först.")
        historical = _read_region(hpath, municipality_code)
        print("\n" + "-" * 78)
        print(f"{year} -> {reference_year}: historical fields {len(historical):,}")
        matches, edges, qa = map_fields(current, historical, matching_cfg)
        matches.insert(0, "history_year", year)
        matches.insert(0, "reference_year", reference_year)
        matches.insert(0, "municipality", municipality)
        edges.insert(0, "history_year", year)
        edges.insert(0, "reference_year", reference_year)
        edges.insert(0, "municipality", municipality)

        ydir = outdir / str(year)
        mp = ydir / "current_matches.parquet"
        ep = ydir / "pair_overlaps.parquet"
        _atomic_parquet(matches, mp)
        _atomic_parquet(edges, ep)

        counts = {str(k): int(v) for k, v in matches["match_confidence"].value_counts().sort_index().items()}
        yr = {
            "historical_source": str(hpath),
            "historical_source_sha256": sha256_file(hpath),
            "current_fields": int(len(matches)),
            "historical_fields": int(len(historical)),
            "candidate_pairs": int(qa["candidate_pairs"]),
            "positive_area_pairs": int(len(edges)),
            "match_counts": counts,
            "coverage_quantiles": _quantiles(matches["coverage_raw"]),
            "primary_f_current_quantiles": _quantiles(matches["primary_f_current"]),
            "primary_f_historical_quantiles": _quantiles(matches["primary_f_historical"]),
            "overlap_anomaly_count": int(matches["overlap_anomaly"].sum()),
            "repaired_current_geometries": int(qa["current"]["repaired"]),
            "repaired_historical_geometries": int(qa["historical"]["repaired"]),
            "failed_current_geometries": int(qa["current"]["failed"]),
            "failed_historical_geometries": int(qa["historical"]["failed"]),
            "current_matches_path": str(mp),
            "current_matches_sha256": sha256_file(mp),
            "pair_overlaps_path": str(ep),
            "pair_overlaps_sha256": sha256_file(ep),
        }
        report["years"][str(year)] = yr
        print("Match counts:", json.dumps(counts, sort_keys=True))
        print(f"coverage_raw P50={yr['coverage_quantiles']['0.5']:.4f}; P10={yr['coverage_quantiles']['0.1']:.4f}; P90={yr['coverage_quantiles']['0.9']:.4f}")
        print(f"overlap anomalies >1: {yr['overlap_anomaly_count']}")
        print(f"geometry repaired current/historical: {yr['repaired_current_geometries']}/{yr['repaired_historical_geometries']}")

    jpath = outdir / "mapping_prototype_report.json"
    mpath = outdir / "mapping_prototype_report.md"
    jpath.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(report, mpath)

    print("\n" + "=" * 78)
    print("MAPPING PROTOTYPE: PASS")
    print("=" * 78)
    print("Report MD:", mpath)
    print("Report JSON:", jpath)
    print("STOPPUNKT B: returnera konsol/logg + mapping_prototype_report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
