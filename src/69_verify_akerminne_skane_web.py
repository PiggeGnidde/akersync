#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX_HTML = ROOT / "dist" / "index.html"
DEFAULT_AKM_DIR = ROOT / "dist" / "data" / "akerminne"
DEFAULT_SKANE = ROOT / "data" / "derived" / "akerminne_v1a" / "skane"
EXPECTED_FIELDS = 128636
EXPECTED_FIELD_YEARS = 1414996
EXPECTED_YEARS = list(range(2015, 2026))
ALLOWED_STATUS = {"SINGLE_CROP", "MIXED_CROPS", "PARTIAL_COVERAGE", "NO_PUBLIC_MATCH"}


def _slug(text: str) -> str:
    trans = str.maketrans({"å": "a", "ä": "a", "ö": "o", "Å": "a", "Ä": "a", "Ö": "o"})
    return "".join(ch if ch.isalnum() else "_" for ch in str(text).translate(trans).lower()).strip("_")


def _status_counts(fields: dict[str, Any]) -> tuple[dict[str, int], int, int]:
    historical = {k: 0 for k in sorted(ALLOWED_STATUS)}
    rows = 0
    overlap_warnings = 0
    for field_id, history in fields.items():
        if len(history) != 11 or [int(x.get("y", -1)) for x in history] != EXPECTED_YEARS:
            raise RuntimeError(f"{field_id}: invalid 11-year web history")
        for row in history:
            rows += 1
            year = int(row["y"])
            status = str(row["s"])
            if status not in ALLOWED_STATUS:
                raise RuntimeError(f"{field_id} {year}: invalid status {status}")
            coverage = float(row["c"])
            if year < 2025:
                historical[status] += 1
            else:
                if status != "SINGLE_CROP" or abs(coverage - 1.0) > 1e-9:
                    raise RuntimeError(f"{field_id}: invalid 2025 reference row")
            overlap_warnings += int(bool(row.get("m", False)))
    return historical, rows, overlap_warnings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index-html", default=str(DEFAULT_INDEX_HTML))
    ap.add_argument("--akm-dir", default=str(DEFAULT_AKM_DIR))
    ap.add_argument("--skane-root", default=str(DEFAULT_SKANE))
    args = ap.parse_args()

    index_html, akm_dir, skane_root = Path(args.index_html), Path(args.akm_dir), Path(args.skane_root)
    if not index_html.exists():
        raise FileNotFoundError(index_html)
    html = index_html.read_text(encoding="utf-8")
    required_ui = (
        "AKERMINNE_PILOT_UI_V1A",
        "AKERMINNE_PILOT_UI_COPY_R1",
        "AKERMINNE_SKANE_UI_R2",
        '"Skurup":"data/akerminne/1264_skurup.json"',
        '"Kristianstad":"data/akerminne/1290_kristianstad.json"',
        '"Hässleholm":"data/akerminne/1293_hassleholm.json"',
        'if(!AKERMINNE_PILOT_FILES[p.kommun])return"";',
        "Jordbruksverkets officiella årsvisa kodlistor 2015–2025",
        "Gröduppgift visas inte vid så låg täckning",
    )
    missing_ui = [x for x in required_ui if x not in html]
    if missing_ui:
        raise RuntimeError("ÅkerMinne Skåne frontend missing: " + ", ".join(missing_ui))
    if 'p.kommun!=="Skurup"' in html or "field_count!==2944" in html:
        raise RuntimeError("Skurup-only guard remains in frontend")

    web_index_path = akm_dir / "skane_index.json"
    if not web_index_path.exists():
        raise FileNotFoundError(web_index_path)
    web_index = json.loads(web_index_path.read_text(encoding="utf-8"))
    if web_index.get("schema_version") != "akerminne-skane-web-index-v1":
        raise RuntimeError("Wrong Skåne web index schema")
    entries = web_index.get("municipalities") or []
    if len(entries) != 33 or int(web_index.get("field_count", -1)) != EXPECTED_FIELDS or int(web_index.get("field_years", -1)) != EXPECTED_FIELD_YEARS:
        raise RuntimeError("Skåne web index totals are invalid")

    plan = json.loads((skane_root / "skane_plan.json").read_text(encoding="utf-8"))
    plan_by_code = {str(x["code"]): x for x in plan["municipalities"]}
    if len(plan_by_code) != 33:
        raise RuntimeError("Skåne plan must contain 33 municipalities")

    total_fields = total_rows = total_bytes = total_overlap = 0
    aggregate_status = {k: 0 for k in sorted(ALLOWED_STATUS)}
    municipality_summaries: list[dict[str, Any]] = []
    for entry in entries:
        code, name = str(entry["municipality_code"]), str(entry["municipality"])
        if code not in plan_by_code or str(plan_by_code[code]["name"]) != name:
            raise RuntimeError(f"Web index municipality mismatch: {code} {name}")
        expected_fields = int(plan_by_code[code]["current_fields"])
        sidecar = akm_dir / f"{code}_{_slug(name)}.json"
        if not sidecar.exists():
            raise FileNotFoundError(sidecar)
        doc = json.loads(sidecar.read_text(encoding="utf-8"))
        if doc.get("schema_version") != "akerminne-web-v1a" or doc.get("municipality") != name or str(doc.get("municipality_code")) != code:
            raise RuntimeError(f"{name}: invalid sidecar identity/schema")
        if doc.get("years") != EXPECTED_YEARS or int(doc.get("reference_year", -1)) != 2025:
            raise RuntimeError(f"{name}: invalid year contract")
        fields = doc.get("fields") or {}
        if len(fields) != expected_fields or int(doc.get("field_count", -1)) != expected_fields:
            raise RuntimeError(f"{name}: expected {expected_fields:,} fields, got {len(fields):,}")
        crop_names = doc.get("crop_names") or {}
        unknown_names = [v for v in crop_names.values() if str(v).startswith("Okänd grödkod")]
        if unknown_names:
            raise RuntimeError(f"{name}: unknown crop labels leaked to web payload")
        status, rows, overlap = _status_counts(fields)
        if rows != expected_fields * 11:
            raise RuntimeError(f"{name}: invalid field-year total {rows:,}")

        mdir = skane_root / "municipalities" / f"{code}_{_slug(name)}"
        build_manifest = json.loads((mdir / "build_manifest.json").read_text(encoding="utf-8"))
        expected_status = {k: int(build_manifest.get("historical_status_counts", {}).get(k, 0)) for k in sorted(ALLOWED_STATUS)}
        if status != expected_status:
            raise RuntimeError(f"{name}: web status counts differ from municipality build: {status} vs {expected_status}")
        if int(build_manifest.get("unknown_crop_combinations", -1)) != 0:
            raise RuntimeError(f"{name}: source build has unknown crop combinations")

        for key, value in status.items():
            aggregate_status[key] += value
        total_fields += expected_fields
        total_rows += rows
        total_overlap += overlap
        total_bytes += sidecar.stat().st_size
        municipality_summaries.append({"code": code, "name": name, "fields": expected_fields, "field_years": rows, "bytes": sidecar.stat().st_size})
        print(f"{code} {name}: OK · {expected_fields:,} fields")

    if total_fields != EXPECTED_FIELDS or total_rows != EXPECTED_FIELD_YEARS:
        raise RuntimeError(f"Web aggregate totals invalid: fields={total_fields:,}, field-years={total_rows:,}")
    if int(web_index.get("sidecar_bytes", -1)) != total_bytes:
        raise RuntimeError("Web index sidecar byte total does not match files")

    report = {
        "schema_version": "akerminne-skane-web-qa-v1",
        "result": "PASS",
        "municipalities": 33,
        "fields": total_fields,
        "field_years": total_rows,
        "sidecar_bytes": total_bytes,
        "historical_status_counts": aggregate_status,
        "material_overlap_warning_rows": total_overlap,
        "municipality_files": municipality_summaries,
    }
    report_json = skane_root / "skane_web_qa.json"
    report_md = skane_root / "skane_web_qa.md"
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# ÅkerMinne v1a – Skåne web QA", "", "**PASS**", "",
        "- Municipalities: **33/33**",
        f"- Current fields: **{total_fields:,}**",
        f"- Field-years: **{total_rows:,}**",
        f"- Sidecar size: **{total_bytes/1024/1024:.1f} MiB**",
        "- Unknown crop labels: **0**", "",
        "## Historical status 2015–2024", "",
    ]
    for key, value in aggregate_status.items():
        lines.append(f"- `{key}`: {value:,}")
    lines += ["", f"Material overlap QA warnings in web rows: **{total_overlap:,}**", ""]
    report_md.write_text("\n".join(lines), encoding="utf-8")

    print("=" * 78)
    print("ÅkerMinne v1a · SKÅNE WEB VERIFY: PASS")
    print("=" * 78)
    print(f"Municipalities: 33/33")
    print(f"Fields/field-years: {total_fields:,}/{total_rows:,}")
    print(f"Sidecars: {total_bytes/1024/1024:.1f} MiB")
    print(f"Unknown crop labels: 0")
    print(f"QA: {report_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
