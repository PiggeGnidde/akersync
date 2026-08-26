#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a self-contained-ish local Leaflet QA view for STOPPUNKT D.

The HTML embeds all reference-case geometries and metadata. Leaflet/tiles are
loaded from the internet; no public ÅkerPass payload or UI is modified.
"""
from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import mapping

from common import load_config

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCAL = ROOT / "config" / "akerminne_local.json"
DEFAULT_PROJECT = ROOT / "config" / "local_paths.json"
DEFAULT_PILOT = ROOT / "data" / "derived" / "akerminne_v1a" / "pilot_skurup"
DEFAULT_QA = ROOT / "data" / "derived" / "akerminne_v1a" / "qa"


def _text(v: Any) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    s = str(v).strip()
    return s[:-2] if s.endswith(".0") else s


def _current_skurup(project: dict[str, Any], code: str = "1264") -> gpd.GeoDataFrame:
    spath = Path(project["skiften"])
    try:
        g = gpd.read_file(spath, where=f"CAST(region_kod AS TEXT) LIKE '{code}%'")
        if len(g):
            return g
    except Exception:
        pass
    bpath = Path(project["blocks"])
    try:
        blocks = gpd.read_file(bpath, where=f"CAST(region_kod AS TEXT) LIKE '{code}%'")
    except Exception:
        blocks = gpd.read_file(bpath)
        blocks = blocks[blocks["region_kod"].astype(str).str.startswith(code)].copy()
    allowed = set(blocks["blockid"].astype(str))
    g = gpd.read_file(spath, bbox=tuple(float(v) for v in blocks.total_bounds))
    return g[g["blockid"].astype(str).isin(allowed)].copy()


def _to_wgs84_geometry(geom: Any, crs: Any) -> dict[str, Any]:
    s = gpd.GeoSeries([geom], crs=crs).to_crs(4326)
    return mapping(s.iloc[0])


def _feature(geom: Any, crs: Any, props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "Feature", "geometry": _to_wgs84_geometry(geom, crs), "properties": props}


def _historical_path(raw_root: Path, year: int) -> Path:
    return raw_root / "akerminne_v1a" / str(year) / f"arslager_skifte_skurup_{year}.gpkg"


def build_cases(checklist: pd.DataFrame, components: pd.DataFrame, current: gpd.GeoDataFrame, raw_root: Path) -> list[dict[str, Any]]:
    current = current.copy()
    current["current_field_id"] = current["blockid"].map(_text) + "|" + current["skiftesbeteckning"].map(_text)
    by_current = current.set_index("current_field_id", drop=False)
    hist_cache: dict[int, gpd.GeoDataFrame] = {}
    cases: list[dict[str, Any]] = []

    for i, row in enumerate(checklist.itertuples(index=False), start=1):
        year = int(row.history_year)
        fid = str(row.current_field_id)
        if fid not in by_current.index:
            raise RuntimeError(f"Current reference field missing: {fid}")
        crow = by_current.loc[fid]
        if isinstance(crow, pd.DataFrame):
            crow = crow.iloc[0]
        current_geom = crow.geometry
        current_feature = _feature(current_geom, current.crs, {
            "layer": "current_2025", "current_field_id": fid, "year": 2025,
        })

        comp = components[(components["history_year"] == year) & (components["current_field_id"].astype(str) == fid)].copy()
        hist_features: list[dict[str, Any]] = []
        intersection_features: list[dict[str, Any]] = []

        if len(comp):
            if year not in hist_cache:
                hp = _historical_path(raw_root, year)
                if not hp.exists():
                    raise FileNotFoundError(f"Historical source missing: {hp}")
                h = gpd.read_file(hp)
                h["historical_field_id"] = h["blockid"].map(_text) + "|" + h["skiftesbeteckning"].map(_text)
                hist_cache[year] = h
            h = hist_cache[year]
            wanted = set(comp["historical_field_id"].astype(str))
            hs = h[h["historical_field_id"].isin(wanted)].copy()
            if len(hs) != len(wanted):
                missing = sorted(wanted - set(hs["historical_field_id"]))
                raise RuntimeError(f"Historical reference geometry missing for {year}: {missing}")
            h_by_id = hs.set_index("historical_field_id", drop=False)
            for c in comp.sort_values(["intersection_m2", "historical_field_id"], ascending=[False, True]).itertuples(index=False):
                hid = str(c.historical_field_id)
                hr = h_by_id.loc[hid]
                if isinstance(hr, pd.DataFrame):
                    hr = hr.iloc[0]
                props = {
                    "layer": "historical", "historical_field_id": hid,
                    "crop_code_raw": _text(c.crop_code_raw),
                    "crop_subcategory_raw": _text(c.crop_subcategory_raw),
                    "intersection_m2": float(c.intersection_m2),
                    "share_current": float(c.share_current),
                    "share_historical": float(c.share_historical),
                }
                hist_features.append(_feature(hr.geometry, h.crs, props))
                inter = current_geom.intersection(hr.geometry)
                if not inter.is_empty and float(inter.area) > 0:
                    intersection_features.append(_feature(inter, current.crs, props | {"layer": "intersection"}))

        cases.append({
            "index": i,
            "qa_category": str(row.qa_category),
            "history_year": year,
            "current_field_id": fid,
            "status": str(row.status),
            "coverage_display": float(row.coverage_display),
            "second_crop_share": float(row.second_crop_share),
            "identity_match_confidence": str(row.identity_match_confidence),
            "overlap_excess_raw": float(row.overlap_excess_raw),
            "current": {"type": "FeatureCollection", "features": [current_feature]},
            "historical": {"type": "FeatureCollection", "features": hist_features},
            "intersections": {"type": "FeatureCollection", "features": intersection_features},
        })
    return cases


HTML = r'''<!doctype html>
<html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ÅkerMinne v1a – Visual QA</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
html,body{height:100%;margin:0;font-family:system-ui,-apple-system,Segoe UI,Arial,sans-serif;background:#f5f5f3;color:#1f2520}
#app{display:grid;grid-template-columns:390px 1fr;height:100%}#side{padding:16px;overflow:auto;border-right:1px solid #ccc;background:#fff}#map{height:100%}
h1{font-size:20px;margin:0 0 4px}.muted{color:#68706a;font-size:12px}.nav{display:flex;gap:8px;margin:12px 0}.nav button,select,.review button,#export{font:inherit;padding:8px 10px;border:1px solid #bbb;border-radius:6px;background:#fff;cursor:pointer}select{width:100%}
.card{border:1px solid #ddd;border-radius:8px;padding:10px;margin:10px 0;background:#fafafa}.grid{display:grid;grid-template-columns:145px 1fr;gap:5px;font-size:13px}.badge{display:inline-block;padding:3px 7px;border-radius:999px;background:#e9ece9;font-weight:600;font-size:12px}
.legend div{margin:4px 0}.sw{display:inline-block;width:18px;height:9px;margin-right:6px;border:2px solid;vertical-align:middle}.current{border-color:#1565c0}.hist{border-color:#ef6c00;background:rgba(239,108,0,.2)}.inter{border-color:#2e7d32;background:rgba(46,125,50,.28)}
.review button.active{outline:3px solid #333}.ok{background:#e7f4e8!important}.bad{background:#fde9e7!important}textarea{width:100%;box-sizing:border-box;min-height:72px;margin-top:8px;font:inherit;padding:7px}
#progress{font-weight:600;margin:8px 0}#export{width:100%;margin-top:8px;background:#f1f4f1}@media(max-width:800px){#app{grid-template-columns:1fr;grid-template-rows:48% 52%}#side{border-right:0;border-bottom:1px solid #ccc;padding:10px}}
</style></head><body><div id="app"><aside id="side">
<h1>ÅkerMinne · STOPPUNKT D</h1><div class="muted">Visuell kontroll: 2025-skifte vs historisk geometri</div>
<div class="nav"><button id="prev">← Föregående</button><button id="next">Nästa →</button></div><select id="caseSelect"></select>
<div id="info" class="card"></div>
<div class="card legend"><strong>Lager</strong><div><span class="sw current"></span>2025-skifte</div><div><span class="sw hist"></span>Historisk originalpolygon</div><div><span class="sw inter"></span>Faktisk överlappning</div><div class="muted">Lager kan slås av/på i kartans lagerkontroll.</div></div>
<div class="card review"><strong>Bedömning</strong><div id="progress"></div><button id="okBtn" class="ok">OK</button> <button id="badBtn" class="bad">GRANSKA</button><textarea id="note" placeholder="Kort notering (frivillig)"></textarea><button id="export">Exportera review CSV</button></div>
</aside><div id="map"></div></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
const CASES=__CASES__;
const STORAGE='akerminne_visual_review_v1a'; let reviews=JSON.parse(localStorage.getItem(STORAGE)||'{}'); let idx=0;
const map=L.map('map',{preferCanvas:true}); const osm=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap contributors'}).addTo(map);
let currentLayer=L.geoJSON(null),histLayer=L.geoJSON(null),interLayer=L.geoJSON(null); currentLayer.addTo(map);histLayer.addTo(map);interLayer.addTo(map);
L.control.layers({'OpenStreetMap':osm},{'2025-skifte':currentLayer,'Historiska polygoner':histLayer,'Överlappning':interLayer},{collapsed:false}).addTo(map);
function key(c){return c.history_year+'|'+c.current_field_id}
function pct(x){return (100*x).toFixed(x<.01?3:1)+'%'}
function histPopup(f){const p=f.properties||{};return `<b>${p.historical_field_id||''}</b><br>Råkod: ${p.crop_code_raw||'–'} / ${p.crop_subcategory_raw||'–'}<br>Andel av 2025-skifte: ${pct(p.share_current||0)}<br>Andel av historiskt skifte: ${pct(p.share_historical||0)}<br>Överlapp: ${(p.intersection_m2||0).toFixed(0)} m²`}
function styleCurrent(){return {color:'#1565c0',weight:4,fillOpacity:.03}}
function styleHist(){return {color:'#ef6c00',weight:3,fillColor:'#ef6c00',fillOpacity:.15}}
function styleInter(){return {color:'#2e7d32',weight:2,fillColor:'#2e7d32',fillOpacity:.28}}
function render(){const c=CASES[idx]; document.getElementById('caseSelect').value=idx; currentLayer.clearLayers();histLayer.clearLayers();interLayer.clearLayers();
 currentLayer.addData(c.current); currentLayer.setStyle(styleCurrent); histLayer.addData(c.historical); histLayer.setStyle(styleHist); histLayer.eachLayer(l=>l.bindPopup(histPopup(l.feature))); interLayer.addData(c.intersections); interLayer.setStyle(styleInter);
 const group=L.featureGroup([currentLayer,histLayer]); if(group.getBounds().isValid()) map.fitBounds(group.getBounds().pad(.18));
 document.getElementById('info').innerHTML=`<span class="badge">${c.qa_category}</span><h3 style="margin:7px 0">${c.history_year} · ${c.current_field_id}</h3><div class="grid"><span>Status</span><b>${c.status}</b><span>Täckning</span><b>${pct(c.coverage_display)}</b><span>Andra grödan</span><b>${pct(c.second_crop_share)}</b><span>Identitet</span><b>${c.identity_match_confidence}</b><span>Overlap excess</span><b>${pct(c.overlap_excess_raw)}</b><span>Historiska polygoner</span><b>${c.historical.features.length}</b></div>`;
 const r=reviews[key(c)]||{}; document.getElementById('note').value=r.note||''; document.getElementById('okBtn').classList.toggle('active',r.verdict==='OK'); document.getElementById('badBtn').classList.toggle('active',r.verdict==='GRANSKA'); updateProgress();}
function save(verdict){const c=CASES[idx],k=key(c),note=document.getElementById('note').value; reviews[k]={verdict:verdict||(reviews[k]||{}).verdict||'',note}; localStorage.setItem(STORAGE,JSON.stringify(reviews));render()}
function updateProgress(){let n=0;for(const c of CASES){if((reviews[key(c)]||{}).verdict)n++}document.getElementById('progress').textContent=`Bedömda ${n}/${CASES.length}`}
function move(d){idx=(idx+d+CASES.length)%CASES.length;render()}
function csvEscape(v){const s=String(v??'');return /[",\n]/.test(s)?'"'+s.replaceAll('"','""')+'"':s}
function exportCsv(){const head=['qa_category','history_year','current_field_id','status','coverage_display','second_crop_share','identity_match_confidence','overlap_excess_raw','verdict','note'];const rows=[head.join(',')];for(const c of CASES){const r=reviews[key(c)]||{};rows.push([c.qa_category,c.history_year,c.current_field_id,c.status,c.coverage_display,c.second_crop_share,c.identity_match_confidence,c.overlap_excess_raw,r.verdict||'',r.note||''].map(csvEscape).join(','))}const blob=new Blob(['\ufeff'+rows.join('\r\n')],{type:'text/csv;charset=utf-8'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='akerminne_visual_review.csv';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
const sel=document.getElementById('caseSelect'); CASES.forEach((c,i)=>{const o=document.createElement('option');o.value=i;o.textContent=`${i+1}. ${c.qa_category} · ${c.history_year} · ${c.current_field_id}`;sel.appendChild(o)});sel.onchange=()=>{idx=Number(sel.value);render()};
document.getElementById('prev').onclick=()=>move(-1);document.getElementById('next').onclick=()=>move(1);document.getElementById('okBtn').onclick=()=>save('OK');document.getElementById('badBtn').onclick=()=>save('GRANSKA');document.getElementById('note').onchange=()=>save(null);document.getElementById('export').onclick=exportCsv;document.addEventListener('keydown',e=>{if(e.target.tagName==='TEXTAREA')return;if(e.key==='ArrowLeft')move(-1);if(e.key==='ArrowRight')move(1)});render();
</script></body></html>'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--local-config", default=str(DEFAULT_LOCAL))
    ap.add_argument("--project-local-config", default=str(DEFAULT_PROJECT))
    ap.add_argument("--pilot-dir", default=str(DEFAULT_PILOT))
    ap.add_argument("--qa-dir", default=str(DEFAULT_QA))
    args = ap.parse_args()

    local = load_config(args.local_config)
    project = load_config(args.project_local_config)
    raw_root = Path(local["raw_root"])
    pilot = Path(args.pilot_dir)
    qa = Path(args.qa_dir)
    checklist_path = qa / "reference_sample_checklist.csv"
    components_path = pilot / "akerminne_components.parquet"
    if not checklist_path.exists():
        raise FileNotFoundError(f"Reference checklist missing: {checklist_path}")
    if not components_path.exists():
        raise FileNotFoundError(f"Components missing: {components_path}")

    checklist = pd.read_csv(checklist_path, dtype={"current_field_id": str})
    components = pd.read_parquet(components_path)
    current = _current_skurup(project)
    if len(checklist) != 20 or checklist["current_field_id"].nunique() != 20:
        raise RuntimeError("Visual QA requires the representative 20-row / 20-field checklist")
    cases = build_cases(checklist, components, current, raw_root)
    if len(cases) != 20:
        raise RuntimeError(f"Expected 20 cases, got {len(cases)}")

    html = HTML.replace("__CASES__", json.dumps(cases, ensure_ascii=False, separators=(",", ":")))
    out = qa / "akerminne_visual_qa.html"
    out.write_text(html, encoding="utf-8")
    manifest = {
        "schema_version": "akerminne-visual-qa-v1a",
        "cases": len(cases),
        "years": sorted({c["history_year"] for c in cases}),
        "historical_polygon_count": sum(len(c["historical"]["features"]) for c in cases),
        "intersection_polygon_count": sum(len(c["intersections"]["features"]) for c in cases),
        "output": str(out),
        "note": "Local STOPPUNKT D QA only; public ÅkerPass UI unchanged.",
    }
    (qa / "akerminne_visual_qa_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=" * 78)
    print("ÅkerMinne v1a · visual geometry QA · STOPPUNKT D")
    print("=" * 78)
    print(f"Cases: {len(cases)}; years: {manifest['years']}")
    print(f"Historical polygons: {manifest['historical_polygon_count']}; intersections: {manifest['intersection_polygon_count']}")
    print("HTML:", out)
    print("Review all 20 cases, mark OK/GRANSKA, then export akerminne_visual_review.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
