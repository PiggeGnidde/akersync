#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Browser-map compatibility wrapper for ÅkerPuls preliminary fields 2026 map v1.

Fixes only browser-map delivery/rendering:
  * use OSM's current raster URL https://tile.openstreetmap.org/{z}/{x}/{y}.png
    instead of the legacy {s}.tile.openstreetmap.org form;
  * embed a small critical subset of Leaflet layout CSS in the generated HTML so
    tiles/panes/canvas remain correctly positioned even if the external Leaflet
    stylesheet is blocked or not applied;
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

# Critical Leaflet layout rules. These are intentionally limited to positioning,
# z-order, pointer handling and basic controls. They are a browser-rendering
# fallback only; they do not affect any geographic coordinates or project data.
CRITICAL_LEAFLET_CSS = r"""
/* AKERPULS_LEAFLET_CRITICAL_CSS: local fallback for Leaflet layout */
.leaflet-container{position:relative;overflow:hidden;-webkit-tap-highlight-color:transparent;background:#ddd;outline-offset:1px}
.leaflet-pane,.leaflet-tile,.leaflet-marker-icon,.leaflet-marker-shadow,.leaflet-tile-container,
.leaflet-pane>svg,.leaflet-pane>canvas,.leaflet-zoom-box,.leaflet-image-layer,.leaflet-layer{
  position:absolute;left:0;top:0
}
.leaflet-tile,.leaflet-marker-icon,.leaflet-marker-shadow{-webkit-user-select:none;-moz-user-select:none;user-select:none;-webkit-user-drag:none}
.leaflet-marker-icon,.leaflet-marker-shadow{display:block}
.leaflet-container .leaflet-overlay-pane svg{max-width:none!important;max-height:none!important}
.leaflet-container .leaflet-marker-pane img,.leaflet-container .leaflet-shadow-pane img,
.leaflet-container .leaflet-tile-pane img,.leaflet-container img.leaflet-image-layer,
.leaflet-container .leaflet-tile{max-width:none!important;max-height:none!important;width:auto;padding:0}
.leaflet-tile{filter:inherit;visibility:hidden}
.leaflet-tile-loaded{visibility:inherit}
.leaflet-pane{z-index:400}.leaflet-tile-pane{z-index:200}.leaflet-overlay-pane{z-index:400}
.leaflet-shadow-pane{z-index:500}.leaflet-marker-pane{z-index:600}.leaflet-tooltip-pane{z-index:650}.leaflet-popup-pane{z-index:700}
.leaflet-map-pane canvas{z-index:100}.leaflet-map-pane svg{z-index:200}
.leaflet-zoom-animated{transform-origin:0 0}
.leaflet-marker-icon,.leaflet-marker-shadow,.leaflet-image-layer,.leaflet-pane>svg path,.leaflet-tile-container{pointer-events:none}
.leaflet-marker-icon.leaflet-interactive,.leaflet-image-layer.leaflet-interactive,.leaflet-pane>svg path.leaflet-interactive,
svg.leaflet-image-layer.leaflet-interactive path{pointer-events:auto}
.leaflet-interactive{cursor:pointer}.leaflet-grab{cursor:grab}.leaflet-dragging .leaflet-grab{cursor:grabbing}
.leaflet-control{position:relative;z-index:800;pointer-events:auto}
.leaflet-top,.leaflet-bottom{position:absolute;z-index:1000;pointer-events:none}
.leaflet-top{top:0}.leaflet-right{right:0}.leaflet-bottom{bottom:0}.leaflet-left{left:0}
.leaflet-control{float:left;clear:both}.leaflet-right .leaflet-control{float:right}
.leaflet-top .leaflet-control{margin-top:10px}.leaflet-bottom .leaflet-control{margin-bottom:10px}
.leaflet-left .leaflet-control{margin-left:10px}.leaflet-right .leaflet-control{margin-right:10px}
.leaflet-control-zoom a{display:block;text-align:center;text-decoration:none;width:30px;height:30px;line-height:30px;background:#fff;color:#000;border-bottom:1px solid #ccc}
.leaflet-control-zoom a:first-child{border-radius:4px 4px 0 0}.leaflet-control-zoom a:last-child{border-radius:0 0 4px 4px;border-bottom:0}
.leaflet-control-attribution{background:rgba(255,255,255,.8);margin:0;padding:0 5px;font-size:11px}
""".strip()


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
    marker = "AKERPULS_LEAFLET_CRITICAL_CSS"
    if marker in html:
        raise RuntimeError("Critical Leaflet CSS already unexpectedly present in base HTML")
    if "</head>" not in html:
        raise RuntimeError("Generated HTML has no </head> insertion point")
    html = html.replace("</head>", f'<style id="akerpuls-leaflet-critical-css">{CRITICAL_LEAFLET_CSS}</style></head>', 1)
    if marker not in html:
        raise RuntimeError("Critical Leaflet CSS injection failed")
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
