#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a post-freeze satellite basemap for the frozen D2C P90+ review product.

This is visualization-only. It verifies the completed D2C freeze and the exact
frozen P90+ GeoJSON, then writes a NEW HTML file using Esri World Imagery as the
default Leaflet basemap. It never rewrites any D2C frozen artifact, ranking,
threshold, geometry, audit sample, or manifest.

The Python stage itself is zero-network. Browser tile requests occur only when
the generated HTML is opened.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_D2C = Path(r"C:\AkerSyncRepo\work\akerpuls_d2c_full_skane_freeze_review_v1")
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
EXPECTED_D2C_STATUS = "FROZEN_FULL_SKANE_QA_RANKING_V1"
EXPECTED_FREEZE_SHA256 = "60b021a5eef2483b54ea8d369ebbc7752c164ac51b113eb7faa524c9552be950"
EXPECTED_P90PLUS = 1136
EXPECTED_P95 = 618
SOURCE_GEOJSON = "d2c_review_p90plus_wgs84.geojson"
OUTPUT_HTML = "d2c_review_p90plus_satellite_map.html"
OUTPUT_MANIFEST = "d2c_review_p90plus_satellite_map_manifest.json"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_json(path: Path, obj: Any) -> None:
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def build_html(geojson_text: str) -> str:
    data = geojson_text.replace("</", "<\\/")
    return f"""<!doctype html>
<html lang=\"sv\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>ÅkerPuls D2C – P90+ satellite review</title>
<link rel=\"stylesheet\" href=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.css\">
<style>
html,body,#map{{height:100%;margin:0}}
.info{{background:rgba(255,255,255,.94);padding:8px 10px;font:13px/1.35 Arial,sans-serif;max-width:390px;box-shadow:0 1px 5px #555;border-radius:3px}}
.legend i{{display:inline-block;width:16px;height:10px;margin-right:6px}}
.leaflet-control-layers{{font:13px/1.35 Arial,sans-serif}}
</style>
</head><body><div id=\"map\"></div><script src=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.js\"></script>
<script>
const DATA={data};
const map=L.map('map');

// Review-only browser basemaps. No OpenStreetMap volunteer tile server is used.
const imagery=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{
  maxZoom:19,
  attribution:'Tiles &copy; Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community'
}}).addTo(map);
const streets=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{{z}}/{{y}}/{{x}}',{{
  maxZoom:19,
  attribution:'Tiles &copy; Esri'
}});

function esc(v){{return String(v??'').replace(/[&<>\"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}}[c]));}}
function style(f){{const hi=f.properties.qa_tier==='HIGH_PRIORITY_SPLIT_CANDIDATE';return {{color:hi?'#b30000':'#d97706',weight:hi?3:2,fillOpacity:0.13}};}}
function popup(f){{const p=f.properties;return '<b>'+esc(p.qa_tier)+'</b><br>'+esc(p.parent_field_id_2025)+'<br>fusion='+Number(p.fusion_score).toFixed(4)+'<br>history='+Number(p.prototype_p_splitmerge_2026).toFixed(4)+'<br>separation='+Number(p.separation_ratio).toFixed(3)+'<br>TRUE-LOO min Dice='+Number(p.true_loo_min_child_dice).toFixed(3)+'<br>cell='+esc(p.analysis_cell_id);}}
const candidates=L.geoJSON(DATA,{{style,onEachFeature:(f,l)=>l.bindPopup(popup(f))}}).addTo(map);
L.control.layers({{'Esri World Imagery':imagery,'Esri Street Map':streets}},{{'Frozen D2C P90+ candidates':candidates}},{{collapsed:false}}).addTo(map);
if (candidates.getBounds().isValid()) map.fitBounds(candidates.getBounds(),{{padding:[10,10]}});

const info=L.control({{position:'topright'}});
info.onAdd=()=>{{const d=L.DomUtil.create('div','info');d.innerHTML='<b>ÅkerPuls D2C – P90+ QA review</b><br>P95/high priority: 618<br>P90-only: 518<br><br><b>Satellite review layer</b><br>Polygons and ranking are the frozen D2C result. This HTML is post-freeze visualization only; no split line or geometry change is generated.';return d;}};
info.addTo(map);
const legend=L.control({{position:'bottomright'}});
legend.onAdd=()=>{{const d=L.DomUtil.create('div','info legend');d.innerHTML='<i style=\"background:#b30000\"></i>P95 high priority<br><i style=\"background:#d97706\"></i>P90-only';return d;}};
legend.addTo(map);
</script></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--d2c-dir", default=str(DEFAULT_D2C))
    args = ap.parse_args()
    head = git_guard()
    out = Path(args.d2c_dir)
    manifest_path = out / "d2c_manifest.json"
    freeze_path = out / "D2C_FULL_SKANE_QA_RANKING_FREEZE_V1.json"
    geojson_path = out / SOURCE_GEOJSON
    for p in (manifest_path, freeze_path, geojson_path):
        if not p.is_file():
            raise FileNotFoundError(p)

    manifest = read_json(manifest_path)
    if manifest.get("status") != EXPECTED_D2C_STATUS:
        raise RuntimeError(f"D2C status changed: {manifest.get('status')}")
    if manifest.get("freeze_sha256") != EXPECTED_FREEZE_SHA256:
        raise RuntimeError(f"D2C manifest freeze SHA changed: {manifest.get('freeze_sha256')}")
    if sha256_file(freeze_path) != EXPECTED_FREEZE_SHA256:
        raise RuntimeError("D2C freeze file SHA does not match the frozen review point")
    census = manifest.get("census", {})
    if int(census.get("p90plus", -1)) != EXPECTED_P90PLUS or int(census.get("p95", -1)) != EXPECTED_P95:
        raise RuntimeError(f"D2C frozen census changed: {census}")

    rec = manifest.get("output_hashes", {}).get(SOURCE_GEOJSON)
    if not rec:
        raise RuntimeError(f"D2C manifest does not contain {SOURCE_GEOJSON}")
    source_sha = sha256_file(geojson_path)
    if source_sha != rec.get("sha256"):
        raise RuntimeError("Frozen D2C P90+ GeoJSON SHA changed")

    # Parse once to verify exact feature census, then embed the original frozen text.
    gj = read_json(geojson_path)
    if gj.get("type") != "FeatureCollection" or len(gj.get("features", [])) != EXPECTED_P90PLUS:
        raise RuntimeError("Frozen D2C P90+ GeoJSON feature census changed")

    html_path = out / OUTPUT_HTML
    html = build_html(geojson_path.read_text(encoding="utf-8"))
    write_text(html_path, html)
    html_sha = sha256_file(html_path)

    post = {
        "schema_version": "akerpuls-d2c-postfreeze-satellite-review-map-v1",
        "status": "PASS_POSTFREEZE_VISUALIZATION_ONLY",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "parent_d2c_status": EXPECTED_D2C_STATUS,
        "parent_d2c_freeze_sha256": EXPECTED_FREEZE_SHA256,
        "source_geojson": str(geojson_path),
        "source_geojson_sha256": source_sha,
        "features": EXPECTED_P90PLUS,
        "p95": EXPECTED_P95,
        "output_html": str(html_path),
        "output_html_sha256": html_sha,
        "default_basemap": "ESRI_WORLD_IMAGERY",
        "fallback_basemap": "ESRI_WORLD_STREET_MAP",
        "python_network_calls": 0,
        "browser_tile_network_required": True,
        "model_executed": False,
        "thresholds_tuned": False,
        "fusion_refit": False,
        "split_line_generated": False,
        "merge_executed": False,
        "geometry_mutated": False,
        "d2c_frozen_artifacts_modified": False,
    }
    write_json(out / OUTPUT_MANIFEST, post)

    print("AKERPULS D2C POST-FREEZE SATELLITE REVIEW MAP")
    print("STATUS=PASS_POSTFREEZE_VISUALIZATION_ONLY")
    print(f"PARENT_D2C_FREEZE_SHA256={EXPECTED_FREEZE_SHA256}")
    print(f"SOURCE_P90PLUS_GEOJSON_SHA256={source_sha}")
    print(f"FEATURES={EXPECTED_P90PLUS} P95={EXPECTED_P95} P90_ONLY={EXPECTED_P90PLUS-EXPECTED_P95}")
    print("DEFAULT_BASEMAP=ESRI_WORLD_IMAGERY FALLBACK_BASEMAP=ESRI_WORLD_STREET_MAP")
    print("PYTHON_NETWORK_CALLS=0")
    print("MODEL_EXECUTED=FALSE THRESHOLDS_TUNED=FALSE FUSION_REFIT=FALSE")
    print("SPLIT_LINE_GENERATED=FALSE GEOMETRY_MUTATED=FALSE D2C_FROZEN_ARTIFACTS_MODIFIED=FALSE")
    print(f"OUTPUT={html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
