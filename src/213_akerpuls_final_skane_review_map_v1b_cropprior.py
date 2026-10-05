#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build ÅkerPuls final Skåne review map v1b with blind 2026 crop Top-3.

Consumes only frozen artefacts:
- proposal-only split/merge geometry v1;
- formally frozen blind M4 2026 field prior.

No model fit, no 2026 crop labels, no 2026 Sentinel crop evidence, no threshold
tuning and no geometry mutation are performed.

The M4 prior was trained from ÅkerMinne history through 2025 plus frozen static
context. It is therefore preserved as a prospective benchmark against:
A) official 2026 crop information when released;
B) independent satellite crop detection (e.g. rapeseed).

Each official 2025 field is clickable. The popup shows frozen Top-3 crop prior.
Fields not touched by a split or merge proposal are flagged CLEAN for a direct
field-level 2026 benchmark. For touched fields the same parent-field prior is
shown with an explicit geometry-change caveat.
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

M4_DIR = Path(r"C:\AkerSyncRepo\work\akerpuls_m4_2026_prior_v1")
M4_PRIOR = M4_DIR / "M4_2026_FIELD_PRIOR.parquet"
M4_FREEZE = Path(r"C:\AkerSyncRepo\work\akerpuls_m4_2026_prior_freeze_v1\AKERPULS_M4_2026_PRIOR_FREEZE_V1.json")
EXPECTED_M4_PRIOR_SHA = "c595553436047132bdf280a685add4e123f579722ba353cbd8906ee778c1e3b8"
EXPECTED_M4_FREEZE_SHA = "61766d03b238d792c773664d40493b184a69823f984f3b7915185dbcda330f95"

DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_final_skane_review_map_v1b_cropprior")
STATUS = "PASS_TO_FINAL_SKANE_REVIEW_MAP_V1B_CROPPRIOR"

EXPECTED_FIELDS = 128636
EXPECTED_SPLIT = 613
EXPECTED_SPLIT_NOGEOM = 5
EXPECTED_MERGE = 2182
EXPECTED_MERGE_HIGH = 1103
EXPECTED_MERGE_STANDARD = 1079
EXPECTED_VETO = 54
EXPECTED_CLASSES = 16
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


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def geojson(gdf) -> str:
    return gdf.to_json(drop_id=True, ensure_ascii=False)


def verify_frozen_inputs():
    for p, expected, name in [
        (PACKAGE_GPKG, EXPECTED_GPKG_SHA, "proposal GPKG"),
        (PACKAGE_POLICY, EXPECTED_POLICY_SHA, "proposal policy"),
        (M4_PRIOR, EXPECTED_M4_PRIOR_SHA, "M4 2026 prior"),
        (M4_FREEZE, EXPECTED_M4_FREEZE_SHA, "M4 2026 prior freeze"),
    ]:
        if not p.is_file():
            raise FileNotFoundError(p)
        got = sha(p)
        if got != expected:
            raise RuntimeError(f"{name} SHA changed: {got}")

    policy = read_json(PACKAGE_POLICY)
    pp = policy.get("product_policy", {})
    required_policy = {
        "canonical_geometry": "OFFICIAL_2025_GEOMETRY",
        "split_proposals": EXPECTED_SPLIT,
        "merge_proposals": EXPECTED_MERGE,
        "merge_high_confidence_proposals": EXPECTED_MERGE_HIGH,
        "low_hprior_veto_boundaries": EXPECTED_VETO,
        "automatic_boundary_removal": False,
        "cross_block_merge_allowed": False,
        "geometry_mutated": False,
        "merge_v1_is_proposal_only": True,
    }
    for key, value in required_policy.items():
        if pp.get(key) != value:
            raise RuntimeError(f"Proposal policy changed: {key}={pp.get(key)}")

    m4f = read_json(M4_FREEZE)
    if m4f.get("status") != "FROZEN_AKERPULS_M4_2026_PRIOR_V1":
        raise RuntimeError("Unexpected M4 freeze status")
    if int(m4f.get("fields", -1)) != EXPECTED_FIELDS or int(m4f.get("classes", -1)) != EXPECTED_CLASSES:
        raise RuntimeError("M4 frozen population/class census changed")
    if m4f.get("key_artefacts", {}).get("M4_2026_FIELD_PRIOR.parquet") != EXPECTED_M4_PRIOR_SHA:
        raise RuntimeError("M4 freeze no longer pins canonical prior parquet")
    guards = m4f.get("guards", {})
    if guards.get("2026_crop_labels_used") is not False or guards.get("2026_satellite_used") is not False:
        raise RuntimeError("M4 2026 prior is not blind to 2026 outcome/satellite")
    return policy, m4f


def proposal_popup_columns(gdf, name: str):
    # GPKG contains original M0 columns plus the frozen-ranking copies (_x/_y).
    for base in ("satellite_merge_score", "satellite_score_percentile"):
        xcol, ycol = base + "_x", base + "_y"
        if xcol not in gdf.columns or ycol not in gdf.columns:
            raise RuntimeError(f"{name} missing frozen duplicate {base} columns")
        a = pd.to_numeric(gdf[xcol], errors="coerce")
        b = pd.to_numeric(gdf[ycol], errors="coerce")
        both = a.notna() & b.notna()
        if bool(both.any()) and not bool(((a[both] - b[both]).abs() <= 1e-12).all()):
            raise RuntimeError(f"{name} duplicate frozen columns disagree for {base}")

    cols = [
        "pair_key", "field_a", "field_b",
        "satellite_merge_score_y", "satellite_score_percentile_y",
        "p_samecrop", "hprior_percentile", "geometry",
    ]
    x = gdf[cols].copy().rename(columns={
        "satellite_merge_score_y": "satellite_merge_score",
        "satellite_score_percentile_y": "satellite_score_percentile",
    })
    return x


def make_html(chunk_files: list[str]) -> str:
    tags = "\n".join('<script src="data/' + x + '"></script>' for x in chunk_files)
    html = """<!doctype html>
<html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ÅkerPuls – Skåne 2026 review v1b + ÅkerMinne Top-3</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
html,body,#map{height:100%;margin:0}body{font-family:Arial,sans-serif}
.info{background:#fff;padding:10px 12px;border-radius:6px;box-shadow:0 1px 5px #777;max-width:450px;line-height:1.35}
.info b{font-size:15px}.small{font-size:12px;color:#444}.tiny{font-size:11px;color:#555}
.legend i{display:inline-block;width:25px;height:4px;margin-right:7px;vertical-align:middle}
.cropRow{display:flex;justify-content:space-between;gap:16px;min-width:230px}
.clean{color:#167a36;font-weight:bold}.caveat{color:#a14a00;font-weight:bold}
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
<script src="data/split_no_geometry.js"></script>
<script src="data/merge_high.js"></script>
<script src="data/merge_standard.js"></script>
<script src="data/merge_veto.js"></script>
<script>
const map=L.map('map',{preferCanvas:true}).setView([55.95,13.45],9);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap contributors'}).addTo(map);
const canvas=L.canvas({padding:0.4});
let splitDrop=null;

function pct(x){const v=Number(x);return Number.isFinite(v)?(100*v).toFixed(1)+' %':'–';}
function n3(x){const v=Number(x);return Number.isFinite(v)?v.toFixed(3):'';}
function fieldPopup(p){
 const status=p.clean_benchmark ?
   '<span class="clean">CLEAN benchmarkfält</span> – ingen split/merge-proposal' :
   '<span class="caveat">Geometriförändrings-proposal</span> – priorn avser 2025-parentfältet';
 return '<b>ÅkerMinne/M4 – blind grödprior 2026</b><br>'+
   '<span class="tiny">Fält: '+p.parent_field_id_2025+'</span><br><br>'+
   '<div class="cropRow"><b>1. '+p.top1_class+'</b><b>'+pct(p.top1_prob)+'</b></div>'+
   '<div class="cropRow">2. '+p.top2_class+'<span>'+pct(p.top2_prob)+'</span></div>'+
   '<div class="cropRow">3. '+p.top3_class+'<span>'+pct(p.top3_prob)+'</span></div><br>'+
   status+'<br>'+
   '<span class="tiny">Giltiga historikår: '+Number(p.valid_history_years).toFixed(0)+
   ' · fryst före 2026-grödkoder och utan 2026-Sentinel.</span>';
}
function bindHover(layer,base,hover){
 layer.on('mouseover',function(e){e.target.setStyle(hover);});
 layer.on('mouseout',function(e){e.target.setStyle(base);});
}

const fields=L.layerGroup();
for(const fc of window.AKERPULS_FIELD_CHUNKS){
 const gj=L.geoJSON(fc,{
   renderer:canvas,
   style:{color:'#59616b',weight:0.9,opacity:0.82,fill:false,interactive:true},
   onEachFeature:function(f,l){l.bindPopup(fieldPopup(f.properties),{maxWidth:380});}
 });
 gj.addTo(fields);
}
fields.addTo(map);

const splitBase={color:'#00bcd4',weight:4,opacity:0.98};
const splitHover={color:'#00bcd4',weight:7,opacity:1};
const splitLines=L.geoJSON(window.AKERPULS_SPLIT_PROPOSALS,{
 renderer:canvas,style:splitBase,
 onEachFeature:function(f,l){
   bindHover(l,splitBase,splitHover);
   l.bindPopup('<b>Split proposal v1</b><br>2025 parent: '+f.properties.parent_field_id_2025+
     '<br><span class="small">Fryst review-only splitlinje. 2025-geometrin är canonical.</span>');
   l.on('click',function(e){
     if(splitDrop){map.removeLayer(splitDrop);}
     splitDrop=L.marker(e.latlng).addTo(map);
   });
 }
});
const splits=L.layerGroup([splitLines]).addTo(map);

const highBase={color:'#dc2626',weight:4,opacity:0.95,dashArray:'8 5'};
const highHover={color:'#dc2626',weight:7,opacity:1,dashArray:'8 5'};
const mh=L.geoJSON(window.AKERPULS_MERGE_HIGH,{
 renderer:canvas,style:highBase,
 onEachFeature:function(f,l){
   bindHover(l,highBase,highHover);
   l.bindPopup('<b>Merge proposal – P95 high-confidence marker</b><br>'+f.properties.field_a+' ↔ '+f.properties.field_b+
   '<br>S2026 pct: '+n3(f.properties.satellite_score_percentile)+'<br>Hprior pct: '+n3(f.properties.hprior_percentile)+
   '<br><span class="small">Boundary proposal only — gränsen har INTE tagits bort.</span>');
 }
}).addTo(map);

const stdBase={color:'#f59e0b',weight:3,opacity:0.9,dashArray:'6 5'};
const stdHover={color:'#f59e0b',weight:6,opacity:1,dashArray:'6 5'};
const ms=L.geoJSON(window.AKERPULS_MERGE_STANDARD,{
 renderer:canvas,style:stdBase,
 onEachFeature:function(f,l){
   bindHover(l,stdBase,stdHover);
   l.bindPopup('<b>Merge proposal v1</b><br>'+f.properties.field_a+' ↔ '+f.properties.field_b+
   '<br>S2026 pct: '+n3(f.properties.satellite_score_percentile)+'<br>Hprior pct: '+n3(f.properties.hprior_percentile)+
   '<br><span class="small">P90–P95 proposal only — gränsen har INTE tagits bort.</span>');
 }
});

const vetoBase={color:'#7e22ce',weight:4,opacity:0.95,dashArray:'2 5'};
const vetoHover={color:'#7e22ce',weight:7,opacity:1,dashArray:'2 5'};
const veto=L.geoJSON(window.AKERPULS_MERGE_VETO,{
 renderer:canvas,style:vetoBase,
 onEachFeature:function(f,l){
   bindHover(l,vetoBase,vetoHover);
   l.bindPopup('<b>Low-Hprior veto</b><br>'+f.properties.field_a+' ↔ '+f.properties.field_b+
   '<br>S2026 pct: '+n3(f.properties.satellite_score_percentile)+'<br>Hprior pct: '+n3(f.properties.hprior_percentile)+
   '<br><span class="small">2025-gränsen behålls i merge-v1.</span>');
 }
});

const nog=L.geoJSON(window.AKERPULS_SPLIT_NO_GEOMETRY,{
 renderer:canvas,style:{color:'#eab308',weight:3,fill:false,opacity:0.95},
 onEachFeature:function(f,l){l.bindPopup('<b>Split candidate utan geometri-proposal</b><br>2025 parent: '+f.properties.parent_field_id_2025);}
});

L.control.layers(null,{
 '2025 fältgränser + ÅkerMinne Top-3':fields,
 '613 split proposals':splits,
 '1103 merge proposals P95 high-confidence':mh,
 '1079 övriga merge proposals P90–P95':ms,
 '54 low-Hprior veto':veto,
 '5 split utan geometri':nog
},{collapsed:false}).addTo(map);

const info=L.control({position:'topleft'});
info.onAdd=function(){
 const d=L.DomUtil.create('div','info');
 d.innerHTML='<b>ÅkerPuls – Skåne 2026 review v1b</b><br><br>'+
 '<b>128 636</b> officiella 2025 fält – klickbara med blind ÅkerMinne/M4 Top-3 för 2026<br>'+
 '<b>613</b> split proposals<br>'+
 '<b>2 182</b> merge proposals, varav <b>1 103</b> P95 high-confidence marker<br>'+
 '<b>54</b> low-Hprior veto<br><br>'+
 '<span class="small">Grå 2025-geometri är fortsatt canonical. Crop-priorn är fryst före officiell 2026-grödinformation och använder ingen 2026-Sentinel; den kan därför benchmarkas prospektivt.</span>';
 return d;
};
info.addTo(map);

const leg=L.control({position:'bottomright'});
leg.onAdd=function(){
 const d=L.DomUtil.create('div','info legend');
 d.innerHTML='<i style="background:#59616b"></i>2025 canonical – klicka för Top-3<br>'+
 '<i style="background:#00bcd4"></i>split proposal<br>'+
 '<i style="background:#dc2626"></i>P95 merge proposal<br>'+
 '<i style="background:#f59e0b"></i>P90–P95 merge proposal<br>'+
 '<i style="background:#7e22ce"></i>low-Hprior veto';
 return d;
};
leg.addTo(map);
</script></body></html>"""
    return html.replace("__FIELD_TAGS__", tags)


def main() -> int:
    import geopandas as gpd

    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    head = git_guard()
    out = Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Output already exists: {out}")

    print("V1B_PROGRESS=VERIFY_FROZEN_GEOMETRY_AND_M4_PRIOR", flush=True)
    verify_frozen_inputs()

    official = gpd.read_file(PACKAGE_GPKG, layer="official_2025_fields")
    split = gpd.read_file(PACKAGE_GPKG, layer="split_proposal_lines_v1")
    nog = gpd.read_file(PACKAGE_GPKG, layer="split_no_geometry_proposal")
    merge = gpd.read_file(PACKAGE_GPKG, layer="merge_proposal_boundaries_v1")
    high = gpd.read_file(PACKAGE_GPKG, layer="merge_high_confidence_proposal")
    veto = gpd.read_file(PACKAGE_GPKG, layer="merge_low_hprior_veto")

    expected_layers = [
        ("official", official, EXPECTED_FIELDS),
        ("split", split, EXPECTED_SPLIT),
        ("split_no_geometry", nog, EXPECTED_SPLIT_NOGEOM),
        ("merge", merge, EXPECTED_MERGE),
        ("merge_high", high, EXPECTED_MERGE_HIGH),
        ("veto", veto, EXPECTED_VETO),
    ]
    for name, gdf, n in expected_layers:
        if len(gdf) != n:
            raise RuntimeError(f"{name} count changed: {len(gdf)} != {n}")
        if gdf.crs is None:
            raise RuntimeError(f"{name} CRS missing")

    official["parent_field_id_2025"] = official["parent_field_id_2025"].astype(str)
    if official["parent_field_id_2025"].duplicated().any():
        raise RuntimeError("Official field IDs not unique")

    # D2A / map lineage uses legacy IDs: 2025|BLOCKID|SKIFTESBETECKNING.
    # Frozen M4 uses the stable field key: BLOCKID|SKIFTESBETECKNING.
    # Bridge the namespaces explicitly and losslessly; never fuzzy-match IDs.
    if not bool(official["parent_field_id_2025"].str.startswith("2025|").all()):
        raise RuntimeError("Official legacy IDs are not uniformly prefixed with 2025|")
    official["m4_field_id"] = official["parent_field_id_2025"].str.slice(5)
    if official["m4_field_id"].duplicated().any():
        raise RuntimeError("2025-prefix removal is not one-to-one")

    high_ids = set(high["pair_key"].astype(str))
    merge_ids = set(merge["pair_key"].astype(str))
    standard = merge.loc[~merge["pair_key"].astype(str).isin(high_ids)].copy()
    if len(standard) != EXPECTED_MERGE_STANDARD:
        raise RuntimeError(f"Expected {EXPECTED_MERGE_STANDARD} standard merge proposals, got {len(standard)}")

    print("V1B_PROGRESS=LOAD_AND_JOIN_FROZEN_M4_TOP3", flush=True)
    prior_cols = [
        "current_field_id",
        "top1_class", "top1_prob",
        "top2_class", "top2_prob",
        "top3_class", "top3_prob",
        "entropy", "valid_history_years",
    ]
    prior = pd.read_parquet(M4_PRIOR, columns=prior_cols)
    prior["current_field_id"] = prior["current_field_id"].astype(str)
    if len(prior) != EXPECTED_FIELDS or prior["current_field_id"].nunique() != EXPECTED_FIELDS:
        raise RuntimeError("M4 prior population/uniqueness changed")
    if prior[prior_cols].isna().any().any():
        raise RuntimeError("M4 Top-3 prior contains nulls")

    oid = set(official["m4_field_id"])
    pid = set(prior["current_field_id"])
    if oid != pid:
        raise RuntimeError(
            f"Official/M4 bridged field-ID sets differ: official_only={len(oid-pid)} prior_only={len(pid-oid)}"
        )

    legacy_by_m4 = official.set_index("m4_field_id")["parent_field_id_2025"].to_dict()

    split_ids_legacy = set(split["parent_field_id_2025"].astype(str)) | set(nog["parent_field_id_2025"].astype(str))
    if len(split_ids_legacy) != EXPECTED_SPLIT + EXPECTED_SPLIT_NOGEOM:
        raise RuntimeError("Split-touched field census is not 618 unique parents")
    if not all(x.startswith("2025|") for x in split_ids_legacy):
        raise RuntimeError("Split proposal IDs are not in legacy 2025| namespace")
    split_ids = {x[5:] for x in split_ids_legacy}

    merge_field_ids_legacy = set(merge["field_a"].astype(str)) | set(merge["field_b"].astype(str))
    if not all(x.startswith("2025|") for x in merge_field_ids_legacy):
        raise RuntimeError("Merge proposal IDs are not in legacy 2025| namespace")
    merge_field_ids = {x[5:] for x in merge_field_ids_legacy}

    crop = prior.copy()
    crop["parent_field_id_2025"] = crop["current_field_id"].map(legacy_by_m4)
    if crop["parent_field_id_2025"].isna().any():
        raise RuntimeError("M4-to-legacy ID bridge is incomplete")
    crop["split_proposal_touch"] = crop["current_field_id"].isin(split_ids)
    crop["merge_proposal_touch"] = crop["current_field_id"].isin(merge_field_ids)
    crop["geometry_change_proposal"] = crop["split_proposal_touch"] | crop["merge_proposal_touch"]
    crop["clean_geometry_for_2026_benchmark"] = ~crop["geometry_change_proposal"]

    def geom_status(row):
        s = bool(row["split_proposal_touch"])
        m = bool(row["merge_proposal_touch"])
        if s and m:
            return "SPLIT_AND_MERGE_PROPOSAL"
        if s:
            return "SPLIT_PROPOSAL"
        if m:
            return "MERGE_PROPOSAL"
        return "CLEAN"
    crop["geometry_status"] = crop.apply(geom_status, axis=1)

    clean_n = int(crop["clean_geometry_for_2026_benchmark"].sum())
    touched_n = EXPECTED_FIELDS - clean_n
    split_touch_n = int(crop["split_proposal_touch"].sum())
    merge_touch_n = int(crop["merge_proposal_touch"].sum())
    overlap_touch_n = int((crop["split_proposal_touch"] & crop["merge_proposal_touch"]).sum())

    print(f"M4_TOP3_FIELDS={len(crop)}")
    print(f"CLEAN_BENCHMARK_FIELDS={clean_n}")
    print(f"GEOMETRY_PROPOSAL_TOUCHED_FIELDS={touched_n}")
    print(f"SPLIT_TOUCHED_FIELDS={split_touch_n} MERGE_TOUCHED_FIELDS={merge_touch_n} SPLIT_MERGE_OVERLAP={overlap_touch_n}")

    joined = official.merge(
        crop.drop(columns=["parent_field_id_2025"]),
        left_on="m4_field_id",
        right_on="current_field_id",
        how="left",
        validate="one_to_one",
    )
    if len(joined) != EXPECTED_FIELDS or joined["top1_class"].isna().any():
        raise RuntimeError("Official/M4 Top-3 join incomplete")

    out.mkdir(parents=True, exist_ok=False)
    data = out / "data"
    data.mkdir()

    exact = out / "akerpuls_2026_proposal_geometry_v1.gpkg"
    shutil.copy2(PACKAGE_GPKG, exact)
    if sha(exact) != EXPECTED_GPKG_SHA:
        raise RuntimeError("Copied proposal GPKG changed")

    benchmark_cols = [
        "parent_field_id_2025",
        "current_field_id",
        "top1_class", "top1_prob",
        "top2_class", "top2_prob",
        "top3_class", "top3_prob",
        "entropy", "valid_history_years",
        "split_proposal_touch", "merge_proposal_touch",
        "geometry_change_proposal", "clean_geometry_for_2026_benchmark",
        "geometry_status",
    ]
    bench_parquet = out / "AKERMINNE_M4_2026_TOP3_BENCHMARK.parquet"
    bench_csv = out / "AKERMINNE_M4_2026_TOP3_BENCHMARK.csv.gz"
    crop[benchmark_cols].to_parquet(bench_parquet, index=False, compression="zstd")
    crop[benchmark_cols].to_csv(bench_csv, index=False, compression="gzip", encoding="utf-8")

    print("V1B_PROGRESS=BUILD_CLICKABLE_BROWSER_FIELDS", flush=True)
    display_cols = [
        "parent_field_id_2025",
        "top1_class", "top1_prob",
        "top2_class", "top2_prob",
        "top3_class", "top3_prob",
        "valid_history_years",
        "clean_geometry_for_2026_benchmark",
        "geometry_status",
        "geometry",
    ]
    fields = joined[display_cols].copy().to_crs(EXPECTED_EPSG)
    fields = fields.rename(columns={"clean_geometry_for_2026_benchmark": "clean_benchmark"})
    for c in ("top1_prob", "top2_prob", "top3_prob"):
        fields[c] = fields[c].astype(float).round(6)
    fields["valid_history_years"] = fields["valid_history_years"].astype(float).round(0)
    fields["geometry"] = fields.geometry.simplify(DISPLAY_SIMPLIFY_M, preserve_topology=True)
    fields = fields.to_crs(4326)

    chunks = []
    for no, start in enumerate(range(0, len(fields), DISPLAY_CHUNK_SIZE), 1):
        part = fields.iloc[start:start + DISPLAY_CHUNK_SIZE]
        name = f"fields_{no:03d}.js"
        write_text(data / name, "window.AKERPULS_FIELD_CHUNKS.push(" + geojson(part) + ");\n")
        chunks.append(name)
        if no == 1 or no % 5 == 0 or start + DISPLAY_CHUNK_SIZE >= len(fields):
            print(f"V1B_FIELDS={min(start + DISPLAY_CHUNK_SIZE, len(fields))}/{len(fields)}", flush=True)

    splitw = split[["parent_field_id_2025", "geometry"]].to_crs(4326)
    nogw = nog[["parent_field_id_2025", "geometry"]].to_crs(4326)
    highw = proposal_popup_columns(high, "merge_high").to_crs(4326)
    stdw = proposal_popup_columns(standard, "merge_standard").to_crs(4326)
    vetow = proposal_popup_columns(veto, "merge_veto").to_crs(4326)

    write_text(data / "split_proposals.js", "window.AKERPULS_SPLIT_PROPOSALS=" + geojson(splitw) + ";\n")
    write_text(data / "split_no_geometry.js", "window.AKERPULS_SPLIT_NO_GEOMETRY=" + geojson(nogw) + ";\n")
    write_text(data / "merge_high.js", "window.AKERPULS_MERGE_HIGH=" + geojson(highw) + ";\n")
    write_text(data / "merge_standard.js", "window.AKERPULS_MERGE_STANDARD=" + geojson(stdw) + ";\n")
    write_text(data / "merge_veto.js", "window.AKERPULS_MERGE_VETO=" + geojson(vetow) + ";\n")

    html = out / "index.html"
    write_text(html, make_html(chunks))

    qa = {
        "schema_version": "akerpuls-final-skane-review-map-v1b-cropprior-qa",
        "status": STATUS,
        "official_2025_fields": EXPECTED_FIELDS,
        "split_proposals": EXPECTED_SPLIT,
        "merge_proposals": EXPECTED_MERGE,
        "merge_high_confidence": EXPECTED_MERGE_HIGH,
        "merge_standard": EXPECTED_MERGE_STANDARD,
        "low_hprior_veto": EXPECTED_VETO,
        "m4_top3_fields": EXPECTED_FIELDS,
        "m4_prior_freeze_sha256": EXPECTED_M4_FREEZE_SHA,
        "m4_prior_parquet_sha256": EXPECTED_M4_PRIOR_SHA,
        "clean_benchmark_fields": clean_n,
        "geometry_proposal_touched_fields": touched_n,
        "split_touched_fields": split_touch_n,
        "merge_touched_fields": merge_touch_n,
        "split_merge_overlap_fields": overlap_touch_n,
        "crop_prior_uses_2026_crop_labels": False,
        "crop_prior_uses_2026_sentinel": False,
        "canonical_geometry": "OFFICIAL_2025_GEOMETRY",
        "automatic_boundary_removal": False,
        "geometry_mutated": False,
    }
    qap = out / "AKERPULS_FINAL_SKANE_REVIEW_MAP_V1B_CROPPRIOR_QA.json"
    write_json(qap, qa)

    outputs = [
        exact, bench_parquet, bench_csv, html, qap,
        data / "split_proposals.js", data / "split_no_geometry.js",
        data / "merge_high.js", data / "merge_standard.js", data / "merge_veto.js",
    ] + [data / x for x in chunks]
    hashes = {
        p.relative_to(out).as_posix(): {"sha256": sha(p), "bytes": int(p.stat().st_size)}
        for p in outputs
    }

    manifest = {
        "schema_version": "akerpuls-final-skane-review-map-v1b-cropprior",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "parents": {
            "proposal_policy_freeze_sha256": EXPECTED_POLICY_SHA,
            "proposal_exact_gpkg_sha256": EXPECTED_GPKG_SHA,
            "m4_2026_prior_freeze_sha256": EXPECTED_M4_FREEZE_SHA,
            "m4_2026_prior_parquet_sha256": EXPECTED_M4_PRIOR_SHA,
        },
        "crop_prior_contract": {
            "target_year": 2026,
            "id_bridge": "LEGACY_2025_PREFIX_STRIPPED_EXACTLY_ONCE__2025|BLOCKID|SKIFTE_TO_BLOCKID|SKIFTE",
            "history_through_year": 2025,
            "top3_persisted_before_2026_validation": True,
            "2026_crop_labels_used": False,
            "2026_sentinel_used": False,
            "future_benchmark_A": "OFFICIAL_2026_CROP_INFORMATION",
            "future_benchmark_B": "INDEPENDENT_SATELLITE_CROP_DETECTION_INCLUDING_RAPESEED",
        },
        "benchmark_population": {
            "all_fields": EXPECTED_FIELDS,
            "clean_geometry_for_direct_field_level_benchmark": clean_n,
            "geometry_change_proposal_touched": touched_n,
            "definition_clean": "NO_SPLIT_PROPOSAL_AND_NO_MERGE_PROPOSAL",
        },
        "ui_changes": {
            "official_2025_boundaries_thicker": True,
            "split_hover_highlight": True,
            "split_click_drop_marker": True,
            "proposal_hover_highlight": True,
            "field_click_top3_crop_prior": True,
        },
        "policy_lock": {
            "canonical_geometry": "OFFICIAL_2025_GEOMETRY",
            "merge_v1_proposal_only": True,
            "automatic_boundary_removal": False,
            "geometry_mutated": False,
        },
        "output_hashes": hashes,
        "next": "VISUAL_REVIEW_AND_FREEZE_V1B_CROPPRIOR_BENCHMARK",
    }
    mp = out / "AKERPULS_FINAL_SKANE_REVIEW_MAP_V1B_CROPPRIOR_MANIFEST.json"
    write_json(mp, manifest)

    print("AKERPULS FINAL SKANE REVIEW MAP V1B + BLIND M4 TOP3")
    print(f"STATUS={STATUS}")
    print(f"PROPOSAL_POLICY_FREEZE_SHA256={EXPECTED_POLICY_SHA}")
    print(f"M4_2026_PRIOR_FREEZE_SHA256={EXPECTED_M4_FREEZE_SHA}")
    print(f"M4_2026_PRIOR_PARQUET_SHA256={EXPECTED_M4_PRIOR_SHA}")
    print("ID_BRIDGE=STRIP_EXACT_2025_PREFIX__ONE_TO_ONE_PASS")
    print(f"OFFICIAL_2025_FIELDS={EXPECTED_FIELDS}")
    print(f"SPLIT_PROPOSALS={EXPECTED_SPLIT} MERGE_PROPOSALS={EXPECTED_MERGE}")
    print(f"CLEAN_BENCHMARK_FIELDS={clean_n}")
    print(f"GEOMETRY_PROPOSAL_TOUCHED_FIELDS={touched_n}")
    print("FIELD_CLICK_TOP3=TRUE")
    print("CROP_PRIOR_2026_LABELS_USED=FALSE CROP_PRIOR_2026_SENTINEL_USED=FALSE")
    print("CANONICAL_GEOMETRY=OFFICIAL_2025_GEOMETRY AUTOMATIC_BOUNDARY_REMOVAL=FALSE")
    print(f"BENCHMARK_PARQUET_SHA256={sha(bench_parquet)}")
    print(f"BENCHMARK_CSV_GZ_SHA256={sha(bench_csv)}")
    print(f"HTML_SHA256={sha(html)}")
    print(f"MANIFEST_SHA256={sha(mp)}")
    print(f"OPEN_MAP={html}")
    print("NEXT=VISUAL_REVIEW_AND_FREEZE_V1B_CROPPRIOR_BENCHMARK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
