#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Independent QA for the combined ÅkerPass + ÅkerMinne + phase-0 web distribution."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_FIELDS = 128_636
EXPECTED_FIELD_YEARS = 1_414_996
EXPECTED_YEARS = list(range(2015, 2026))
ALLOWED_STATUS = {"SINGLE_CROP", "MIXED_CROPS", "PARTIAL_COVERAGE", "NO_PUBLIC_MATCH"}


def verify_sidecar(path: Path, entry: dict[str, Any]) -> tuple[int, int]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema_version") != "akerminne-web-v1a":
        raise RuntimeError(f"{path.name}: wrong ÅkerMinne sidecar schema")
    if doc.get("municipality") != entry.get("municipality"):
        raise RuntimeError(f"{path.name}: municipality mismatch")
    if str(doc.get("municipality_code")) != str(entry.get("municipality_code")):
        raise RuntimeError(f"{path.name}: municipality code mismatch")
    if doc.get("years") != EXPECTED_YEARS or int(doc.get("reference_year", -1)) != 2025:
        raise RuntimeError(f"{path.name}: invalid year contract")

    fields = doc.get("fields") or {}
    expected = int(entry.get("field_count", -1))
    if len(fields) != expected or int(doc.get("field_count", -1)) != expected:
        raise RuntimeError(f"{path.name}: field count mismatch {len(fields)} != {expected}")

    unknown_names = [v for v in (doc.get("crop_names") or {}).values() if str(v).startswith("Okänd grödkod")]
    if unknown_names:
        raise RuntimeError(f"{path.name}: unknown crop labels leaked to reused web package")

    rows = 0
    for field_id, history in fields.items():
        if len(history) != 11:
            raise RuntimeError(f"{path.name} {field_id}: expected 11 history rows")
        years = [int(row.get("y", -1)) for row in history]
        if years != EXPECTED_YEARS:
            raise RuntimeError(f"{path.name} {field_id}: invalid year sequence")
        for row in history:
            status = str(row.get("s") or "")
            if status not in ALLOWED_STATUS:
                raise RuntimeError(f"{path.name} {field_id}: invalid status {status}")
            rows += 1
        ref = history[-1]
        if str(ref.get("s")) != "SINGLE_CROP" or abs(float(ref.get("c", 0.0)) - 1.0) > 1e-9:
            raise RuntimeError(f"{path.name} {field_id}: invalid 2025 reference row")
    return expected, rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", default=str(ROOT / "dist"))
    args = ap.parse_args()
    dist = Path(args.dist)
    html_path = dist / "index.html"
    manifest_path = dist / "municipalities.json"
    akm_dir = dist / "data" / "akerminne"
    web_index_path = akm_dir / "skane_index.json"
    for path in (html_path, manifest_path, web_index_path):
        if not path.exists():
            raise FileNotFoundError(path)

    html = html_path.read_text(encoding="utf-8")
    required_ui = (
        "AKERMINNE_PILOT_UI_V1A",
        "AKERMINNE_PILOT_UI_COPY_R1",
        "AKERMINNE_SKANE_UI_R2",
        "ÅkerMinne · 2015–2025",
        '"Lomma":"data/akerminne/1262_lomma.json"',
        "Historisk jordbruksklass — referensdata",
        "Skördeområde (SKO)",
    )
    missing_ui = [item for item in required_ui if item not in html]
    if missing_ui:
        raise RuntimeError("Combined frontend missing: " + ", ".join(missing_ui))
    if "Historisk jordbruksklass 1971 — referensdata" in html:
        raise RuntimeError("Old hard-coded 1971 label remains in combined frontend")
    if 'p.kommun!=="Skurup"' in html or "field_count!==2944" in html:
        raise RuntimeError("Skurup-only ÅkerMinne guard remains in combined frontend")

    public_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    municipalities = public_manifest.get("municipalities") or {}
    if len(municipalities) != 33:
        raise RuntimeError("Public web manifest does not contain 33 municipalities")
    if public_manifest.get("akerprestation_phase0_version") != "akerprestation-phase0-v0a":
        raise RuntimeError("Public web manifest lacks phase-0 version")
    if int(public_manifest.get("sko_source_id_count", -1)) != 18 or int(public_manifest.get("sko_dominant_id_count", -1)) != 17:
        raise RuntimeError("Public web manifest has wrong SKO source/dominant domain counts")

    web_index = json.loads(web_index_path.read_text(encoding="utf-8"))
    entries = web_index.get("municipalities") or []
    if (
        web_index.get("schema_version") != "akerminne-skane-web-index-v1"
        or len(entries) != 33
        or int(web_index.get("municipality_count", -1)) != 33
        or int(web_index.get("field_count", -1)) != EXPECTED_FIELDS
        or int(web_index.get("field_years", -1)) != EXPECTED_FIELD_YEARS
        or web_index.get("years") != EXPECTED_YEARS
    ):
        raise RuntimeError("Reused ÅkerMinne web index is not the frozen full-Skåne package")

    total_fields = 0
    total_rows = 0
    total_bytes = 0
    names: set[str] = set()
    for entry in entries:
        name = str(entry.get("municipality") or "")
        rel = str(entry.get("file") or "")
        if not name or name in names:
            raise RuntimeError(f"Invalid/duplicate ÅkerMinne municipality: {name!r}")
        names.add(name)
        sidecar = dist / rel
        if not sidecar.exists():
            raise FileNotFoundError(sidecar)
        fields, rows = verify_sidecar(sidecar, entry)
        total_fields += fields
        total_rows += rows
        total_bytes += sidecar.stat().st_size
        print(f"  {name:16s} {fields:6,d} fields · ÅkerMinne OK")

    if total_fields != EXPECTED_FIELDS or total_rows != EXPECTED_FIELD_YEARS:
        raise RuntimeError(f"Combined ÅkerMinne totals invalid: {total_fields:,}/{total_rows:,}")
    if int(web_index.get("sidecar_bytes", -1)) != total_bytes:
        raise RuntimeError("Reused ÅkerMinne sidecar byte total differs from web index")
    if set(municipalities) != names:
        raise RuntimeError("Public municipalities and ÅkerMinne municipalities differ")

    print("=" * 96)
    print("ÅKERPASS + ÅKERMINNE + PHASE 0 COMBINED WEB: PASS")
    print("=" * 96)
    print("Municipalities: 33/33")
    print(f"Fields / ÅkerMinne field-years: {total_fields:,} / {total_rows:,}")
    print("ÅkerMinne: all-Skåne UI + 33 sidecars verified")
    print("Phase 0: historic class 1-10 + dominant SKO UI verified")
    print("SKO domain: 18 source IDs / 17 dominant field IDs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
