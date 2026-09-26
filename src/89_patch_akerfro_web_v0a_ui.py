#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Small deterministic HTML hook patch for ÅkerFrö web assets."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

MARKER = "AKERFRO_ERTOR_WEB_UI_V0A"
AKERNORM_MARKER = "AKERNORM_WEB_UI_V1"

CONTROLS = r"""
  <div id="akerfroControls" class="akf-controls">
   <div class="akf-head"><span class="akf-title">ÅkerFrö · konservärt 2026</span><button id="akfTopButton" class="akf-top-btn" type="button">🏆 Top 1000</button></div>
   <div class="akf-class-row">
    <label class="akf-check"><input class="akf-class-filter" type="checkbox" value="A_STRONG_CANDIDATE" checked><span class="akf-dot" style="background:#17643c"></span>A</label>
    <label class="akf-check"><input class="akf-class-filter" type="checkbox" value="B_PHYSICAL_CANDIDATE" checked><span class="akf-dot" style="background:#72a85e"></span>B</label>
    <label class="akf-check"><input class="akf-class-filter" type="checkbox" value="C_ROTATION_CAUTION"><span class="akf-dot" style="background:#d99a3e"></span>C</label>
    <label class="akf-check"><input class="akf-class-filter" type="checkbox" value="D_NOT_HIGH_PHYSICAL_MATCH"><span class="akf-dot" style="background:#b8bcb6"></span>D</label>
   </div>
   <div class="akf-filter-grid">
    <label><span class="akf-mini-label">Bjuv-avstånd</span><select id="akfDistanceFilter" class="akf-select"><option value="all">Alla</option><option value="60">&lt;60 km</option><option value="40">&lt;40 km</option><option value="20">&lt;20 km</option></select></label>
    <label><span class="akf-mini-label">Areal</span><select id="akfAreaFilter" class="akf-select"><option value="all">Alla</option><option value="2plus">≥2 ha</option><option value="5plus">≥5 ha</option><option value="5-12">5–12 ha</option></select></label>
   </div>
   <label class="akf-history"><input id="akfHistoryOutline" type="checkbox"> Markera historiska konservärtsfält 2015–2025</label>
  </div>
"""


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one occurrence, found {count}")
    return text.replace(old, new, 1)


def patch_html(html: str, mapping: dict[str, str], toplist_file: str) -> str:
    if MARKER in html:
        raise RuntimeError("ÅkerFrö patch must be applied to unpatched ÅkerNorm base")
    if AKERNORM_MARKER not in html:
        raise RuntimeError("ÅkerNorm base marker missing")
    if len(mapping) != 33 or "Kristianstad" not in mapping or "Lomma" not in mapping:
        raise RuntimeError("ÅkerFrö mapping requires all 33 municipalities")

    out = html
    out = replace_once(
        out,
        "</head>",
        '<link rel="stylesheet" href="assets/akerfro_v0a.css">\n'
        f'<!-- {MARKER} -->\n</head>',
        "stylesheet hook",
    )

    drift = '<button class="layer-button" type="button" data-layer="drift" title="Strukturell maskinell brukbarhet">ÅkerDrift</button>'
    fro = '<button class="layer-button" type="button" data-layer="fro" title="Konservärt 2026 · kandidatfält">ÅkerFrö</button>'
    out = replace_once(out, drift, drift + "\n   " + fro, "layer button")

    out = replace_once(
        out,
        '<div id="layerHint" class="hint"></div>',
        '<div id="layerHint" class="hint"></div>\n' + CONTROLS,
        "filter controls",
    )

    akn = "$" + "{akernormSection(p)}"
    akf = "$" + "{akerfroSection(p)}"
    anchor = " " + akn + "\n <details><summary>Historik / referens</summary>"
    replacement = " " + akn + "\n " + akf + "\n <details><summary>Historik / referens</summary>"
    out = replace_once(out, anchor, replacement, "field drawer")

    config = {
        "files": mapping,
        "toplist": toplist_file,
        "schema": "akerfro-ertor-web-v0a",
    }
    config_js = json.dumps(config, ensure_ascii=False, separators=(",", ":"))
    scripts = (
        f'<script>window.AKERFRO_WEB_CONFIG={config_js};</script>\n'
        '<script src="assets/akerfro_v0a.js"></script>\n'
    )
    out = replace_once(out, "</body>", scripts + "</body>", "script hook")

    required = (
        MARKER,
        AKERNORM_MARKER,
        'data-layer="fro"',
        "ÅkerFrö · konservärt 2026",
        "Top 1000",
        "A_STRONG_CANDIDATE",
        "B_PHYSICAL_CANDIDATE",
        "C_ROTATION_CAUTION",
        "D_NOT_HIGH_PHYSICAL_MATCH",
        akf,
        "assets/akerfro_v0a.css",
        "assets/akerfro_v0a.js",
        "window.AKERFRO_WEB_CONFIG",
    )
    missing = [item for item in required if item not in out]
    if missing:
        raise RuntimeError("Patched ÅkerFrö UI missing: " + ", ".join(missing))
    if out.count(MARKER) != 1:
        raise RuntimeError("ÅkerFrö HTML marker count mismatch")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--web-index", required=True, type=Path)
    args = parser.parse_args()

    index = json.loads(args.web_index.read_text(encoding="utf-8-sig"))
    entries = index.get("municipalities") or []
    mapping = {str(row["municipality"]): str(row["file"]) for row in entries}
    patched = patch_html(
        args.index.read_text(encoding="utf-8"),
        mapping,
        str(index["toplist_file"]),
    )
    args.index.write_text(patched, encoding="utf-8")
    print(f"ÅkerFrö WEB UI PATCH: PASS · {args.index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
