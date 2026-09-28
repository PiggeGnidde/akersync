#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic HTML hook patch for ÅkerVatten web v0a."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

MARKER = "AKERVATTEN_WEB_UI_V0A"
AKERFRO_MARKER = "AKERFRO_ERTOR_WEB_UI_V0A"

CONTROLS = r"""
  <div id="akervattenControls" class="akv-controls">
   <div class="akv-head">
    <span class="akv-title">ÅkerVatten · informationslager</span>
    <span class="akv-noverdict">Ingen totalscore</span>
   </div>
   <div class="akv-layer-grid">
    <button type="button" class="akv-sub active" data-akv-layer="mark_torka">MarkTorka</button>
    <button type="button" class="akv-sub" data-akv-layer="mark_vata">MarkVäta</button>
    <button type="button" class="akv-sub" data-akv-layer="small_gw">Små magasin</button>
    <button type="button" class="akv-sub" data-akv-layer="gw_drought">GW-torka</button>
    <button type="button" class="akv-sub" data-akv-layer="large_gw">Stora magasin</button>
    <button type="button" class="akv-sub" data-akv-layer="sw_drought">Ytvatten</button>
   </div>
   <div id="akvSubHint" class="akv-subhint"></div>
  </div>
"""


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one occurrence, found {count}")
    return text.replace(old, new, 1)


def patch_html(html: str, mapping: dict[str, str], regional: dict[str, str]) -> str:
    if MARKER in html:
        raise RuntimeError("ÅkerVatten patch must be applied to unpatched ÅkerFrö base")
    if AKERFRO_MARKER not in html:
        raise RuntimeError("ÅkerFrö base marker missing")
    if len(mapping) != 33 or "Kristianstad" not in mapping or "Lomma" not in mapping:
        raise RuntimeError("ÅkerVatten mapping requires all 33 municipalities")
    required_regional = {"groundwater_history", "surfacewater_history", "large_groundwater"}
    if set(regional) != required_regional:
        raise RuntimeError("ÅkerVatten regional mapping mismatch")

    out = html
    out = replace_once(
        out,
        "</head>",
        '<link rel="stylesheet" href="assets/akervatten_v0a.css">\n'
        f'<!-- {MARKER} -->\n</head>',
        "stylesheet hook",
    )

    fro = '<button class="layer-button" type="button" data-layer="fro" title="Konservärt 2026 · kandidatfält">ÅkerFrö</button>'
    vatten = '<button class="layer-button" type="button" data-layer="vatten" title="Mark, grundvatten och ytvatten · separata informationslager">ÅkerVatten</button>'
    out = replace_once(out, fro, fro + "\n   " + vatten, "layer button")

    fro_controls_anchor = (
        '<label class="akf-history"><input id="akfHistoryOutline" type="checkbox"> '
        'Markera historiska konservärtsfält 2015–2025</label>\n  </div>'
    )
    out = replace_once(
        out,
        fro_controls_anchor,
        fro_controls_anchor + "\n" + CONTROLS,
        "ÅkerVatten controls",
    )

    akf = "$" + "{akerfroSection(p)}"
    akv = "$" + "{akervattenSection(p)}"
    anchor = " " + akf + "\n <details><summary>Historik / referens</summary>"
    replacement = " " + akf + "\n " + akv + "\n <details><summary>Historik / referens</summary>"
    out = replace_once(out, anchor, replacement, "field drawer")

    config = {
        "files": mapping,
        "regional": regional,
        "schema": "akervatten-web-field-v0a",
        "overall_score": "NOT_CREATED",
        "legal_status": "NOT_ASSESSED",
    }
    config_js = json.dumps(config, ensure_ascii=False, separators=(",", ":"))
    scripts = (
        f'<script>window.AKERVATTEN_WEB_CONFIG={config_js};</script>\n'
        '<script src="assets/akervatten_v0a.js"></script>\n'
    )
    out = replace_once(out, "</body>", scripts + "</body>", "script hook")

    required = (
        MARKER,
        AKERFRO_MARKER,
        'data-layer="vatten"',
        "ÅkerVatten · informationslager",
        "Ingen totalscore",
        'data-akv-layer="mark_torka"',
        'data-akv-layer="large_gw"',
        akv,
        "assets/akervatten_v0a.css",
        "assets/akervatten_v0a.js",
        "window.AKERVATTEN_WEB_CONFIG",
    )
    missing = [token for token in required if token not in out]
    if missing:
        raise RuntimeError("Patched ÅkerVatten UI missing: " + ", ".join(missing))
    if out.count(MARKER) != 1:
        raise RuntimeError("ÅkerVatten HTML marker count mismatch")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True, type=Path)
    ap.add_argument("--web-index", required=True, type=Path)
    args = ap.parse_args()

    index = json.loads(args.web_index.read_text(encoding="utf-8-sig"))
    mapping = {str(r["municipality"]): str(r["file"]) for r in index["municipalities"]}
    regional = {str(k): str(v["file"]) for k, v in index["regional"].items()}
    patched = patch_html(args.index.read_text(encoding="utf-8"), mapping, regional)
    args.index.write_text(patched, encoding="utf-8")
    print(f"ÅkerVatten WEB UI PATCH: PASS · {args.index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
