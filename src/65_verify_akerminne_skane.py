#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify completed ÅkerMinne municipality outputs and aggregate Skåne QA."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SKANE = ROOT / "data" / "derived" / "akerminne_v1a" / "skane"
EXPECTED_STATUSES = {"SINGLE_CROP", "MIXED_CROPS", "PARTIAL_COVERAGE", "NO_PUBLIC_MATCH"}
EXPECTED_YEARS = list(range(2015, 2026))
EXPECTED_TOTAL_FIELDS = 128636
EXPECTED_TOTAL_FIELD_YEARS = EXPECTED_TOTAL_FIELDS * 11
SCHEMA_VERSION = "akerminne-municipality-v1a-r1"


def _slug(text: str) -> str:
    trans = str.maketrans({"å": "a", "ä": "a", "ö": "o", "Å": "a", "Ä": "a", "Ö": "o"})
    s = str(text).translate(trans).lower()
    return "".join(ch if ch.isalnum() else "_" for ch in s).strip("_")


def municipality_dir(root: Path, item: dict[str, Any]) -> Path:
    return root / "municipalities" / f"{item['code']}_{_slug(item['name'])}"


def verify_one(root: Path, item: dict[str, Any]) -> dict[str, Any]:
    d = municipality_dir(root, item)
    manifest_path = d / "build_manifest.json"
    classified_path = d / "akerminne_year_summary_classified.parquet"
    components_path = d / "akerminne_components.parquet"
    crop_areas_path = d / "akerminne_crop_areas_grouped.parquet"
    for path in (manifest_path, classified_path, components_path, crop_areas_path):
        if not path.exists():
            raise FileNotFoundError(path)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError(f"{item['code']}: wrong municipality schema")
    expected_fields = int(item["current_fields"])
    if int(manifest.get("current_fields", -1)) != expected_fields:
        raise RuntimeError(f"{item['code']}: field count differs from frozen plan")

    classified = pd.read_parquet(classified_path)
    components = pd.read_parquet(components_path)
    crop_areas = pd.read_parquet(crop_areas_path)
    expected_rows = expected_fields * 11
    if len(classified) != expected_rows:
        raise RuntimeError(f"{item['code']}: expected {expected_rows:,} field-years, got {len(classified):,}")
    years = sorted(map(int, classified["history_year"].unique()))
    if years != EXPECTED_YEARS:
        raise RuntimeError(f"{item['code']}: wrong year set {years}")
    counts = classified.groupby("current_field_id")["history_year"].nunique()
    if len(counts) != expected_fields or not (counts == 11).all():
        raise RuntimeError(f"{item['code']}: not exactly 11 years per current field")
    statuses = set(classified["status"].astype(str))
    if statuses - EXPECTED_STATUSES:
        raise RuntimeError(f"{item['code']}: unexpected statuses {sorted(statuses - EXPECTED_STATUSES)}")

    current = classified[classified["history_year"] == 2025]
    if len(current) != expected_fields:
        raise RuntimeError(f"{item['code']}: wrong 2025 reference row count")
    if not (current["status"] == "SINGLE_CROP").all():
        raise RuntimeError(f"{item['code']}: non-single 2025 reference status")
    if (current["coverage_display"].astype(float) - 1.0).abs().max() > 1e-9:
        raise RuntimeError(f"{item['code']}: non-unit 2025 coverage")

    historical = classified[classified["history_year"] < 2025]
    status_counts = {str(k): int(v) for k, v in historical["status"].value_counts().sort_index().items()}
    identity_counts = {str(k): int(v) for k, v in historical["identity_match_confidence"].value_counts().sort_index().items()}
    unknown_rows = int((~components["crop_known"]).sum()) if len(components) else 0
    unknown_combinations = int(manifest.get("unknown_crop_combinations", -1))
    if unknown_combinations < 0:
        raise RuntimeError(f"{item['code']}: missing unknown crop count in manifest")

    return {"code": str(item["code"]), "name": str(item["name"]), "current_fields": expected_fields, "field_years": int(len(classified)), "component_rows": int(len(components)), "grouped_crop_rows": int(len(crop_areas)), "unknown_component_rows": unknown_rows, "unknown_crop_combinations": unknown_combinations, "historical_status_counts": status_counts, "historical_identity_counts": identity_counts}


def _sum_nested(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        for k, v in (row.get(key) or {}).items():
            out[str(k)] = out.get(str(k), 0) + int(v)
    return dict(sorted(out.items()))


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# ÅkerMinne v1a – Skåne batch QA", "",
        f"Generated: `{report['generated_at_utc']}`", "",
        f"- Completed municipalities: **{report['completed_municipalities']}/33**",
        f"- Frozen 2025 current fields represented: **{report['current_fields']:,}/{EXPECTED_TOTAL_FIELDS:,}**",
        f"- Field-years represented: **{report['field_years']:,}/{EXPECTED_TOTAL_FIELD_YEARS:,}**",
        f"- Crop components: **{report['component_rows']:,}**",
        f"- Unknown crop-code combinations: **{report['unknown_crop_combinations']:,}**", "",
        "## Municipality QA", "",
        "| code | municipality | fields | field-years | components | unknown combos |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for row in report["municipalities"]:
        lines.append(f"| {row['code']} | {row['name']} | {row['current_fields']:,} | {row['field_years']:,} | {row['component_rows']:,} | {row['unknown_crop_combinations']:,} |")
    if report["missing_codes"]:
        lines += ["", "## Missing municipalities", "", ", ".join(report["missing_codes"])]
    lines += ["", "## Historical status totals 2015–2024", ""]
    for k, v in report["historical_status_counts"].items():
        lines.append(f"- `{k}`: {v:,}")
    lines += ["", "## Historical identity totals 2015–2024", ""]
    for k, v in report["historical_identity_counts"].items():
        lines.append(f"- `{k}`: {v:,}")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skane-root", default=str(DEFAULT_SKANE))
    ap.add_argument("--allow-partial", action="store_true")
    args = ap.parse_args()

    root = Path(args.skane_root)
    plan_path = root / "skane_plan.json"
    if not plan_path.exists():
        raise FileNotFoundError(plan_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    rows, missing, failures = [], [], []
    for item in plan["municipalities"]:
        try:
            rows.append(verify_one(root, item))
        except FileNotFoundError:
            missing.append(str(item["code"]))
        except Exception as exc:
            failures.append(f"{item['code']} {item['name']}: {exc}")

    if failures:
        raise RuntimeError("Municipality verification failures:\n" + "\n".join(failures))
    if missing and not args.allow_partial:
        raise RuntimeError(f"Missing {len(missing)} municipalities: {', '.join(missing)}")

    report = {"schema_version": "akerminne-skane-qa-v1", "generated_at_utc": datetime.now(timezone.utc).isoformat(), "completed_municipalities": len(rows), "missing_codes": missing, "current_fields": sum(r["current_fields"] for r in rows), "field_years": sum(r["field_years"] for r in rows), "component_rows": sum(r["component_rows"] for r in rows), "grouped_crop_rows": sum(r["grouped_crop_rows"] for r in rows), "unknown_component_rows": sum(r["unknown_component_rows"] for r in rows), "unknown_crop_combinations": sum(r["unknown_crop_combinations"] for r in rows), "historical_status_counts": _sum_nested(rows, "historical_status_counts"), "historical_identity_counts": _sum_nested(rows, "historical_identity_counts"), "municipalities": sorted(rows, key=lambda r: r["code"])}
    if not missing:
        if report["completed_municipalities"] != 33:
            raise RuntimeError("Full Skåne verification expected 33 municipalities")
        if report["current_fields"] != EXPECTED_TOTAL_FIELDS:
            raise RuntimeError(f"Full Skåne current field total changed: expected {EXPECTED_TOTAL_FIELDS:,}, got {report['current_fields']:,}")
        if report["field_years"] != EXPECTED_TOTAL_FIELD_YEARS:
            raise RuntimeError(f"Full Skåne field-year total changed: expected {EXPECTED_TOTAL_FIELD_YEARS:,}, got {report['field_years']:,}")

    qa_json = root / "skane_qa.json"
    qa_md = root / "skane_qa.md"
    qa_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(report, qa_md)

    print("=" * 78)
    print("ÅkerMinne v1a · SKÅNE VERIFY: PASS")
    print("=" * 78)
    print(f"Municipalities: {len(rows)}/33; missing: {len(missing)}")
    print(f"Current fields: {report['current_fields']:,}; field-years: {report['field_years']:,}")
    print(f"Components: {report['component_rows']:,}")
    print(f"Unknown crop combinations: {report['unknown_crop_combinations']:,}")
    print(f"QA: {qa_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
