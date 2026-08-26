#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Finalize STOPPUNKT C thresholds and build reference-sample QA for STOPPUNKT D."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from common import load_config, sha256_file
from akerminne_status_core import HistoryStatusConfig, apply_history_status

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "akerminne_v1a.json"
DEFAULT_PROJECT = ROOT / "config" / "local_paths.json"
DEFAULT_PILOT = ROOT / "data" / "derived" / "akerminne_v1a" / "pilot_skurup"
DEFAULT_QA = ROOT / "data" / "derived" / "akerminne_v1a" / "qa"


def _atomic_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp.parquet")
    tmp.unlink(missing_ok=True)
    df.to_parquet(tmp, index=False)
    check = pd.read_parquet(tmp)
    if len(check) != len(df) or list(check.columns) != list(df.columns):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Parquet verification failed: {path}")
    path.unlink(missing_ok=True)
    tmp.replace(path)


def _text(v: Any) -> str:
    if v is None or pd.isna(v):
        return ""
    s = str(v)
    return s[:-2] if s.endswith(".0") else s


def _read_current_skurup(project: dict[str, Any], code: str) -> gpd.GeoDataFrame:
    spath = Path(project["skiften"])
    try:
        g = gpd.read_file(spath, where=f"CAST(region_kod AS TEXT) LIKE '{code}%'")
        if len(g):
            return g
    except Exception:
        pass
    bpath = Path(project["blocks"])
    try:
        blocks = gpd.read_file(bpath, where=f"CAST(region_kod AS TEXT) LIKE '{code}%'")
    except Exception:
        blocks = gpd.read_file(bpath)
        blocks = blocks[blocks["region_kod"].astype(str).str.startswith(code)].copy()
    allowed = set(blocks["blockid"].astype(str))
    g = gpd.read_file(spath, bbox=tuple(float(v) for v in blocks.total_bounds))
    return g[g["blockid"].astype(str).isin(allowed)].copy()


def _distinct_pick(frame: pd.DataFrame, n: int, category: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["qa_category", "history_year", "current_field_id", "status", "coverage_display", "second_crop_share", "identity_match_confidence", "overlap_excess_raw"])
    picked = frame.drop_duplicates("current_field_id", keep="first").head(n).copy()
    picked.insert(0, "qa_category", category)
    cols = ["qa_category", "history_year", "current_field_id", "status", "coverage_display", "second_crop_share", "identity_match_confidence", "overlap_excess_raw"]
    return picked[cols]


def build_checklist(classified: pd.DataFrame) -> pd.DataFrame:
    h = classified[classified["history_year"] < 2025].copy()
    stable = h[
        (h["status"] == "SINGLE_CROP") &
        (h["identity_match_confidence"].isin(["direct_id", "one_to_one_strict"])) &
        (h["coverage_display"] >= .999) & (h["second_crop_share"] < .01) &
        (~h["material_overlap_anomaly"])
    ].sort_values(["history_year", "current_field_id"], kind="mergesort")
    topo = h[
        h["identity_match_confidence"].isin(["split", "merge"])
    ].sort_values(["history_year", "identity_match_confidence", "current_field_id"], kind="mergesort")
    mixed_partial = h[h["status"].isin(["MIXED_CROPS", "PARTIAL_COVERAGE"])].sort_values(
        ["status", "history_year", "current_field_id"], kind="mergesort")
    problem = h[
        h["material_overlap_anomaly"] |
        ((h["identity_match_confidence"].isin(["ambiguous", "unmatched"])) & (h["coverage_display"] >= .95))
    ].sort_values(["overlap_excess_raw", "history_year", "current_field_id"], ascending=[False, True, True], kind="mergesort")
    return pd.concat([
        _distinct_pick(stable, 5, "stable_simple"),
        _distinct_pick(topo, 5, "split_merge"),
        _distinct_pick(mixed_partial, 5, "mixed_partial"),
        _distinct_pick(problem, 5, "problem"),
    ], ignore_index=True)


def write_problem_geojson(checklist: pd.DataFrame, current: gpd.GeoDataFrame, path: Path) -> None:
    g = current.copy()
    g["current_field_id"] = g["blockid"].map(_text) + "|" + g["skiftesbeteckning"].map(_text)
    agg = checklist.groupby("current_field_id").agg(
        qa_categories=("qa_category", lambda x: ";".join(sorted(set(map(str, x))))),
        qa_examples=("history_year", lambda x: ";".join(map(str, sorted(set(map(int, x)))))),
    ).reset_index()
    out = g.merge(agg, on="current_field_id", how="inner", validate="one_to_one")
    keep = [c for c in ["current_field_id", "blockid", "skiftesbeteckning", "qa_categories", "qa_examples", "geometry"] if c in out.columns]
    out = out[keep].sort_values("current_field_id", kind="mergesort")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp.geojson")
    tmp.unlink(missing_ok=True)
    out.to_file(tmp, driver="GeoJSON")
    check = gpd.read_file(tmp)
    if len(check) != len(out):
        tmp.unlink(missing_ok=True)
        raise RuntimeError("problem_fields GeoJSON verification failed")
    path.unlink(missing_ok=True)
    tmp.replace(path)


def q(series: pd.Series, x: float) -> float:
    return float(series.astype(float).quantile(x))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--project-local-config", default=str(DEFAULT_PROJECT))
    ap.add_argument("--pilot-dir", default=str(DEFAULT_PILOT))
    ap.add_argument("--output", default=str(DEFAULT_QA))
    args = ap.parse_args()

    config = load_config(args.config)
    project = load_config(args.project_local_config)
    scfg = HistoryStatusConfig.from_dict(config.get("history_status") or {})
    pilot = Path(args.pilot_dir)
    outdir = Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    spath = pilot / "akerminne_year_summary.parquet"
    cpath = pilot / "akerminne_components.parquet"
    if not spath.exists() or not cpath.exists():
        raise FileNotFoundError("Phase 3 Parquet files missing; run RUN_AKERMINNE_PILOT_SKURUP.bat first")
    summary = pd.read_parquet(spath)
    components = pd.read_parquet(cpath)
    if len(summary) != 2944 * 11:
        raise RuntimeError(f"Expected 32,384 summary rows, got {len(summary):,}")

    classified, crop_areas = apply_history_status(summary, components, scfg)
    cp = outdir / "akerminne_year_summary_classified.parquet"
    gp = outdir / "akerminne_crop_areas_grouped.parquet"
    _atomic_parquet(classified, cp)
    _atomic_parquet(crop_areas, gp)

    checklist = build_checklist(classified)
    checklist_path = outdir / "manual_checklist.csv"
    checklist.to_csv(checklist_path, index=False, encoding="utf-8-sig")
    current = _read_current_skurup(project, str(config["pilot_municipality_code"]))
    problem_path = outdir / "problem_fields.geojson"
    write_problem_geojson(checklist, current, problem_path)

    years: dict[str, Any] = {}
    for year, g in classified.groupby("history_year", sort=True):
        rawc = components[components["history_year"] == year]
        vc = g["status"].value_counts()
        years[str(int(year))] = {
            "fields": int(len(g)),
            "status_counts": {str(k): int(v) for k, v in vc.items()},
            "coverage_p10": q(g["coverage_raw"], .10),
            "coverage_p50": q(g["coverage_raw"], .50),
            "coverage_p90": q(g["coverage_raw"], .90),
            "dominant_share_p50": q(g["dominant_crop_share"], .50),
            "raw_component_rows": int(len(rawc)),
            "max_component_count": int(g["component_count"].max()),
            "unknown_code_fields": int(g["reason_flags"].str.contains("UNKNOWN_CODE", regex=False).sum()),
            "raw_overlap_anomalies": int(g["overlap_anomaly"].sum()),
            "material_overlap_anomalies": int(g["material_overlap_anomaly"].sum()),
            "max_overlap_excess": float(g["overlap_excess_raw"].max()),
            "current_area_m2_sum": float(g["current_area_m2"].sum()),
            "covered_area_m2_sum_raw": float(g["covered_area_m2"].sum()),
        }

    historical = classified[classified["history_year"] < 2025]
    status_total = historical["status"].value_counts()
    crop_hist = crop_areas[crop_areas["history_year"] < 2025]
    sensitivity = []
    total_current_area = historical["current_area_m2"].sum()
    for threshold in (.001, .005, .01, .02, .05):
        removed = crop_hist[crop_hist["crop_share_current"] < threshold]
        sensitivity.append({
            "threshold": threshold,
            "removed_crop_rows": int(len(removed)),
            "retained_crop_rows": int(len(crop_hist) - len(removed)),
            "removed_area_pct_of_field_year_area": float(100.0 * removed["crop_area_m2"].sum() / total_current_area),
        })

    qa = {
        "schema_version": "akerminne-pilot-qa-v1a",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "municipality": config["pilot_municipality"],
        "thresholds": scfg.__dict__,
        "summary_rows": int(len(classified)),
        "component_rows": int(len(components)),
        "historical_status_counts": {str(k): int(v) for k, v in status_total.items()},
        "years": years,
        "sliver_sensitivity": sensitivity,
        "manual_checklist_rows": int(len(checklist)),
        "inputs": {
            "summary": {"path": str(spath), "sha256": sha256_file(spath)},
            "components": {"path": str(cpath), "sha256": sha256_file(cpath)},
        },
        "outputs": {
            "classified_summary": str(cp), "grouped_crop_areas": str(gp),
            "manual_checklist": str(checklist_path), "problem_fields": str(problem_path),
        },
        "crop_dictionary_note": "Official year-specific crop dictionaries are still pending; UNKNOWN_CODE remains a separate reason flag and does not replace geometry/coverage status.",
    }
    jpath = outdir / "akerminne_pilot_qa.json"
    jpath.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")

    md = [
        "# ÅkerMinne v1a – Skurup pilot QA – STOPPUNKT D", "",
        f"Generated: `{qa['generated_at_utc']}`", "",
        "## Frozen pilot thresholds", "",
        f"- complete coverage: `coverage_display >= {scfg.complete_coverage_min:.2f}`",
        f"- MIXED_CROPS: second grouped crop share `>= {scfg.mixed_secondary_crop_min_share:.2f}`",
        f"- web-visible component: grouped crop share `>= {scfg.web_component_min_share:.2f}`",
        f"- raw overlap flag tolerance: `{scfg.overlap_raw_tolerance}`",
        f"- material overlap QA: raw excess `> {scfg.material_overlap_excess:.3f}`",
        "- status precedence: NO_PUBLIC_MATCH -> PARTIAL_COVERAGE -> MIXED_CROPS -> SINGLE_CROP.",
        "- identity confidence, UNKNOWN_CODE and DUPLICATE_OVERLAP remain separate quality flags.", "",
        "## Status by year", "",
        "| Year | SINGLE | MIXED | PARTIAL | NO MATCH | raw overlap | material overlap | coverage P50 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year in sorted(years, key=int):
        r = years[year]; c = r["status_counts"]
        md.append(f"| {year} | {c.get('SINGLE_CROP',0)} | {c.get('MIXED_CROPS',0)} | {c.get('PARTIAL_COVERAGE',0)} | {c.get('NO_PUBLIC_MATCH',0)} | {r['raw_overlap_anomalies']} | {r['material_overlap_anomalies']} | {r['coverage_p50']:.4f} |")
    md += ["", "## Historical totals 2015–2024", ""]
    total_hist = len(historical)
    for status in ("SINGLE_CROP", "MIXED_CROPS", "PARTIAL_COVERAGE", "NO_PUBLIC_MATCH"):
        n = int(status_total.get(status, 0))
        md.append(f"- `{status}`: {n:,} ({100*n/total_hist:.2f}%)")
    md += ["", "## Sliver sensitivity after grouping identical crop codes", "", "| threshold | removed crop rows | retained | removed area of all field-years |", "|---:|---:|---:|---:|"]
    for r in sensitivity:
        md.append(f"| {100*r['threshold']:.1f}% | {r['removed_crop_rows']:,} | {r['retained_crop_rows']:,} | {r['removed_area_pct_of_field_year_area']:.4f}% |")
    md += ["", "## Manual reference sample", "", "| category | year | current field | status | coverage | second crop | identity | overlap excess |", "|---|---:|---|---|---:|---:|---|---:|"]
    for r in checklist.itertuples(index=False):
        md.append(f"| {r.qa_category} | {r.history_year} | `{r.current_field_id}` | {r.status} | {r.coverage_display:.4f} | {r.second_crop_share:.4f} | {r.identity_match_confidence} | {r.overlap_excess_raw:.4f} |")
    md += ["", "## STOPPUNKT D", "", "Open `problem_fields.geojson`/the listed fields in the next map QA step. Do not build the public web payload/UI until the reference sample has been reviewed.", ""]
    mpath = outdir / "akerminne_pilot_qa.md"
    mpath.write_text("\n".join(md), encoding="utf-8")

    print("=" * 78)
    print("ÅkerMinne v1a · finalized pilot thresholds + reference QA · STOPPUNKT D")
    print("=" * 78)
    print("Thresholds: coverage 95%; mixed second crop 5%; visible component 1%")
    print("Historical status counts:", json.dumps(qa["historical_status_counts"], sort_keys=True))
    print(f"Checklist: {len(checklist)} rows; problem GeoJSON fields: {checklist.current_field_id.nunique()}")
    print("QA MD:", mpath)
    print("QA JSON:", jpath)
    print("Problem fields:", problem_path)
    print("STOPPUNKT D remains active")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
