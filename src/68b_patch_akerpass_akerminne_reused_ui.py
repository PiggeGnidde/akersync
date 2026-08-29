#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Apply the frozen/all-Skåne ÅkerMinne UI patch using a reused web sidecar index.

This avoids requiring generated ÅkerMinne source parquet files in the current worktree.
The already-built sidecars are treated as immutable web artifacts; only dist/index.html is patched.
"""
from __future__ import annotations

import argparse
import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = ROOT / "dist" / "index.html"
DEFAULT_WEB_INDEX = ROOT / "dist" / "data" / "akerminne" / "skane_index.json"
EXPECTED_FIELDS = 128_636
EXPECTED_FIELD_YEARS = 1_414_996
EXPECTED_YEARS = list(range(2015, 2026))

PATCH68 = runpy.run_path(
    str(ROOT / "src" / "68_patch_akerpass_akerminne_skane_ui.py"),
    run_name="akerminne_skane_patch_reuse",
)


def load_mapping(web_index_path: Path) -> dict[str, str]:
    doc = json.loads(web_index_path.read_text(encoding="utf-8"))
    if doc.get("schema_version") != "akerminne-skane-web-index-v1":
        raise RuntimeError("Reused ÅkerMinne web index has wrong schema")
    entries = doc.get("municipalities") or []
    if (
        len(entries) != 33
        or int(doc.get("municipality_count", -1)) != 33
        or int(doc.get("field_count", -1)) != EXPECTED_FIELDS
        or int(doc.get("field_years", -1)) != EXPECTED_FIELD_YEARS
        or doc.get("years") != EXPECTED_YEARS
    ):
        raise RuntimeError("Reused ÅkerMinne web index is not the full Skåne 33/128636/1414996 package")

    mapping: dict[str, str] = {}
    for entry in entries:
        name = str(entry.get("municipality") or "")
        rel = str(entry.get("file") or "")
        if not name or not rel.startswith("data/akerminne/") or not rel.endswith(".json"):
            raise RuntimeError(f"Invalid ÅkerMinne web-index entry: {entry}")
        if name in mapping:
            raise RuntimeError(f"Duplicate ÅkerMinne municipality in web index: {name}")
        mapping[name] = rel
    if len(mapping) != 33 or "Skurup" not in mapping or "Lomma" not in mapping:
        raise RuntimeError("Reused ÅkerMinne mapping does not contain all 33 municipalities")
    return mapping


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default=str(DEFAULT_INDEX))
    ap.add_argument("--web-index", default=str(DEFAULT_WEB_INDEX))
    args = ap.parse_args()

    index_path = Path(args.index)
    web_index_path = Path(args.web_index)
    if not index_path.exists():
        raise FileNotFoundError(index_path)
    if not web_index_path.exists():
        raise FileNotFoundError(web_index_path)

    mapping = load_mapping(web_index_path)
    original = index_path.read_text(encoding="utf-8")
    patched = PATCH68["patch_html"](original, mapping)
    if patched == original:
        print("AKERMINNE REUSED SKÅNE UI PATCH: already present")
        return 0

    tmp = index_path.with_suffix(".akm-reuse.tmp.html")
    tmp.write_text(patched, encoding="utf-8")
    if tmp.read_text(encoding="utf-8") != patched:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("Reused ÅkerMinne UI patch write verification failed")
    index_path.unlink(missing_ok=True)
    tmp.replace(index_path)

    print(f"AKERMINNE REUSED SKÅNE UI PATCH: OK · {index_path}")
    print(f"Municipality sidecars wired: {len(mapping)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
