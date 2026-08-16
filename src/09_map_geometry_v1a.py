#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd

# Conservative land-use grouping for visual QA.
# These are explicit non-arable pasture/meadow/fabod/restoration codes in
# Jordbruksverket's crop-code guidance. V1a keeps the raw crop code as source
# truth and does NOT turn this into a machineability score.
PASTURE_MEADOW_CODES = {52, 53, 55, 61, 89, 90, 95}
OTHER_NON_CROP_CODES = {314}

# Labels are deliberately partial. Unknown codes are shown as raw crop codes
# rather than guessed. This keeps the map useful even when code lists change.
CROP_LABELS = {
    49: "slåtter-/betesvall på åkermark",
    50: "slåtter-/betesvall på åkermark",
    52: "betesmark (inte åker)",
    53: "slåtteräng (inte åker)",
    55: "fäbodbete",
    57: "slåttervall på åker",
    61: "fäbodbete",
    66: "anpassad skyddszon",
    77: "skyddszon",
    80: "grönfoder",
    83: "julgranar",
    88: "övrig odling på åkermark",
    89: "mosaikbetesmark",
    90: "gräsfattig mark",
    95: "betesmark/slåtteräng under restaurering",
    314: "annan markanvändning på åkermark",
}

HTML = '''<!doctype html><html lang="sv"><head><meta charset="utf-8"/>
<title>ÅkerSync Geometry V1a karta</title><meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
html,body,#map{height:100%;margin:0}
.panel{position:absolute;top:10px;left:10px;z-index:1000;background:#fffffff2;padding:10px 12px;border-radius:8px;max-width:430px;font:13px Arial;box-shadow:0 2px 10px #0002}
.sw{display:inline-block;width:12px;height:12px;margin-right:6px;vertical-align:middle}
.filters{margin:9px 0 6px}.filters button{font:12px Arial;margin:2px 2px 2px 0;padding:5px 7px;border:1px solid #bbb;border-radius:5px;background:white;cursor:pointer}.filters button.active{background:#333;color:white;border-color:#333}
.note{font-size:11px;color:#555;line-height:1.3;margin-top:6px}
</style>
</head><body><div class="panel"><b>ÅkerSync Geometry V1a</b><br>Visuell QA av kandidater och extrema skiftesformer.<br><br>
<div><span class="sw" style="background:#18a558"></span>Königsegg-kandidat (4/4)</div>
<div><span class="sw" style="background:#0b72ff"></span>Stark kandidat (3/4)</div>
<div><span class="sw" style="background:#f39c12"></span>Extrem / specialfall</div>
<div><span class="sw" style="background:#d81b60"></span>Svår form</div>
<div class="filters">
<b>Markanvändning:</b><br>
<button id="f-all" class="active" onclick="setFilter('all')">Alla (__N_ALL__)</button>
<button id="f-crop" onclick="setFilter('crop')">Odling/åker (__N_CROP__)</button>
<button id="f-pasture" onclick="setFilter('pasture')">Bete/slåtter (__N_PASTURE__)</button>
<button id="f-unknown" onclick="setFilter('unknown')">Okänd/annan (__N_UNKNOWN__)</button>
</div>
<div class="note">"Odling/åker" är ett konservativt QA-filter: tydliga betes-/slåtterkoder och kod 314 tas bort. Rå grödkod visas alltid i popup. Ingen Geometry-score ändras.</div>
</div><div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
const map=L.map('map');L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap'}).addTo(map);
const gj=__GEOJSON__;
function sty(f){const c=f.properties.map_class; const m={konigsegg:'#18a558',strong:'#0b72ff',extreme:'#f39c12',difficult:'#d81b60'}; return {color:m[c]||'#666',weight:c==='konigsegg'?3:2,fillColor:m[c]||'#666',fillOpacity:.42};}
function fmt(v,n=3){return (v===null||v===undefined||Number.isNaN(Number(v)))?'–':Number(v).toFixed(n)}
function pop(p){return `<b>${p.kommun} · ${p.skiftesbeteckning}</b><br>Block: ${p.blockid}<br>Kategori: ${p.category}<br><b>Grödkod: ${p.crop_code_display}</b><br>Markgrupp: ${p.crop_group_label}<br>Areal: ${fmt(p.area_ha,2)} ha<br>Rectangularity: ${fmt(p.rectangularity)}<br>Convexity: ${fmt(p.convexity)}<br>MBR-aspekt: ${fmt(p.mbr_aspect_ratio)}<br>ERL-proxy: ${fmt(p.erl_proxy_m,1)} m<br>Hål: ${p.hole_count}`;}
let layer=null;
function featuresFor(kind){if(kind==='all')return gj.features;if(kind==='crop')return gj.features.filter(f=>f.properties.crop_group==='crop');if(kind==='pasture')return gj.features.filter(f=>f.properties.crop_group==='pasture');return gj.features.filter(f=>f.properties.crop_group==='unknown'||f.properties.crop_group==='other');}
function setFilter(kind){if(layer)map.removeLayer(layer);const data={type:'FeatureCollection',features:featuresFor(kind)};layer=L.geoJSON(data,{style:sty,onEachFeature:(f,l)=>l.bindPopup(pop(f.properties))}).addTo(map);document.querySelectorAll('.filters button').forEach(b=>b.classList.remove('active'));document.getElementById('f-'+kind).classList.add('active');}
const allLayer=L.geoJSON(gj);if(allLayer.getLayers().length)map.fitBounds(allLayer.getBounds(),{padding:[20,20]});setFilter('all');
</script></body></html>'''


def q(s, p):
    s = pd.to_numeric(s, errors="coerce").dropna()
    return float(s.quantile(p)) if len(s) else float("nan")


def crop_code_int(v):
    if pd.isna(v):
        return None
    s = str(v).strip()
    if not s or s.lower() in {"nan", "none"}:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def add_crop_group(df):
    x = df.copy()
    x["crop_code_int"] = x.get("crop_code", pd.Series(index=x.index, dtype=object)).map(crop_code_int)

    def group(code):
        if code is None or pd.isna(code):
            return "unknown"
        if int(code) in PASTURE_MEADOW_CODES:
            return "pasture"
        if int(code) in OTHER_NON_CROP_CODES:
            return "other"
        return "crop"

    def display(code):
        if code is None or pd.isna(code):
            return "okänd"
        code = int(code)
        label = CROP_LABELS.get(code)
        return f"{code} · {label}" if label else str(code)

    x["crop_group"] = x["crop_code_int"].map(group)
    x["crop_group_label"] = x["crop_group"].map({
        "crop": "odling/åker (ej tydlig betes-/slåtterkod)",
        "pasture": "bete/slåtter/fäbodbete",
        "other": "annan markanvändning",
        "unknown": "okänd grödkod",
    })
    x["crop_code_display"] = x["crop_code_int"].map(display)
    return x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--geometry-csv", default="data/derived/geometry_v1a_skiften.csv")
    ap.add_argument("--skiften", default=r"C:/AkerSyncRaw/jv_skane_2025/arslager_skifte_skane_2025.gpkg")
    ap.add_argument("--out-html", default="dist/geometry_v1a_candidates_map.html")
    ap.add_argument("--out-csv", default="data/derived/geometry_v1a_candidates_map.csv")
    a = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    geom_csv = root / a.geometry_csv if not Path(a.geometry_csv).is_absolute() else Path(a.geometry_csv)
    out_html = root / a.out_html if not Path(a.out_html).is_absolute() else Path(a.out_html)
    out_csv = root / a.out_csv if not Path(a.out_csv).is_absolute() else Path(a.out_csv)
    skiften = Path(a.skiften) if Path(a.skiften).exists() else root / a.skiften

    df = pd.read_csv(geom_csv, dtype={"blockid": str, "skiftesbeteckning": str, "crop_code": str})
    for c in ["area_ha", "rectangularity", "convexity", "mbr_aspect_ratio", "erl_proxy_m", "perimeter_per_ha_m", "hole_count"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["hole_count"] = df["hole_count"].fillna(0).astype(int)
    df = add_crop_group(df)
    good = df[df["geometry_valid"].fillna(False).astype(bool) & df["area_ha"].gt(0)].copy()

    p90a, p90r, p90c, p90e = (q(good[c], .90) for c in ["area_ha", "rectangularity", "convexity", "erl_proxy_m"])
    base = good[good["area_ha"] >= 5].copy()
    base["hits"] = ((base["area_ha"] >= p90a).astype(int) + (base["rectangularity"] >= p90r).astype(int) + (base["convexity"] >= p90c).astype(int) + (base["erl_proxy_m"] >= p90e).astype(int))
    konig = base[(base["hits"] >= 4) & (base["hole_count"] == 0)].copy(); konig["category"] = "Königsegg-kandidat"; konig["map_class"] = "konigsegg"
    strong = base[(base["hits"] >= 3) & (base["hole_count"] == 0)].copy(); strong = strong[~((strong["blockid"] + "|" + strong["skiftesbeteckning"]).isin(konig["blockid"] + "|" + konig["skiftesbeteckning"]))].head(40); strong["category"] = "Stark kandidat"; strong["map_class"] = "strong"
    extreme = pd.concat([
        good.sort_values(["area_ha"], ascending=False).head(10),
        good[good["area_ha"] >= 1].sort_values(["rectangularity"], ascending=False).head(10),
        good[good["area_ha"] >= 1].sort_values(["erl_proxy_m"], ascending=False).head(10),
    ]).drop_duplicates(["blockid", "skiftesbeteckning"]); extreme["category"] = "Extrem / specialfall"; extreme["map_class"] = "extreme"
    difficult = pd.concat([
        good[good["area_ha"] >= 1].sort_values(["rectangularity", "area_ha"], ascending=[True, False]).head(15),
        good[good["area_ha"] >= 1].sort_values(["convexity", "area_ha"], ascending=[True, False]).head(15),
        good[good["area_ha"] >= 1].sort_values(["perimeter_per_ha_m", "area_ha"], ascending=[False, False]).head(15),
    ]).drop_duplicates(["blockid", "skiftesbeteckning"]); difficult["category"] = "Svår form"; difficult["map_class"] = "difficult"

    sel = pd.concat([konig, strong, extreme, difficult]).drop_duplicates(["blockid", "skiftesbeteckning"]).copy()
    out_cols = ["kommun", "blockid", "skiftesbeteckning", "category", "map_class", "crop_code", "crop_code_int", "crop_code_display", "crop_group", "crop_group_label", "area_ha", "rectangularity", "convexity", "mbr_aspect_ratio", "erl_proxy_m", "hole_count", "perimeter_per_ha_m"]
    sel[out_cols].to_csv(out_csv, index=False, encoding="utf-8-sig")

    g = gpd.read_file(skiften)[["blockid", "skiftesbeteckning", "geometry"]].copy()
    g["blockid"] = g["blockid"].astype(str); g["skiftesbeteckning"] = g["skiftesbeteckning"].astype(str)
    g = g.merge(sel, on=["blockid", "skiftesbeteckning"], how="inner").to_crs(4326)
    gj = json.loads(g.to_json())

    counts = g["crop_group"].value_counts().to_dict()
    html = HTML.replace("__GEOJSON__", json.dumps(gj, ensure_ascii=False))
    html = html.replace("__N_ALL__", str(len(g)))
    html = html.replace("__N_CROP__", str(int(counts.get("crop", 0))))
    html = html.replace("__N_PASTURE__", str(int(counts.get("pasture", 0))))
    html = html.replace("__N_UNKNOWN__", str(int(counts.get("unknown", 0) + counts.get("other", 0))))
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(html, encoding="utf-8")

    print("=" * 92); print("ÅkerSync · Geometry V1a · kandidatkarta + grödkod/markanvändning"); print("=" * 92)
    print(f"Visade objekt totalt:        {len(g):,}")
    print(f"Odling/åker-filter:          {int(counts.get('crop', 0)):,}")
    print(f"Bete/slåtter-filter:         {int(counts.get('pasture', 0)):,}")
    print(f"Okänd/annan markanvändning:  {int(counts.get('unknown', 0) + counts.get('other', 0)):,}")
    print(f"Königsegg-kandidater (4/4): {len(konig):,}")
    print("Output:"); print(" ", out_html); print(" ", out_csv)
    print("Geometry-råmåtten och 4/4-screenen är oförändrade; detta är bara ett QA-lager/filter.")


if __name__ == "__main__":
    main()
