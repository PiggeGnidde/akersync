#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rebuild a representative STOPPUNKT D visual-reference sample without changing frozen thresholds."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from common import load_config
from akerminne_reference_sample import build_reference_checklist

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT = ROOT / "config" / "local_paths.json"
DEFAULT_CLASSIFIED = ROOT / "data" / "derived" / "akerminne_v1a" / "qa" / "akerminne_year_summary_classified.parquet"
DEFAULT_QA = ROOT / "data" / "derived" / "akerminne_v1a" / "qa"


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


def write_geojson(checklist: pd.DataFrame, current: gpd.GeoDataFrame, path: Path) -> None:
    g = current.copy()
    g["current_field_id"] = g["blockid"].map(_text) + "|" + g["skiftesbeteckning"].map(_text)
    out = g.merge(checklist, on="current_field_id", how="inner", validate="one_to_one")
    keep = [c for c in [
        "current_field_id", "blockid", "skiftesbeteckning", "qa_category",
        "history_year", "status", "coverage_display", "second_crop_share",
        "identity_match_confidence", "overlap_excess_raw", "geometry"
    ] if c in out.columns]
    out = out[keep].sort_values(["qa_category", "history_year", "current_field_id"], kind="mergesort")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp.geojson")
    tmp.unlink(missing_ok=True)
    out.to_file(tmp, driver="GeoJSON")
    check = gpd.read_file(tmp)
    if len(check) != 20:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"reference_sample.geojson expected 20 rows, got {len(check)}")
    path.unlink(missing_ok=True)
    tmp.replace(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-local-config", default=str(DEFAULT_PROJECT))
    ap.add_argument("--classified", default=str(DEFAULT_CLASSIFIED))
    ap.add_argument("--output", default=str(DEFAULT_QA))
    ap.add_argument("--municipality-code", default="1264")
    args = ap.parse_args()

    classified_path = Path(args.classified)
    if not classified_path.exists():
        raise FileNotFoundError(
            f"Classified QA file missing: {classified_path}. Run VERIFY_AKERMINNE_PILOT_SKURUP.bat first."
        )
    classified = pd.read_parquet(classified_path)
    checklist = build_reference_checklist(classified)

    outdir = Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    csv_path = outdir / "reference_sample_checklist.csv"
    checklist.to_csv(csv_path, index=False, encoding="utf-8-sig")

    project = load_config(args.project_local_config)
    current = _read_current_skurup(project, str(args.municipality_code))
    geojson_path = outdir / "reference_sample_fields.geojson"
    write_geojson(checklist, current, geojson_path)

    generated = datetime.now(timezone.utc).isoformat()
    years = sorted(checklist["history_year"].astype(int).unique().tolist())
    statuses = checklist["status"].value_counts().to_dict()
    categories = checklist["qa_category"].value_counts().to_dict()

    md = [
        "# ÅkerMinne v1a – representative reference sample – STOPPUNKT D", "",
        f"Generated: `{generated}`", "",
        "This replaces only the earlier 20-case visual sample. Frozen thresholds and classified history are unchanged.", "",
        "## Coverage contract", "",
        "- 20 rows and 20 unique current 2025 fields.",
        "- Stable and split/merge cases are spread across historical years.",
        "- `status_edge` deliberately contains 2 MIXED_CROPS, 2 PARTIAL_COVERAGE and 1 NO_PUBLIC_MATCH.",
        "- `problem` contains the five highest-ranked material/ambiguous QA cases after excluding already selected fields.",
        f"- Historical years represented: `{', '.join(map(str, years))}`.",
        f"- Status counts: `{statuses}`.",
        f"- Category counts: `{categories}`.", "",
        "## Checklist", "",
        "| category | year | field | status | coverage | second crop | identity | overlap excess |",
        "|---|---:|---|---|---:|---:|---|---:|",
    ]
    for r in checklist.itertuples(index=False):
        md.append(
            f"| {r.qa_category} | {int(r.history_year)} | `{r.current_field_id}` | {r.status} | "
            f"{float(r.coverage_display):.4f} | {float(r.second_crop_share):.4f} | "
            f"{r.identity_match_confidence} | {float(r.overlap_excess_raw):.4f} |"
        )
    md += [
        "", "## STOPPUNKT D visual review", "",
        "Open `reference_sample_fields.geojson` or use the listed field ids in the existing ÅkerPass map. "
        "Do not start public ÅkerMinne UI until these representative cases have been visually reviewed.", "",
    ]
    report_path = outdir / "reference_sample_qa.md"
    report_path.write_text("\n".join(md), encoding="utf-8")

    print("=" * 78)
    print("ÅkerMinne v1a · representative reference sample · STOPPUNKT D")
    print("=" * 78)
    print(f"Checklist: {len(checklist)} rows; unique current fields: {checklist.current_field_id.nunique()}")
    print("Years:", ", ".join(map(str, years)))
    print("Statuses:", statuses)
    print("CSV:", csv_path)
    print("GeoJSON:", geojson_path)
    print("Report:", report_path)
    print("STOPPUNKT D remains active pending visual review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
