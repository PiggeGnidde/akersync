#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Post-process the validated Skåne web build with Geometry V1a + field UI tweaks.

This deliberately leaves src/07_build_web.py and the validated v0.92 map shell
alone.  The enhancer runs immediately after the normal web build and adds:

* compact Geometry V1a raw descriptors to skifte popups (NO score),
* a scrollable popup also on desktop; mobile keeps its existing bounded popup,
* expandable secondary geometry details,
* a small GPS dot instead of Leaflet's large default pin.

Geometry is embedded as compact arrays per skifte to avoid repeating long JSON
property names in already-large municipality HTML files.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from common import load_config

ROOT = Path(__file__).resolve().parents[1]

# Compact embedded order. Keep in sync with GEOM_IDX_NOTE and JS below.
GEOM_COLS = [
    "area_ha",                       # 0
    "rectangularity",                # 1
    "convexity",                     # 2
    "compactness_4piA_P2",           # 3
    "mbr_aspect_ratio",              # 4
    "hole_count",                    # 5
    "mbr_long_m",                    # 6
    "mbr_short_m",                   # 7
    "mbr_long_axis_deg_from_north",  # 8
    "erl_proxy_m",                   # 9
    "perimeter_per_ha_m",            # 10
    "hole_area_ha",                  # 11
    "component_count",               # 12
]

EXTRA_CSS = r'''
/* ÅkerSync Geometry V1a + field-validation UI -------------------------------- */
.geomHead{display:flex;align-items:baseline;justify-content:space-between;gap:8px;margin-top:1px}
.geomTag{font-size:10px;color:#555;border:1px solid #bbb;border-radius:999px;padding:1px 6px;white-space:nowrap}
.rawDetails{margin:6px 0 2px;border:1px solid #ddd;border-radius:7px;background:#fafafa}
.rawDetails>summary{cursor:pointer;padding:5px 7px;font-weight:650;user-select:none}
.rawDetails[open]>summary{border-bottom:1px solid #e3e3e3}
.rawDetails .popupgrid{padding:3px 7px 6px;margin:3px 0}
.gps-dot.leaflet-interactive{cursor:pointer}
/* Desktop gets the same principle as mobile: a bounded, internally scrollable data card. */
@media(min-width:701px){
 .leaflet-popup-content-wrapper{max-height:min(78vh,720px);overflow:hidden}
 .leaflet-popup-content{max-height:min(72vh,650px);overflow-y:auto;overflow-x:hidden;-webkit-overflow-scrolling:touch;padding-right:4px}
}
'''

GEOM_JS = r'''
function fieldGeom(p){
 return GEOM[`${p.blockid}|${p.skiftesbeteckning}`]||null;
}
function geometrySummaryHtml(p){
 const g=fieldGeom(p);
 if(!g)return '<div class="sep"></div><div><b>Geometri:</b> ingen Geometry V1a-data</div>';
 return `<div class="sep"></div>
 <div class="geomHead"><b>Geometri · skifte</b><span class="geomTag">V1a · råmått</span></div>
 <div class="popupgrid">
   <span>Geometrisk area</span><b>${fmt(g[0],2)} ha</b>
   <span>Rectangularity</span><b>${fmt(g[1],3)}</b>
   <span>Convexity</span><b>${fmt(g[2],3)}</b>
   <span>Compactness · 4πA/P²</span><b>${fmt(g[3],3)}</b>
   <span>MBR-aspekt</span><b>${fmt(g[4],2)}</b>
   <span>Hål</span><b>${fmt(g[5],0)}</b>
 </div>
 <details class="rawDetails">
   <summary>Fler geometri-råmått</summary>
   <div class="popupgrid">
     <span>MBR långsida</span><b>${fmt(g[6],1)} m</b>
     <span>MBR kortsida</span><b>${fmt(g[7],1)} m</b>
     <span>MBR långaxel från norr</span><b>${fmt(g[8],1)}°</b>
     <span>ERL-proxy</span><b>${fmt(g[9],1)} m</b>
     <span>Kant per ha</span><b>${fmt(g[10],1)} m/ha</b>
     <span>Hålarea</span><b>${fmt(g[11],3)} ha</b>
     <span>Komponenter</span><b>${fmt(g[12],0)}</b>
   </div>
 </details>
 <div class="small">Geometry V1a är transparenta råmått. Ingen sammansatt maskinbarhets- eller ÅkerScore används här.</div>`;
}

'''

OLD_GPS = "gpsLayer=L.layerGroup([L.circle([lat,lon],{radius:acc,weight:1,fillOpacity:.08}),L.marker([lat,lon]).bindPopup(`Din position<br>Noggrannhet ≈ ${Math.round(acc)} m`)]).addTo(map);"
NEW_GPS = """gpsLayer=L.layerGroup([\n     L.circle([lat,lon],{radius:acc,color:'#1f6feb',weight:1,opacity:.45,fillColor:'#1f6feb',fillOpacity:.035,interactive:false}),\n     L.circleMarker([lat,lon],{radius:4,color:'#ffffff',weight:2,fillColor:'#1f6feb',fillOpacity:1,className:'gps-dot'}).bindPopup(`Din position<br>Noggrannhet ≈ ${Math.round(acc)} m`)\n   ]).addTo(map);"""

POPUP_CHAIN = "${textureSummaryHtml(st)}${detailedSoilHtml(st,parent)}${topoSummaryHtml(blockTopo(p.blockid))}${hydroSummaryHtml(blockHydro(p.blockid))}"
POPUP_CHAIN_GEOM = "${geometrySummaryHtml(p)}${textureSummaryHtml(st)}${detailedSoilHtml(st,parent)}${topoSummaryHtml(blockTopo(p.blockid))}${hydroSummaryHtml(blockHydro(p.blockid))}"


def jnum(v):
    if pd.isna(v):
        return None
    x = float(v)
    if not np.isfinite(x):
        return None
    # Five decimals is already more than enough for display/raw QA and keeps HTML down.
    return round(x, 5)


def geometry_payload(df: pd.DataFrame, mun: str) -> dict[str, list]:
    sub = df[df["kommun"].astype(str) == mun]
    out: dict[str, list] = {}
    for r in sub.itertuples(index=False):
        key = f"{getattr(r, 'blockid')}|{getattr(r, 'skiftesbeteckning')}"
        out[key] = [jnum(getattr(r, c)) for c in GEOM_COLS]
    return out


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Kunde inte patcha {label}: förväntad text saknas")
    return text.replace(old, new, 1)


def enhance_html(html: str, geom: dict[str, list]) -> str:
    # Fresh 07_build_web output is expected, but fail clearly instead of double-patching.
    if "const GEOM=" in html or "Geometry V1a är transparenta råmått" in html:
        raise RuntimeError("HTML verkar redan Geometry V1a-patchad. Kör BUILD_WEB_ONLY.bat från början igen.")

    html = replace_once(html, "</style>", EXTRA_CSS + "\n</style>", "CSS")

    geom_json = json.dumps(geom, ensure_ascii=False, separators=(",", ":"))
    html = replace_once(
        html,
        "const ORG_LABELS=",
        f"const GEOM={geom_json};\nconst ORG_LABELS=",
        "Geometry JSON",
    )

    html = replace_once(
        html,
        "function popupForSkifte(feature){",
        GEOM_JS + "function popupForSkifte(feature){",
        "Geometry popup-funktion",
    )
    html = replace_once(html, POPUP_CHAIN, POPUP_CHAIN_GEOM, "Geometry popup-innehåll")
    html = replace_once(html, OLD_GPS, NEW_GPS, "GPS-prick")

    # Human-facing wording. Keep the model/scoring distinction explicit.
    html = html.replace(
        "Klicka på block/skifte för <b>jord + topografi + hydrologi</b>.",
        "Klicka på skifte för <b>geometri + jord + topografi + hydrologi</b>.",
    )
    html = html.replace(
        "<b>Jordbruksverket 2025 + SLU jordlager + Lantmäteriet DEM + Whitebox hydrologi.</b>",
        "<b>Jordbruksverket 2025 + Geometry V1a + SLU jordlager + Lantmäteriet DEM + Whitebox hydrologi.</b>",
    )
    html = html.replace("ÅkerSync v0.92", "ÅkerSync · Geometry V1a")
    return html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    args = ap.parse_args()

    cfg = load_config(ROOT / args.config)
    d = ROOT / cfg.get("build_dir", "data/derived")
    dist = ROOT / cfg.get("dist_dir", "dist")
    geom_path = d / "geometry_v1a_skiften.csv"
    manifest_path = dist / "municipalities.json"

    if not geom_path.exists():
        raise FileNotFoundError(f"Saknar {geom_path}. Kör RUN_GEOMETRY_V1A.bat först.")
    if not manifest_path.exists():
        raise FileNotFoundError(f"Saknar {manifest_path}. Kör först src/07_build_web.py.")

    g = pd.read_csv(
        geom_path,
        dtype={"blockid": str, "skiftesbeteckning": str, "kommun": str},
    )
    missing_cols = [c for c in ["kommun", "blockid", "skiftesbeteckning", *GEOM_COLS] if c not in g.columns]
    if missing_cols:
        raise RuntimeError("Geometry V1a saknar kolumner: " + ", ".join(missing_cols))

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print("=" * 104)
    print("ÅkerSync · web enhancement · Geometry V1a + mobil popup + liten GPS-prick")
    print("=" * 104)

    total_geom = 0
    total_added = 0
    for mun, meta in manifest.items():
        path = dist / meta["file"]
        if not path.exists():
            raise FileNotFoundError(path)
        gp = geometry_payload(g, mun)
        expected = int(meta.get("skiften", 0))
        if len(gp) != expected:
            raise RuntimeError(
                f"{mun}: Geometry V1a har {len(gp):,} skiften men webmanifest har {expected:,}. Avbryter hellre än att gömma mismatch."
            )

        before = path.stat().st_size
        html = path.read_text(encoding="utf-8")
        html = enhance_html(html, gp)
        path.write_text(html, encoding="utf-8")
        after = path.stat().st_size
        total_geom += len(gp)
        total_added += after - before
        print(f"  {mun:16s} geometri {len(gp):6,d} · +{(after-before)/1024/1024:5.2f} MB")

    print("\nWEB ENHANCEMENT: OK")
    print(f"  Geometrimatchning: {total_geom:,} / {int(g.shape[0]):,} Geometry V1a-rader")
    print(f"  Extra HTML totalt: {total_added/1024/1024:.1f} MB")
    print("  Popup: geometri + jord + topografi + hydrologi")
    print("  UI: desktop-popup begränsad/scrollbar; befintlig mobil-scroll kvar")
    print("  GPS: 4 px blå prick + diskret noggrannhetscirkel")
    print("  Score: INGEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
