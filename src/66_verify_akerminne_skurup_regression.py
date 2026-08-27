#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PILOT_QA = ROOT / "data" / "derived" / "akerminne_v1a" / "qa"
DEFAULT_PILOT = ROOT / "data" / "derived" / "akerminne_v1a" / "pilot_skurup"
DEFAULT_SKANE = ROOT / "data" / "derived" / "akerminne_v1a" / "skane"
EXPECTED_FIELDS = 2944
EXPECTED_FIELD_YEARS = 32384
EXPECTED_COMPONENTS = 73328
EXPECTED_STATUS = {
    "SINGLE_CROP": 23161,
    "MIXED_CROPS": 2655,
    "PARTIAL_COVERAGE": 1034,
    "NO_PUBLIC_MATCH": 2590,
}


def _slug(text: str) -> str:
    trans = str.maketrans({"å": "a", "ä": "a", "ö": "o", "Å": "a", "Ä": "a", "Ö": "o"})
    return "".join(ch if ch.isalnum() else "_" for ch in str(text).translate(trans).lower()).strip("_")


def _norm_text(series: pd.Series) -> pd.Series:
    return series.astype("string").fillna("<NULL>")


def _compare_frame(
    left: pd.DataFrame,
    right: pd.DataFrame,
    keys: list[str],
    categorical: list[str],
    numeric: list[str],
    label: str,
) -> dict[str, Any]:
    missing_left = sorted(set(keys + categorical + numeric) - set(left.columns))
    missing_right = sorted(set(keys + categorical + numeric) - set(right.columns))
    if missing_left or missing_right:
        raise RuntimeError(f"{label}: missing columns pilot={missing_left}, skane={missing_right}")
    l = left[keys + categorical + numeric].copy()
    r = right[keys + categorical + numeric].copy()
    if l.duplicated(keys).any() or r.duplicated(keys).any():
        raise RuntimeError(f"{label}: comparison keys are not unique")
    l = l.sort_values(keys, kind="mergesort").reset_index(drop=True)
    r = r.sort_values(keys, kind="mergesort").reset_index(drop=True)
    if len(l) != len(r):
        raise RuntimeError(f"{label}: row count differs {len(l):,} vs {len(r):,}")
    for key in keys:
        if not _norm_text(l[key]).equals(_norm_text(r[key])):
            raise RuntimeError(f"{label}: key column differs: {key}")
    categorical_mismatches: dict[str, int] = {}
    for col in categorical:
        neq = _norm_text(l[col]) != _norm_text(r[col])
        n = int(neq.sum())
        if n:
            categorical_mismatches[col] = n
    numeric_max_abs: dict[str, float] = {}
    for col in numeric:
        a = pd.to_numeric(l[col], errors="coerce").to_numpy(dtype=float)
        b = pd.to_numeric(r[col], errors="coerce").to_numpy(dtype=float)
        same_nan = np.isnan(a) & np.isnan(b)
        ok = np.isclose(a, b, rtol=1e-10, atol=1e-8, equal_nan=True)
        if not bool(np.all(ok | same_nan)):
            bad = np.where(~(ok | same_nan))[0]
            max_abs = float(np.nanmax(np.abs(a[bad] - b[bad]))) if len(bad) else 0.0
            raise RuntimeError(f"{label}: numeric column differs: {col}; rows={len(bad)}, max_abs={max_abs}")
        finite = np.isfinite(a) & np.isfinite(b)
        numeric_max_abs[col] = float(np.max(np.abs(a[finite] - b[finite]))) if finite.any() else 0.0
    if categorical_mismatches:
        raise RuntimeError(f"{label}: categorical differences {categorical_mismatches}")
    return {"rows": int(len(l)), "numeric_max_abs": numeric_max_abs}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot-qa", default=str(DEFAULT_PILOT_QA))
    ap.add_argument("--pilot", default=str(DEFAULT_PILOT))
    ap.add_argument("--skane-root", default=str(DEFAULT_SKANE))
    args = ap.parse_args()

    pilot_qa, pilot, skane = Path(args.pilot_qa), Path(args.pilot), Path(args.skane_root)
    skurup = skane / "municipalities" / f"1264_{_slug('Skurup')}"
    paths = {
        "pilot_classified": pilot_qa / "akerminne_year_summary_classified.parquet",
        "pilot_grouped": pilot_qa / "akerminne_crop_areas_grouped.parquet",
        "pilot_components": pilot / "akerminne_components.parquet",
        "skane_classified": skurup / "akerminne_year_summary_classified.parquet",
        "skane_grouped": skurup / "akerminne_crop_areas_grouped.parquet",
        "skane_components": skurup / "akerminne_components.parquet",
    }
    missing = [str(p) for p in paths.values() if not p.exists()]
    if missing:
        raise FileNotFoundError("Regression inputs missing: " + ", ".join(missing))

    pc = pd.read_parquet(paths["pilot_classified"])
    sc = pd.read_parquet(paths["skane_classified"])
    pg = pd.read_parquet(paths["pilot_grouped"])
    sg = pd.read_parquet(paths["skane_grouped"])
    pp = pd.read_parquet(paths["pilot_components"])
    sp = pd.read_parquet(paths["skane_components"])

    if len(pc) != EXPECTED_FIELD_YEARS or len(sc) != EXPECTED_FIELD_YEARS:
        raise RuntimeError(f"Skurup field-year contract changed: pilot={len(pc):,}, skane={len(sc):,}")
    fields_p = int(pc["current_field_id"].nunique())
    fields_s = int(sc["current_field_id"].nunique())
    if fields_p != EXPECTED_FIELDS or fields_s != EXPECTED_FIELDS:
        raise RuntimeError(f"Skurup current field contract changed: {fields_p}/{fields_s}")
    if len(pp) != EXPECTED_COMPONENTS or len(sp) != EXPECTED_COMPONENTS:
        raise RuntimeError(f"Skurup component contract changed: pilot={len(pp):,}, skane={len(sp):,}")

    classified_result = _compare_frame(
        pc, sc,
        ["current_field_id", "history_year"],
        [
            "status", "identity_match_confidence", "dominant_crop_code_raw",
            "dominant_crop_subcategory_raw", "dominant_crop_name", "material_overlap_anomaly",
        ],
        [
            "current_area_m2", "coverage_raw", "coverage_display", "dominant_crop_share",
            "first_crop_share_grouped", "second_crop_share", "overlap_excess_raw",
        ],
        "classified field-years",
    )

    grouped_result = _compare_frame(
        pg, sg,
        ["history_year", "current_field_id", "crop_code_raw", "crop_subcategory_raw"],
        [], ["crop_area_m2", "current_area_m2", "crop_share_current", "crop_rank"],
        "grouped crop areas",
    )

    component_keys = [
        "history_year", "current_field_id", "historical_field_id",
        "crop_code_raw", "crop_subcategory_raw",
    ]
    component_categorical = ["crop_name", "crop_known", "same_admin_key", "is_current_primary", "is_historical_primary", "is_mutual_primary"]
    component_numeric = ["intersection_m2", "share_current", "share_historical", "strict_score", "relaxed_score"]
    component_result = _compare_frame(pp, sp, component_keys, component_categorical, component_numeric, "raw components")

    h = sc[sc["history_year"] < 2025]
    status = {str(k): int(v) for k, v in h["status"].value_counts().sort_index().items()}
    if status != EXPECTED_STATUS:
        raise RuntimeError(f"Skurup historical status regression: {status}")
    unknown = int((~sp["crop_known"].astype(bool)).sum())
    if unknown != 0:
        raise RuntimeError(f"Skurup has {unknown} unknown component labels")

    report = {
        "schema_version": "akerminne-skurup-regression-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "result": "PASS",
        "fields": EXPECTED_FIELDS,
        "field_years": EXPECTED_FIELD_YEARS,
        "components": EXPECTED_COMPONENTS,
        "historical_status_counts": status,
        "classified": classified_result,
        "grouped_crop_areas": grouped_result,
        "components_compare": component_result,
        "unknown_component_labels": unknown,
    }
    out_json = skane / "skurup_regression.json"
    out_md = skane / "skurup_regression.md"
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# ÅkerMinne v1a – Skurup regression", "",
        "**PASS** – the general Skåne pipeline reproduces the frozen Skurup pilot semantically.", "",
        f"- Current fields: **{EXPECTED_FIELDS:,}**",
        f"- Field-years: **{EXPECTED_FIELD_YEARS:,}**",
        f"- Raw historical components: **{EXPECTED_COMPONENTS:,}**",
        "- Unknown official crop labels: **0**",
        "- Status, identity class, coverage, crop identity and component geometry: **unchanged**", "",
        "## Historical status 2015–2024", "",
    ]
    for key, value in EXPECTED_STATUS.items():
        lines.append(f"- `{key}`: {value:,}")
    lines += ["", f"Machine-readable report: `{out_json}`", ""]
    out_md.write_text("\n".join(lines), encoding="utf-8")

    print("=" * 78)
    print("ÅkerMinne v1a · SKURUP REGRESSION: PASS")
    print("=" * 78)
    print(f"Fields/field-years/components: {EXPECTED_FIELDS:,}/{EXPECTED_FIELD_YEARS:,}/{EXPECTED_COMPONENTS:,}")
    print(f"Status 2015-2024: {status}")
    print("Geometry/coverage/identity/crops: unchanged")
    print(f"Report: {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
