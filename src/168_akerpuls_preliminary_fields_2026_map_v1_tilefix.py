#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tile-policy compatibility wrapper for ÅkerPuls preliminary fields 2026 map v1.

Fixes only browser-map delivery:
  * use OSM's current required raster URL https://tile.openstreetmap.org/{z}/{x}/{y}.png
    instead of the legacy {s}.tile.openstreetmap.org form;
  * preserve the already-fixed formal-v1 `product_policy` lineage verifier.

The map should be opened through the companion localhost HTTP launcher so the
browser sends a normal HTTP Referer. No model, thresholds, geometry, ranking,
freeze, split lines or QA semantics are changed.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "src" / "166_akerpuls_preliminary_fields_2026_map_v1.py"
POLICYFIX = ROOT / "src" / "167_akerpuls_preliminary_fields_2026_map_v1_policyfix.py"
OLD_TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
CURRENT_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def fixed_make_html(base, chunk_files: list[str]) -> str:
    html = base.make_html(chunk_files)
    if OLD_TILE_URL not in html:
        raise RuntimeError("Expected legacy OSM tile URL not found in base HTML")
    html = html.replace(OLD_TILE_URL, CURRENT_TILE_URL)
    if OLD_TILE_URL in html or CURRENT_TILE_URL not in html:
        raise RuntimeError("OSM tile URL compatibility replacement failed")
    return html


def main() -> int:
    base = load(BASE, "akerpuls_map_v1_base_tilefix")
    pf = load(POLICYFIX, "akerpuls_map_v1_policyfix_for_tilefix")
    base.verify_frozen_inputs = lambda d2c: pf.fixed_verify_frozen_inputs(base, d2c)
    base.make_html = lambda chunk_files: fixed_make_html(base_original, chunk_files)
    return int(base.main())


# Keep an unpatched base instance solely so fixed_make_html can call the original
# make_html without recursion after main() replaces base.make_html.
base_original = load(BASE, "akerpuls_map_v1_base_original_for_tilefix")


if __name__ == "__main__":
    raise SystemExit(main())
