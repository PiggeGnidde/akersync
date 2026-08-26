#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = ROOT / "dist" / "index.html"
DEFAULT_DATA = ROOT / "dist" / "data" / "akerminne" / "1264_skurup.json"
EXPECTED_HISTORICAL = {
    "SINGLE_CROP": 23161,
    "MIXED_CROPS": 2655,
    "PARTIAL_COVERAGE": 1034,
    "NO_PUBLIC_MATCH": 2590,
}
EXPECTED_YEARS = list(range(2015, 2026))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default=str(DEFAULT_INDEX))
    ap.add_argument("--data", default=str(DEFAULT_DATA))
    args = ap.parse_args()
    index = Path(args.index)
    data_path = Path(args.data)
    if not index.exists() or not data_path.exists():
        raise FileNotFoundError("ÅkerMinne pilot index/data missing")

    html = index.read_text(encoding="utf-8")
    required_ui = (
        "AKERMINNE_PILOT_UI_V1A", "ÅkerMinne · 2015–2025",
        "Historiken beskriver den markyta som utgör dagens 2025-skifte",
        "Små grödkomponenter under 1 % döljs", "loadAkerminnePilot",
        "data/akerminne/1264_skurup.json", "gräns ändrad",
        "historiska skiften sammanslagna", "historiskt skifte delat",
    )
    missing = [m for m in required_ui if m not in html]
    if missing:
        raise RuntimeError("ÅkerMinne frontend missing: " + ", ".join(missing))

    doc = json.loads(data_path.read_text(encoding="utf-8"))
    if doc.get("schema_version") != "akerminne-web-v1a":
        raise RuntimeError("wrong ÅkerMinne web schema")
    if doc.get("municipality") != "Skurup" or str(doc.get("municipality_code")) != "1264":
        raise RuntimeError("wrong pilot municipality")
    if doc.get("years") != EXPECTED_YEARS or doc.get("reference_year") != 2025:
        raise RuntimeError("wrong ÅkerMinne year contract")
    fields = doc.get("fields") or {}
    if len(fields) != 2944 or int(doc.get("field_count", -1)) != 2944:
        raise RuntimeError(f"expected 2,944 fields, got {len(fields):,}")
    thresholds = doc.get("thresholds") or {}
    minimum = float(thresholds.get("minimum_match", -1))
    complete = float(thresholds.get("complete_coverage", -1))
    mixed = float(thresholds.get("mixed_secondary_crop", -1))
    visible = float(thresholds.get("visible_component", -1))
    if (minimum, complete, mixed, visible) != (0.01, 0.95, 0.05, 0.01):
        raise RuntimeError(f"unexpected frozen thresholds: {thresholds}")

    historical = {k: 0 for k in EXPECTED_HISTORICAL}
    year_rows = 0
    material_overlap = 0
    visible_components = 0
    for field_id, history in fields.items():
        if len(history) != 11 or [int(r.get("y")) for r in history] != EXPECTED_YEARS:
            raise RuntimeError(f"{field_id}: invalid 11-year history")
        for row in history:
            year_rows += 1
            year = int(row["y"])
            status = str(row["s"])
            coverage = float(row["c"])
            second = float(row.get("ss", 0.0))
            if year < 2025:
                if status not in historical:
                    raise RuntimeError(f"{field_id} {year}: invalid status {status}")
                historical[status] += 1
            if status == "NO_PUBLIC_MATCH":
                if coverage >= minimum:
                    raise RuntimeError(f"{field_id} {year}: no-match at material coverage")
            elif status == "PARTIAL_COVERAGE":
                if not minimum <= coverage < complete:
                    raise RuntimeError(f"{field_id} {year}: invalid partial coverage {coverage}")
            elif status == "MIXED_CROPS":
                if coverage < complete or second < mixed:
                    raise RuntimeError(f"{field_id} {year}: invalid mixed status")
            elif status == "SINGLE_CROP":
                if coverage < complete or second >= mixed:
                    raise RuntimeError(f"{field_id} {year}: invalid single status")
            else:
                raise RuntimeError(f"{field_id} {year}: unknown status {status}")
            for comp in row.get("x", []):
                visible_components += 1
                if float(comp[1]) + 1e-12 < visible:
                    raise RuntimeError(f"{field_id} {year}: hidden sliver leaked to UI payload")
            material_overlap += int(bool(row.get("m", False)))
        current = history[-1]
        if current["y"] != 2025 or current["s"] != "SINGLE_CROP" or abs(float(current["c"]) - 1.0) > 1e-9:
            raise RuntimeError(f"{field_id}: invalid 2025 reference row")

    if historical != EXPECTED_HISTORICAL:
        raise RuntimeError(f"historical status totals changed: {historical}")
    if year_rows != 32384:
        raise RuntimeError(f"expected 32,384 field-years, got {year_rows:,}")

    print("AKERMINNE WEB PILOT QA: OK")
    print(f"  Fields/field-years: {len(fields):,}/{year_rows:,}")
    print(f"  Historical status: {historical}")
    print(f"  Visible crop components: {visible_components:,}")
    print(f"  Material overlap warnings: {material_overlap:,}")
    print(f"  Sidecar size: {data_path.stat().st_size / 1024 / 1024:.2f} MiB")
    print("  Existing ÅkerPass UI remains verified separately by 43_verify_akerpass_web_v1.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
