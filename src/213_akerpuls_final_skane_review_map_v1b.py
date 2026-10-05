#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerPuls final Skåne review map v1b: UI polish + frozen M4 crop top-3.

No new model is fit and no geometry/policy is changed.

UI changes versus v1:
- thicker/darker official 2025 canonical boundaries;
- thicker split proposals plus a wide transparent click target;
- small cyan midpoint dots for split proposals;
- hover highlight for proposal lines;
- unchanged 2025 fields are clickable and show frozen M4 2026 top-3 crop prior.

Crop popup scope:
- shown only when the 2025 field has neither a split proposal/no-geometry split
  candidate nor participates in any merge proposal;
- M4 is history/static prior only: history through 2025, NO Sentinel 2026.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"

PACKAGE_DIR = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_v1_policy_proposal_geometry_v1")
PACKAGE_GPKG = PACKAGE_DIR / "akerpuls_2026_proposal_geometry_v1.gpkg"
PACKAGE_POLICY = PACKAGE_DIR / "AKERPULS_MERGE_V1_POLICY_PROPOSAL_GEOMETRY_V1.json"
EXPECTED_GPKG_SHA = "af2749b0d36199cceccf0440b5f95974fc5b09d3149bc7625f951510722624a2"
EXPECTED_POLICY_SHA = "52e0e46f1fe07735c510664f67353cc6fa2e7818cbb31e1542688a2f70755394"

M4_FREEZE = Path(r"C:\AkerSyncRepo\work\akerpuls_m4_2026_prior_freeze_v1\AKERPULS_M4_2026_PRIOR_FREEZE_V1.json")
M4_PRIOR = Path(r"C:\AkerSyncRepo\work\akerpuls_m4_2026_prior_v1\M4_2026_FIELD_PRIOR.parquet")
EXPECTED_M4_FREEZE_SHA = "61766d03b238d792c773664d40493b184a69823f984f3b7915185dbcda330f95"
EXPECTED_M4_PRIOR_SHA = "c595553436047132bdf280a685add4e123f579722ba353cbd8906ee778c1e3b8"

DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_final_skane_review_map_v1b")
STATUS = "PASS_TO_FINAL_SKANE_REVIEW_MAP_V1B"

EXPECTED_FIELDS = 128636
EXPECTED_SPLIT = 613
EXPECTED_SPLIT_NOGEOM = 5
EXPECTED_MERGE = 2182
EXPECTED_MERGE_HIGH = 1103
EXPECTED_MERGE_STANDARD = 1079
EXPECTED_VETO = 54
EXPECTED_EPSG = 32633
DISPLAY_SIMPLIFY_M = 5.0
DISPLAY_CHUNK_SIZE = 5000


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_json(path: Path, obj) -> None:
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected {EXPECTED_BRANCH}, got {branch}")
    if subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip():
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def geojson(gdf) -> str:
    return gdf.to_json(drop_id=True, ensure_ascii=False)


def popup_line_js(varname: str, title: str, color: str, weight: float, extra: str) -> str:
    return f"""
function popup_{varname}(f){{
  return '<b>{title}</b><br>'+f.properties.field_a+' ↔ '+f.properties.field_b+
    '<br>S2026 pct: '+n3(f.properties.satellite_score_percentile)+
    '<br>Hprior pct: '+n3(f.properties.hprior_percentile)+
    '<br><span class="small">{extra}</span>';
}}
const {varname}=L.geoJSON(window.AKERPULS_{varname.upper()},{{
 renderer:canvas,
 style:{{color:'{color}',weight:{weight},opacity:0.94,dashArray:'8 5'}},
 onEachFeature:function(f,l){{
   l.bindPopup(popup_{varname}(f));
   const w={weight};
   l.on('mouseover',function(){{this.setStyle({{weight:w+2,opacity:1}});}});
   l.on('mouseout',function(){{this.setStyle({{weight:w,opacity:0.94}});}});
 }}
}});
"""


def make_html(chunk_files: list[str]) -> str:
    tags = "\n".join('<script src="data/' + x + '"></script>' for x in chunk_files)
    return """<!doctype html>
<html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ÅkerPuls – Skåne 2026 proposal review v1b</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
html,body,#map{height:100%;margin:0}body{font-family:Arial,sans-serif}
.info{background:#fff;padding:10px 12px;border-radius:6px;box-shadow:0 1px 5px #777;max-width:455px;line-height:1.35}
.info b{font-size:15px}.small{font-size:12px;color:#444}.crop{line-height:1.55}.legend i{display:inline-block;width:25px;height:4px;margin-right:7px;vertical-align:middle}
.leaflet-container{position:relative;overflow:hidden;background:#ddd}.leaflet-pane,.leaflet-tile,.leaflet-pane>svg,.leaflet-pane>canvas,.leaflet-layer{position:absolute;left:0;top:0}
.leaflet-pane{z-index:400}.leaflet-tile-pane{z-index:200}.leaflet-overlay-pane{z-index:400}.leaflet-control{position:relative;z-index:800}
.leaflet-top,.leaflet-bottom{position:absolute;z-index:1000;pointer-events:none}.leaflet-top{top:0}.leaflet-right{right:0}.leaflet-bottom{bottom:0}.leaflet-left{left:0}
.leaflet-control{float:left;clear:both;pointer-events:auto}.leaflet-right .leaflet-control{float:right}.leaflet-top .leaflet-control{margin-top:10px}.leaflet-bottom .leaflet-control{margin-bottom:10px}
.leaflet-left .leaflet-control{margin-left:10px}.leaflet-right .leaflet-control{margin-right:10px}
</style></head><body><div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>window.AKERPULS_FIELD_CHUNKS=[];</script>
__FIELD_TAGS__
<script src="data/split_proposals.js"></script>
<script src="data/split_midpoints.js"></script>
<script src="data/split_no_geometry.js"></script>
<script src="data/merge_high.js"></script>
<script src="data/merge_standard.js"></script>
<script src="data/merge_veto.js"></script>
<script>
const map=L.map('map',{preferCanvas:true}).setView([55.95,13.45],9);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap contributors'}).addTo(map);
const canvas=L.canvas({padding:0.4});
function n3(x){const v=Number(x);return Number.isFinite(v)?v.toFixed(3):'';}
function pct(x){const v=Number(x);return Number.isFinite(v)?(100*v).toFixed(1)+' %':'';}

function cropPopup(f){
 const p=f.properties;
 return '<div class="crop"><b>2026 grödprior (M4)</b><br>'+
   '<span class="small">2025-fält: '+p.parent_field_id_2025+'</span><br><br>'+
   '1. <b>'+p.top1_class+'</b> — '+pct(p.top1_prob)+'<br>'+
   '2. <b>'+p.top2_class+'</b> — '+pct(p.top2_prob)+'<br>'+
   '3. <b>'+p.top3_class+'</b> — '+pct(p.top3_prob)+'<br><br>'+
   '<span class="small">Prior från ÅkerMinne/historik t.o.m. 2025 + statisk kontext. <b>Sentinel 2026 är inte använd.</b> Detta är en sannolikhetsprior, inte observerad 2026-gröda.</span></div>';
}

const fields=L.layerGroup();
for(const fc of window.AKERPULS_FIELD_CHUNKS){
 L.geoJSON(fc,{
   renderer:canvas,
   style:function(f){return {color:'#555f6b',weight:1.15,opacity:0.88,fill:false,interactive:!!f.properties.crop_clickable};},
   onEachFeature:function(f,l){
     if(f.properties.crop_clickable){
       l.bindPopup(cropPopup(f));
       l.on('mouseover',function(){this.setStyle({color:'#111827',weight:2.3,fill:true,fillOpacity:0.035});});
       l.on('mouseout',function(){this.setStyle({color:'#555f6b',weight:1.15,opacity:0.88,fill:false,fillOpacity:0});});
     }
   }
 }).addTo(fields);
}
fields.addTo(map);

function splitPopup(f){
 return '<b>Split proposal v1</b><br>2025 parent: '+f.properties.parent_field_id_2025+
 '<br><span class="small">Fryst review-only splitlinje. 2025-geometrin är canonical.</span>';
}
const splits=L.geoJSON(window.AKERPULS_SPLIT_PROPOSALS,{
 renderer:canvas,style:{color:'#00a9c4',weight:4.2,opacity:0.98},
 onEachFeature:function(f,l){
   l.bindPopup(splitPopup(f));
   l.on('mouseover',function(){this.setStyle({weight:6.5,color:'#007b91'});});
   l.on('mouseout',function(){this.setStyle({weight:4.2,color:'#00a9c4'});});
 }
}).addTo(map);

/* Invisible wide hit target: easier to click a 10 m-derived line on a large map. */
const splitHit=L.geoJSON(window.AKERPULS_SPLIT_PROPOSALS,{
 renderer:canvas,style:{color:'#00a9c4',weight:14,opacity:0.01},
 onEachFeature:function(f,l){l.bindPopup(splitPopup(f));}
}).addTo(map);

/* Small midpoint dots instead of 613 large default drop pins. */
const splitDots=L.geoJSON(window.AKERPULS_SPLIT_MIDPOINTS,{
 pointToLayer:function(f,ll){return L.circleMarker(ll,{radius:4.2,color:'#007b91',weight:1.5,fillColor:'#00d2ef',fillOpacity:0.95});},
 onEachFeature:function(f,l){l.bindPopup(splitPopup(f));}
}).addTo(map);

function mergePopup(f,title,note){
 return '<b>'+title+'</b><br>'+f.properties.field_a+' ↔ '+f.properties.field_b+
 '<br>S2026 pct: '+n3(f.properties.satellite_score_percentile)+
 '<br>Hprior pct: '+n3(f.properties.hprior_percentile)+
 '<br><span class="small">'+note+'</span>';
}
function lineLayer(data,color,weight,dash,title,note,visible){
 const x=L.geoJSON(data,{
   renderer:canvas,style:{color:color,weight:weight,opacity:0.94,dashArray:dash},
   onEachFeature:function(f,l){
     l.bindPopup(mergePopup(f,title,note));
     l.on('mouseover',function(){this.setStyle({weight:weight+2,opacity:1});});
     l.on('mouseout',function(){this.setStyle({weight:weight,opacity:0.94});});
   }
 });
 if(visible)x.addTo(map);
 return x;
}
const mh=lineLayer(window.AKERPULS_MERGE_HIGH,'#dc2626',4.2,'8 5','Merge proposal – P95 high-confidence marker','Boundary proposal only — gränsen har INTE tagits bort.',true);
const ms=lineLayer(window.AKERPULS_MERGE_STANDARD,'#f59e0b',3.2,'6 5','Merge proposal v1','P90–P95 proposal only — gränsen har INTE tagits bort.',false);
const veto=lineLayer(window.AKERPULS_MERGE_VETO,'#7e22ce',4.0,'2 5','Low-Hprior veto','2025-gränsen behålls i merge-v1.',false);

const nog=L.geoJSON(window.AKERPULS_SPLIT_NO_GEOMETRY,{
 renderer:canvas,style:{color:'#eab308',weight:3.5,fill:false,opacity:0.95},
 onEachFeature:function(f,l){l.bindPopup('<b>Split candidate utan geometri-proposal</b><br>2025 parent: '+f.properties.parent_field_id_2025);}
});

L.control.layers(null,{
 '2025 fältgränser — canonical + M4 Top-3 klick':fields,
 '613 split proposals':splits,
 'Split midpoint dots':splitDots,
 '1103 merge proposals P95 high-confidence':mh,
 '1079 övriga merge proposals P90–P95':ms,
 '54 low-Hprior veto':veto,
 '5 split utan geometri':nog
},{collapsed:false}).addTo(map);

const info=L.control({position:'topleft'});
info.onAdd=function(){
 const d=L.DomUtil.create('div','info');
 d.innerHTML='<b>ÅkerPuls – Skåne 2026 proposal review v1b</b><br><br>'+
 '<b>128 636</b> officiella 2025 fält — fortsatt canonical<br>'+
 '<b>613</b> split proposals<br>'+
 '<b>2 182</b> merge proposals, varav <b>1 103</b> P95 high-confidence marker<br>'+
 '<b>54</b> low-Hprior veto<br>'+
 '<b>__CROP_CLICKABLE__</b> oförändrade fält med klickbar M4 Top-3 grödprior<br><br>'+
 '<span class="small"><b>Viktigt:</b> merge-linjer är review-proposals och har inte tagits bort. M4 Top-3 visas bara för fält utan split-/merge-proposal och bygger inte på Sentinel 2026.</span>';
 return d;
};
info.addTo(map);

const leg=L.control({position:'bottomright'});
leg.onAdd=function(){
 const d=L.DomUtil.create('div','info legend');
 d.innerHTML='<i style="background:#555f6b"></i>2025 canonical<br>'+
 '<i style="background:#00a9c4"></i>split proposal<br>'+
 '<i style="background:#dc2626"></i>P95 merge proposal<br>'+
 '<i style="background:#f59e0b"></i>P90–P95 merge proposal<br>'+
 '<i style="background:#7e22ce"></i>low-Hprior veto';
 return d;
};
leg.addTo(map);
</script></body></html>""".replace("__FIELD_TAGS__", tags)


def main() -> int:
    import geopandas as gpd

    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    head = git_guard()
    out = Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Output already exists: {out}")

    print("V1B_PROGRESS=VERIFY_FROZEN_GEOMETRY_POLICY_AND_M4_PRIOR", flush=True)
    for p, expected, name in [
        (PACKAGE_GPKG, EXPECTED_GPKG_SHA, "proposal GPKG"),
        (PACKAGE_POLICY, EXPECTED_POLICY_SHA, "proposal policy"),
        (M4_FREEZE, EXPECTED_M4_FREEZE_SHA, "M4 freeze"),
        (M4_PRIOR, EXPECTED_M4_PRIOR_SHA, "M4 prior"),
    ]:
        if not p.is_file() or sha(p) != expected:
            raise RuntimeError(f"{name} missing or changed")

    policy = json.loads(PACKAGE_POLICY.read_text(encoding="utf-8-sig"))
    pp = policy.get("product_policy", {})
    if pp.get("canonical_geometry") != "OFFICIAL_2025_GEOMETRY":
        raise RuntimeError("Canonical geometry policy changed")
    if pp.get("merge_v1_is_proposal_only") is not True or pp.get("automatic_boundary_removal") is not False:
        raise RuntimeError("Merge-v1 proposal-only policy changed")

    m4freeze = json.loads(M4_FREEZE.read_text(encoding="utf-8-sig"))
    if m4freeze.get("status") != "FROZEN_AKERPULS_M4_2026_PRIOR_V1":
        raise RuntimeError("Unexpected M4 freeze status")
    guards = m4freeze.get("guards", {})
    if guards.get("2026_satellite_used") is not False or guards.get("2026_crop_labels_used") is not False:
        raise RuntimeError("M4 prior is not the frozen blind history/static prior")

    print("V1B_PROGRESS=READ_GEOMETRY_AND_DEFINE_UNCHANGED_FIELDS", flush=True)
    official = gpd.read_file(PACKAGE_GPKG, layer="official_2025_fields")
    split = gpd.read_file(PACKAGE_GPKG, layer="split_proposal_lines_v1")
    nog = gpd.read_file(PACKAGE_GPKG, layer="split_no_geometry_proposal")
    merge = gpd.read_file(PACKAGE_GPKG, layer="merge_proposal_boundaries_v1")
    high = gpd.read_file(PACKAGE_GPKG, layer="merge_high_confidence_proposal")
    veto = gpd.read_file(PACKAGE_GPKG, layer="merge_low_hprior_veto")

    if len(official) != EXPECTED_FIELDS or len(split) != EXPECTED_SPLIT or len(nog) != EXPECTED_SPLIT_NOGEOM:
        raise RuntimeError("Official/split census changed")
    if len(merge) != EXPECTED_MERGE or len(high) != EXPECTED_MERGE_HIGH or len(veto) != EXPECTED_VETO:
        raise RuntimeError("Merge/veto census changed")

    split_affected = set(split["parent_field_id_2025"].astype(str)) | set(nog["parent_field_id_2025"].astype(str))
    merge_affected = set(merge["field_a"].astype(str)) | set(merge["field_b"].astype(str))
    changed = split_affected | merge_affected

    official["parent_field_id_2025"] = official["parent_field_id_2025"].astype(str)
    official["crop_clickable"] = ~official["parent_field_id_2025"].isin(changed)
    clickable_n = int(official["crop_clickable"].sum())
    print(f"FIELDS_WITHOUT_SPLIT_OR_MERGE_PROPOSAL={clickable_n}")
    print(f"FIELDS_EXCLUDED_FROM_CROP_POPUP={EXPECTED_FIELDS-clickable_n}")

    print("V1B_PROGRESS=JOIN_FROZEN_M4_TOP3", flush=True)
    cols = [
        "current_field_id", "top1_class", "top1_prob",
        "top2_class", "top2_prob", "top3_class", "top3_prob",
        "entropy", "valid_history_years",
    ]
    prior = pd.read_parquet(M4_PRIOR, columns=cols)
    prior["current_field_id"] = prior["current_field_id"].astype(str)
    if len(prior) != EXPECTED_FIELDS or prior["current_field_id"].nunique() != EXPECTED_FIELDS:
        raise RuntimeError("M4 prior field population changed")

    # Frozen ID namespace bridge: map uses 2025|BLOCKID|SKIFTE, M4 uses BLOCKID|SKIFTE.
    ids = official["parent_field_id_2025"].astype(str)
    if not bool(ids.str.startswith("2025|").all()):
        raise RuntimeError("Unexpected map field-ID namespace")
    official["current_field_id"] = ids.str.slice(start=5)
    if official["current_field_id"].duplicated().any():
        raise RuntimeError("ID bridge creates duplicate M4 IDs")

    joined = official.merge(prior, on="current_field_id", how="left", validate="one_to_one")
    needed = ["top1_class","top1_prob","top2_class","top2_prob","top3_class","top3_prob"]
    if joined[needed].isna().any().any():
        raise RuntimeError("M4 Top-3 join has missing values")

    probs = joined[["top1_prob","top2_prob","top3_prob"]].to_numpy(dtype=float)
    if not np.isfinite(probs).all() or (probs < 0).any() or (probs > 1).any():
        raise RuntimeError("M4 Top-3 probabilities invalid")
    if not bool((probs[:,0] >= probs[:,1]).all() and (probs[:,1] >= probs[:,2]).all()):
        raise RuntimeError("M4 Top-3 probabilities are not ordered")

    high_ids = set(high["pair_key"].astype(str))
    standard = merge.loc[~merge["pair_key"].astype(str).isin(high_ids)].copy()
    if len(standard) != EXPECTED_MERGE_STANDARD:
        raise RuntimeError("Standard merge proposal census changed")

    out.mkdir(parents=True, exist_ok=False)
    data = out / "data"
    data.mkdir()
    exact = out / "akerpuls_2026_proposal_geometry_v1.gpkg"
    shutil.copy2(PACKAGE_GPKG, exact)
    if sha(exact) != EXPECTED_GPKG_SHA:
        raise RuntimeError("Exact GPKG copy changed")

    print("V1B_PROGRESS=BUILD_CLICKABLE_FIELD_CHUNKS", flush=True)
    keep = [
        "parent_field_id_2025","crop_clickable",
        "top1_class","top1_prob","top2_class","top2_prob","top3_class","top3_prob",
        "geometry",
    ]
    display = joined[keep].copy().to_crs(EXPECTED_EPSG)
    display["geometry"] = display.geometry.simplify(DISPLAY_SIMPLIFY_M, preserve_topology=True)
    display = display.to_crs(4326)

    chunks = []
    for no, start in enumerate(range(0, len(display), DISPLAY_CHUNK_SIZE), 1):
        part = display.iloc[start:start+DISPLAY_CHUNK_SIZE]
        name = f"fields_{no:03d}.js"
        write_text(data/name, "window.AKERPULS_FIELD_CHUNKS.push(" + geojson(part) + ");\n")
        chunks.append(name)
        if no == 1 or no % 5 == 0 or start + DISPLAY_CHUNK_SIZE >= len(display):
            print(f"V1B_FIELDS={min(start+DISPLAY_CHUNK_SIZE,len(display))}/{len(display)}", flush=True)

    propcols = ["pair_key","field_a","field_b","p_samecrop","hprior_percentile","geometry"]
    def popup_view(gdf):
        score = "satellite_score_percentile_y" if "satellite_score_percentile_y" in gdf.columns else "satellite_score_percentile"
        cols2 = propcols.copy()
        cols2.insert(3, score)
        x = gdf[cols2].copy().rename(columns={score:"satellite_score_percentile"})
        return x.to_crs(4326)

    splitw = split[["parent_field_id_2025","geometry"]].to_crs(4326)
    nogw = nog[["parent_field_id_2025","geometry"]].to_crs(4326)
    highw = popup_view(high)
    stdw = popup_view(standard)
    vetow = popup_view(veto)

    mid = split[["parent_field_id_2025","geometry"]].copy().to_crs(EXPECTED_EPSG)
    mid["geometry"] = mid.geometry.interpolate(0.5, normalized=True)
    mid = mid.to_crs(4326)

    write_text(data/"split_proposals.js", "window.AKERPULS_SPLIT_PROPOSALS=" + geojson(splitw) + ";\n")
    write_text(data/"split_midpoints.js", "window.AKERPULS_SPLIT_MIDPOINTS=" + geojson(mid) + ";\n")
    write_text(data/"split_no_geometry.js", "window.AKERPULS_SPLIT_NO_GEOMETRY=" + geojson(nogw) + ";\n")
    write_text(data/"merge_high.js", "window.AKERPULS_MERGE_HIGH=" + geojson(highw) + ";\n")
    write_text(data/"merge_standard.js", "window.AKERPULS_MERGE_STANDARD=" + geojson(stdw) + ";\n")
    write_text(data/"merge_veto.js", "window.AKERPULS_MERGE_VETO=" + geojson(vetow) + ";\n")

    html = out / "index.html"
    write_text(html, make_html(chunks).replace("__CROP_CLICKABLE__", f"{clickable_n:,}".replace(",", " ")))

    qa = {
        "schema_version":"akerpuls-final-skane-review-map-v1b-qa",
        "status":STATUS,
        "official_2025_fields":EXPECTED_FIELDS,
        "canonical_boundary_display_weight":1.15,
        "split_display_weight":4.2,
        "split_hit_target_weight":14,
        "split_midpoint_markers":EXPECTED_SPLIT,
        "merge_proposals":EXPECTED_MERGE,
        "merge_high_confidence":EXPECTED_MERGE_HIGH,
        "merge_standard":EXPECTED_MERGE_STANDARD,
        "low_hprior_veto":EXPECTED_VETO,
        "crop_top3_source":"FROZEN_M4_2026_HISTORY_STATIC_PRIOR",
        "m4_prior_sha256":EXPECTED_M4_PRIOR_SHA,
        "m4_2026_satellite_used":False,
        "fields_crop_clickable":clickable_n,
        "fields_crop_popup_excluded":EXPECTED_FIELDS-clickable_n,
        "crop_popup_exclusion_rule":"EXCLUDE_SPLIT_AFFECTED_OR_ANY_MERGE_PROPOSAL_FIELD",
        "geometry_mutated":False,
        "thresholds_tuned":False,
        "model_fit_executed":False,
    }
    qap = out / "AKERPULS_FINAL_SKANE_REVIEW_MAP_V1B_QA.json"
    write_json(qap, qa)

    outputs = [exact,html,qap,data/"split_proposals.js",data/"split_midpoints.js",data/"split_no_geometry.js",
               data/"merge_high.js",data/"merge_standard.js",data/"merge_veto.js"] + [data/x for x in chunks]
    hashes = {p.relative_to(out).as_posix():{"sha256":sha(p),"bytes":p.stat().st_size} for p in outputs}
    manifest = {
        "schema_version":"akerpuls-final-skane-review-map-v1b",
        "status":STATUS,
        "generated_utc":datetime.now(timezone.utc).isoformat(),
        "git_head":head,
        "parents":{
            "proposal_policy_sha256":EXPECTED_POLICY_SHA,
            "exact_geometry_gpkg_sha256":EXPECTED_GPKG_SHA,
            "m4_2026_prior_freeze_sha256":EXPECTED_M4_FREEZE_SHA,
            "m4_2026_prior_parquet_sha256":EXPECTED_M4_PRIOR_SHA,
        },
        "ui_changes":{
            "canonical_boundaries_thicker":True,
            "split_lines_thicker":True,
            "split_wide_click_target":True,
            "split_midpoint_dots":True,
            "proposal_hover_highlight":True,
            "unchanged_field_crop_top3_popup":True,
        },
        "crop_popup":{
            "source":"M4_2026_PRIOR",
            "interpretation":"HISTORY_STATIC_PRIOR_NOT_OBSERVED_2026_CROP",
            "sentinel_2026_used":False,
            "fields_clickable":clickable_n,
            "fields_excluded_due_split_or_merge_proposal":EXPECTED_FIELDS-clickable_n,
        },
        "policy_lock":{
            "canonical_geometry":"OFFICIAL_2025_GEOMETRY",
            "merge_v1_proposal_only":True,
            "automatic_boundary_removal":False,
            "geometry_mutated":False,
        },
        "output_hashes":hashes,
        "next":"HUMAN_REVIEW_V1B_UI_AND_M4_TOP3_POPUPS",
    }
    mp = out / "AKERPULS_FINAL_SKANE_REVIEW_MAP_V1B_MANIFEST.json"
    write_json(mp, manifest)

    print("AKERPULS FINAL SKANE REVIEW MAP V1B")
    print(f"STATUS={STATUS}")
    print(f"FIELDS={EXPECTED_FIELDS}")
    print(f"FIELDS_CROP_CLICKABLE={clickable_n}")
    print(f"FIELDS_CROP_POPUP_EXCLUDED={EXPECTED_FIELDS-clickable_n}")
    print(f"SPLIT_PROPOSALS={EXPECTED_SPLIT} SPLIT_MIDPOINT_DOTS={EXPECTED_SPLIT}")
    print(f"MERGE_PROPOSALS={EXPECTED_MERGE} HIGH={EXPECTED_MERGE_HIGH} STANDARD={EXPECTED_MERGE_STANDARD}")
    print("CANONICAL_BOUNDARY_WEIGHT=1.15 SPLIT_WEIGHT=4.2 SPLIT_HIT_TARGET_WEIGHT=14")
    print("CROP_TOP3_SOURCE=FROZEN_M4_2026_HISTORY_STATIC_PRIOR")
    print("M4_SENTINEL_2026_USED=FALSE")
    print("GEOMETRY_MUTATED=FALSE THRESHOLDS_TUNED=FALSE MODEL_FIT_EXECUTED=FALSE")
    print(f"HTML_SHA256={sha(html)}")
    print(f"MANIFEST_SHA256={sha(mp)}")
    print(f"OPEN_MAP={html}")
    print("NEXT=HUMAN_REVIEW_V1B_UI_AND_M4_TOP3_POPUPS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
