#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Independent verifier for ÅkerFrö konservärt web v0a."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

spec = importlib.util.spec_from_file_location(
    "akerfro_web_build_verify", ROOT / "src/88_build_akerfro_web_v0a.py"
)
if spec is None or spec.loader is None:
    raise RuntimeError("Cannot load ÅkerFrö web builder")
BUILD = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BUILD)


def load_json(path: Path) -> dict:
    if not path.exists():
        raise RuntimeError(f"Missing verifier input: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-dist", required=True, type=Path)
    ap.add_argument("--dist", required=True, type=Path)
    ap.add_argument("--work", default=str(ROOT / "work/akerfro_web_v0a"), type=Path)
    args = ap.parse_args()

    base = args.base_dist.resolve()
    dist = args.dist.resolve()
    work = args.work.resolve()

    problems: list[str] = []
    manifest = load_json(work / "akerfro_web_manifest.json")
    index = load_json(dist / "data/akerfro/skane_index.json")
    toplist = load_json(dist / "data/akerfro/skane_top1000.json")

    if manifest.get("status") != "PASS":
        problems.append("BUILD MANIFEST NOT PASS")
    if manifest.get("scope", {}).get("akerfro_model_recalculated") is not False:
        problems.append("BUILD CLAIMS MODEL RECALCULATION")
    if manifest.get("scope", {}).get("akernorm_base_changed") is not False:
        problems.append("BUILD CLAIMS AKERNORM BASE CHANGE")
    if manifest.get("scope", {}).get("deployment") is not False:
        problems.append("BUILD CLAIMS DEPLOYMENT")

    if index.get("schema_version") != BUILD.INDEX_SCHEMA or index.get("status") != "PASS":
        problems.append("WEB INDEX CONTRACT MISMATCH")
    if int(index.get("field_count", -1)) != BUILD.EXPECTED_FIELDS:
        problems.append("WEB INDEX FIELD COUNT MISMATCH")
    if int(index.get("municipality_count", -1)) != BUILD.EXPECTED_MUNICIPALITIES:
        problems.append("WEB INDEX MUNICIPALITY COUNT MISMATCH")
    if index.get("class_counts") != BUILD.EXPECTED_CLASSES:
        problems.append("WEB INDEX CLASS COUNTS MISMATCH")
    if index.get("operational_band_counts") != BUILD.EXPECTED_BANDS:
        problems.append("WEB INDEX OPERATIONAL BAND COUNTS MISMATCH")

    entries = index.get("municipalities") or []
    total_fields = 0
    total_classes = {k: 0 for k in BUILD.EXPECTED_CLASSES}
    for entry in entries:
        path = dist / Path(str(entry["file"]))
        if not path.exists():
            problems.append(f"MISSING MUNICIPALITY SIDECAR {path}")
            continue
        if path.stat().st_size != int(entry["bytes"]):
            problems.append(f"SIZE MISMATCH {path}")
        if BUILD.sha256_file(path) != str(entry["sha256"]):
            problems.append(f"HASH MISMATCH {path}")
        payload = load_json(path)
        if payload.get("schema_version") != BUILD.SCHEMA:
            problems.append(f"SCHEMA MISMATCH {path}")
        if payload.get("municipality") != entry.get("municipality"):
            problems.append(f"MUNICIPALITY NAME MISMATCH {path}")
        n = int(payload.get("field_count", -1))
        if n != len(payload.get("fields") or {}):
            problems.append(f"FIELD DICTIONARY COUNT MISMATCH {path}")
        total_fields += max(n, 0)
        for cls, count in (payload.get("class_counts") or {}).items():
            total_classes[cls] = total_classes.get(cls, 0) + int(count)

    if total_fields != BUILD.EXPECTED_FIELDS:
        problems.append(f"SIDECAR TOTAL FIELD COUNT {total_fields} != {BUILD.EXPECTED_FIELDS}")
    if total_classes != BUILD.EXPECTED_CLASSES:
        problems.append(f"SIDECAR CLASS TOTALS {total_classes} != {BUILD.EXPECTED_CLASSES}")

    if toplist.get("schema_version") != "akerfro-ertor-toplist-v0a":
        problems.append("TOPLIST SCHEMA MISMATCH")
    rows = toplist.get("rows") or []
    if len(rows) != 1000 or int(toplist.get("count", -1)) != 1000:
        problems.append("TOPLIST COUNT MISMATCH")
    if rows:
        ranks = [int(row["rank"]) for row in rows]
        if ranks != list(range(1, 1001)):
            problems.append("TOPLIST RANK SEQUENCE MISMATCH")
        if any(row.get("class") != "A_STRONG_CANDIDATE" for row in rows):
            problems.append("TOP 1000 CONTAINS NON-A CLASS")
        if len({row.get("field_id") for row in rows}) != len(rows):
            problems.append("TOPLIST DUPLICATE FIELD")

    html_path = dist / "index.html"
    if not html_path.exists():
        problems.append("TARGET INDEX MISSING")
        html = ""
    else:
        html = html_path.read_text(encoding="utf-8")

    field_panel_token = "$" + "{akerfroSection(p)}"
    required_html = (
        "AKERNORM_WEB_UI_V1",
        "AKERFRO_ERTOR_WEB_UI_V0A",
        'data-layer="fro"',
        "ÅkerFrö · konservärt 2026",
        "Top 1000",
        "assets/akerfro_v0a.css",
        "assets/akerfro_v0a.js",
        "window.AKERFRO_WEB_CONFIG",
        field_panel_token,
    )
    for token in required_html:
        if token not in html:
            problems.append(f"TARGET INDEX MISSING TOKEN {token}")

    css = dist / "assets/akerfro_v0a.css"
    js = dist / "assets/akerfro_v0a.js"
    for path in (css, js):
        if not path.exists() or path.stat().st_size <= 100:
            problems.append(f"WEB ASSET MISSING/TOO SMALL {path}")
    if css.exists():
        css_text = css.read_text(encoding="utf-8")
        for token in (".akf-controls", ".akf-top-row", "@media(max-width:700px)"):
            if token not in css_text:
                problems.append(f"CSS MISSING TOKEN {token}")
    if js.exists():
        js_text = js.read_text(encoding="utf-8")
        for token in ("A_STRONG_CANDIDATE", "area_logistics", "loadSidecar", "openToplist", 'requested==="fro"'):
            if token not in js_text:
                problems.append(f"JS MISSING TOKEN {token}")

    try:
        BUILD.verify_base_target(base, dist)
    except Exception as exc:
        problems.append("PROTECTED AKERNORM BASE DIFFERS: " + str(exc))

    if manifest.get("base_index_sha256") != BUILD.sha256_file(base / "index.html"):
        problems.append("MANIFEST BASE INDEX HASH MISMATCH")
    if html_path.exists() and manifest.get("patched_index_sha256") != BUILD.sha256_file(html_path):
        problems.append("MANIFEST PATCHED INDEX HASH MISMATCH")

    protected_ok = not any(
        p.startswith("PROTECTED AKERNORM BASE") for p in problems
    )
    result = {
        "schema_version": "akerfro-ertor-web-verification-v0a",
        "status": "FAIL" if problems else "PASS",
        "field_count": total_fields,
        "municipality_count": len(entries),
        "class_counts": total_classes,
        "toplist_count": len(rows),
        "akernorm_marker_present": "AKERNORM_WEB_UI_V1" in html,
        "akerfro_marker_present": "AKERFRO_ERTOR_WEB_UI_V0A" in html,
        "protected_base_byte_identical": protected_ok,
        "problems": problems,
    }
    work.mkdir(parents=True, exist_ok=True)
    (work / "verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("=" * 96)
    print("ÅkerFrö – Ärter MVP v0a WEB VERIFY")
    print("=" * 96)
    print(f"Fields: {total_fields:,} · municipalities: {len(entries)}")
    print(f"A/B/C/D: {total_classes}")
    print(f"Top list: {len(rows):,}")
    print(f"ÅkerNorm marker: {'YES' if result['akernorm_marker_present'] else 'NO'}")
    print(f"ÅkerFrö marker: {'YES' if result['akerfro_marker_present'] else 'NO'}")
    print(f"Protected ÅkerNorm base byte-identical: {'YES' if protected_ok else 'NO'}")
    if problems:
        print("\nPROBLEMS")
        for p in problems:
            print("  - " + p)
        print("=" * 96)
        print("VERIFY_AKERFRO_WEB_V0A: FAIL")
        return 2

    print("=" * 96)
    print("VERIFY_AKERFRO_WEB_V0A: PASS")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
