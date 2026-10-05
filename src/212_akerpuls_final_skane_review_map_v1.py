#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build final ÅkerPuls Skåne 2026 proposal review map v1.

Consumes only the frozen proposal-only geometry package. No inference,
threshold tuning, fusion, automatic merge or geometry mutation is performed.

Display:
- gray: official 2025 canonical boundaries
- cyan: 613 split proposals
- red dashed: 1103 P95/Hprior>P25 high-confidence merge proposals
- orange dashed: remaining 1079 P90-P95/Hprior>P25 merge proposals
- purple dotted: 54 low-Hprior veto boundaries
- yellow: five split candidates without geometry proposal

Merge lines are existing 2025 boundaries proposed for review; they are not
removed from canonical geometry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"

PACKAGE_DIR = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_v1_policy_proposal_geometry_v1")
PACKAGE_GPKG = PACKAGE_DIR / "akerpuls_2026_proposal_geometry_v1.gpkg"
PACKAGE_POLICY = PACKAGE_DIR / "AKERPULS_MERGE_V1_POLICY_PROPOSAL_GEOMETRY_V1.json"

EXPECTED_GPKG_SHA = "af2749b0d36199cceccf0440b5f95974fc5b09d3149bc7625f951510722624a2"
EXPECTED_POLICY_SHA = "52e0e46f1fe07735c510664f67353cc6fa2e7818cbb31e1542688a2f70755394"

DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_final_skane_review_map_v1")
STATUS = "PASS_TO_FINAL_SKANE_REVIEW_MAP_V1"

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


def make_html(chunk_files: list[str]) -> str:
    tags = "\n".join('<script src="data/' + x + '"></script>' for x in chunk_files)
    html = """<!doctype html>
<html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ÅkerPuls – Skåne 2026 proposal review v1</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
html,body,#map{height:100%;margin:0}body{font-family:Arial,sans-serif}
.info{background:#fff;padding:10px 12px;border-radius:6px;box-shadow:0 1px 5px #777;max-width:430px;line-height:1.35}
.info b{font-size:15px}.small{font-size:12px;color:#444}.legend i{display:inline-block;width:25px;height:4px;margin-right:7px;vertical-align:middle}
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
const fields=L.layerGroup();
for(const fc of window.AKERPULS_FIELD_CHUNKS){
  L.geoJSON(fc,{renderer:canvas,style:{color:'#6b7280',weight:0.5,opacity:0.68,fill:false,interactive:false}}).addTo(fields);
}
fields.addTo(map);
function n3(x){const v=Number(x);return Number.isFinite(v)?v.toFixed(3):'';}

const splits=L.geoJSON(window.AKERPULS_SPLIT_PROPOSALS,{
 renderer:canvas,style:{color:'#00bcd4',weight:3,opacity:0.95},
 onEachFeature:function(f,l){l.bindPopup('<b>Split proposal v1</b><br>2025 parent: '+f.properties.parent_field_id_2025+'<br><span class="small">Fryst review-only splitlinje. 2025-geometrin är canonical.</span>');}
}).addTo(map);

const mh=L.geoJSON(window.AKERPULS_MERGE_HIGH,{
 renderer:canvas,style:{color:'#dc2626',weight:4,opacity:0.95,dashArray:'8 5'},
 onEachFeature:function(f,l){l.bindPopup('<b>Merge proposal – P95 high-confidence marker</b><br>'+f.properties.field_a+' ↔ '+f.properties.field_b+'<br>S2026 pct: '+n3(f.properties.satellite_score_percentile)+'<br>Hprior pct: '+n3(f.properties.hprior_percentile)+'<br><span class="small">Boundary proposal only — gränsen har INTE tagits bort.</span>');}
}).addTo(map);

const ms=L.geoJSON(window.AKERPULS_MERGE_STANDARD,{
 renderer:canvas,style:{color:'#f59e0b',weight:3,opacity:0.9,dashArray:'6 5'},
 onEachFeature:function(f,l){l.bindPopup('<b>Merge proposal v1</b><br>'+f.properties.field_a+' ↔ '+f.properties.field_b+'<br>S2026 pct: '+n3(f.properties.satellite_score_percentile)+'<br>Hprior pct: '+n3(f.properties.hprior_percentile)+'<br><span class="small">P90–P95 proposal only — gränsen har INTE tagits bort.</span>');}
});

const veto=L.geoJSON(window.AKERPULS_MERGE_VETO,{
 renderer:canvas,style:{color:'#7e22ce',weight:4,opacity:0.95,dashArray:'2 5'},
 onEachFeature:function(f,l){l.bindPopup('<b>Low-Hprior veto</b><br>'+f.properties.field_a+' ↔ '+f.properties.field_b+'<br>S2026 pct: '+n3(f.properties.satellite_score_percentile)+'<br>Hprior pct: '+n3(f.properties.hprior_percentile)+'<br><span class="small">2025-gränsen behålls i merge-v1.</span>');}
});

const nog=L.geoJSON(window.AKERPULS_SPLIT_NO_GEOMETRY,{
 renderer:canvas,style:{color:'#eab308',weight:3,fill:false,opacity:0.95},
 onEachFeature:function(f,l){l.bindPopup('<b>Split candidate utan geometri-proposal</b><br>2025 parent: '+f.properties.parent_field_id_2025);}
});

L.control.layers(null,{
 '2025 fältgränser — canonical':fields,
 '613 split proposals':splits,
 '1103 merge proposals P95 high-confidence':mh,
 '1079 övriga merge proposals P90–P95':ms,
 '54 low-Hprior veto':veto,
 '5 split utan geometri':nog
},{collapsed:false}).addTo(map);

const info=L.control({position:'topleft'});
info.onAdd=function(){
 const d=L.DomUtil.create('div','info');
 d.innerHTML='<b>ÅkerPuls – Skåne 2026 proposal review v1</b><br><br>'+
 '<b>128 636</b> officiella 2025 fält — fortsatt canonical<br>'+
 '<b>613</b> split proposals<br>'+
 '<b>2 182</b> merge proposals, varav <b>1 103</b> P95 high-confidence marker<br>'+
 '<b>54</b> low-Hprior veto<br><br>'+
 '<span class="small"><b>Viktigt:</b> merge-linjer visar befintliga 2025-gränser som modellen föreslår för review. Inga gränser är automatiskt borttagna. Final blind auto-merge gate FAIL; merge-v1 är proposal-only.</span>';
 return d;
};
info.addTo(map);

const leg=L.control({position:'bottomright'});
leg.onAdd=function(){
 const d=L.DomUtil.create('div','info legend');
 d.innerHTML='<i style="background:#6b7280"></i>2025 canonical<br>'+
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

    print("FINAL_SKANE_MAP_PROGRESS=VERIFY_FROZEN_PROPOSAL_PACKAGE", flush=True)
    if not PACKAGE_GPKG.is_file() or sha(PACKAGE_GPKG) != EXPECTED_GPKG_SHA:
        raise RuntimeError("Proposal geometry GPKG missing or changed")
    if not PACKAGE_POLICY.is_file() or sha(PACKAGE_POLICY) != EXPECTED_POLICY_SHA:
        raise RuntimeError("Proposal policy freeze missing or changed")

    policy = json.loads(PACKAGE_POLICY.read_text(encoding="utf-8-sig"))
    if policy.get("status") != "FROZEN_AKERPULS_MERGE_V1_POLICY_PROPOSAL_GEOMETRY_V1":
        raise RuntimeError("Unexpected policy-package status")
    pp = policy.get("product_policy", {})
    expected = {
        "canonical_geometry": "OFFICIAL_2025_GEOMETRY",
        "split_proposals": EXPECTED_SPLIT,
        "merge_proposals": EXPECTED_MERGE,
        "merge_high_confidence_proposals": EXPECTED_MERGE_HIGH,
        "low_hprior_veto_boundaries": EXPECTED_VETO,
        "automatic_boundary_removal": False,
        "cross_block_merge_allowed": False,
        "geometry_mutated": False,
        "merge_v1_is_proposal_only": True,
        "no_more_threshold_search_with_same_signals": True,
    }
    for key, value in expected.items():
        if pp.get(key) != value:
            raise RuntimeError(f"Frozen policy changed: {key}={pp.get(key)}")

    print("FINAL_SKANE_MAP_PROGRESS=READ_EXACT_GPKG_LAYERS", flush=True)
    official = gpd.read_file(PACKAGE_GPKG, layer="official_2025_fields")
    split = gpd.read_file(PACKAGE_GPKG, layer="split_proposal_lines_v1")
    nog = gpd.read_file(PACKAGE_GPKG, layer="split_no_geometry_proposal")
    merge = gpd.read_file(PACKAGE_GPKG, layer="merge_proposal_boundaries_v1")
    high = gpd.read_file(PACKAGE_GPKG, layer="merge_high_confidence_proposal")
    veto = gpd.read_file(PACKAGE_GPKG, layer="merge_low_hprior_veto")

    for name, gdf, n in [
        ("official", official, EXPECTED_FIELDS),
        ("split", split, EXPECTED_SPLIT),
        ("split_no_geometry", nog, EXPECTED_SPLIT_NOGEOM),
        ("merge", merge, EXPECTED_MERGE),
        ("merge_high", high, EXPECTED_MERGE_HIGH),
        ("veto", veto, EXPECTED_VETO),
    ]:
        if len(gdf) != n:
            raise RuntimeError(f"{name} count changed: {len(gdf)} != {n}")
        if gdf.crs is None:
            raise RuntimeError(f"{name} CRS missing")

    if merge["pair_key"].duplicated().any() or high["pair_key"].duplicated().any() or veto["pair_key"].duplicated().any():
        raise RuntimeError("Merge proposal/veto pair keys must be unique")

    high_ids = set(high["pair_key"].astype(str))
    merge_ids = set(merge["pair_key"].astype(str))
    veto_ids = set(veto["pair_key"].astype(str))
    if not high_ids.issubset(merge_ids):
        raise RuntimeError("High-confidence set is not subset of merge proposals")
    if merge_ids & veto_ids:
        raise RuntimeError("Merge proposal and veto sets overlap")

    standard = merge.loc[~merge["pair_key"].astype(str).isin(high_ids)].copy()
    if len(standard) != EXPECTED_MERGE_STANDARD:
        raise RuntimeError(f"Expected {EXPECTED_MERGE_STANDARD} standard merge proposals, got {len(standard)}")

    out.mkdir(parents=True, exist_ok=False)
    data = out / "data"
    data.mkdir()
    exact = out / "akerpuls_2026_proposal_geometry_v1.gpkg"
    shutil.copy2(PACKAGE_GPKG, exact)
    if sha(exact) != EXPECTED_GPKG_SHA:
        raise RuntimeError("Copied exact proposal GPKG hash changed")

    print("FINAL_SKANE_MAP_PROGRESS=BUILD_BROWSER_DISPLAY", flush=True)
    fields = official[["parent_field_id_2025", "geometry"]].copy().to_crs(EXPECTED_EPSG)
    fields["geometry"] = fields.geometry.simplify(DISPLAY_SIMPLIFY_M, preserve_topology=True)
    fields = fields.to_crs(4326)

    chunks = []
    for no, start in enumerate(range(0, len(fields), DISPLAY_CHUNK_SIZE), 1):
        part = fields.iloc[start:start + DISPLAY_CHUNK_SIZE]
        name = f"fields_{no:03d}.js"
        write_text(data / name, "window.AKERPULS_FIELD_CHUNKS.push(" + geojson(part) + ");\n")
        chunks.append(name)
        if no == 1 or no % 5 == 0 or start + DISPLAY_CHUNK_SIZE >= len(fields):
            print(f"FINAL_SKANE_MAP_FIELDS={min(start + DISPLAY_CHUNK_SIZE, len(fields))}/{len(fields)}", flush=True)

    splitw = split[["parent_field_id_2025", "geometry"]].to_crs(4326)
    nogw = nog[["parent_field_id_2025", "geometry"]].to_crs(4326)
    # The frozen proposal GPKG carries the original M0 satellite columns and
    # the ranking copy from the one-to-one join. GeoPandas therefore reads them
    # with _x/_y suffixes. They must agree exactly; use the ranking (_y) copy
    # for browser popups and rename it back to the canonical display names.
    for gname, gdf in [("merge_high", high), ("merge_standard", standard), ("merge_veto", veto)]:
        for basecol in ("satellite_merge_score", "satellite_score_percentile"):
            xcol, ycol = basecol + "_x", basecol + "_y"
            if xcol not in gdf.columns or ycol not in gdf.columns:
                raise RuntimeError(f"{gname} missing expected frozen duplicate columns for {basecol}: {list(gdf.columns)}")
            a = gdf[xcol].astype(float)
            b = gdf[ycol].astype(float)
            both = a.notna() & b.notna()
            if both.any() and not ((a[both] - b[both]).abs() <= 1e-12).all():
                raise RuntimeError(f"{gname} frozen duplicate columns disagree for {basecol}")

    def popup_view(gdf):
        cols = [
            "pair_key", "field_a", "field_b",
            "satellite_merge_score_y", "satellite_score_percentile_y",
            "p_samecrop", "hprior_percentile", "geometry",
        ]
        x = gdf[cols].copy()
        x = x.rename(columns={
            "satellite_merge_score_y": "satellite_merge_score",
            "satellite_score_percentile_y": "satellite_score_percentile",
        })
        return x.to_crs(4326)

    highw = popup_view(high)
    stdw = popup_view(standard)
    vetow = popup_view(veto)

    write_text(data / "split_proposals.js", "window.AKERPULS_SPLIT_PROPOSALS=" + geojson(splitw) + ";\n")
    write_text(data / "split_no_geometry.js", "window.AKERPULS_SPLIT_NO_GEOMETRY=" + geojson(nogw) + ";\n")
    write_text(data / "merge_high.js", "window.AKERPULS_MERGE_HIGH=" + geojson(highw) + ";\n")
    write_text(data / "merge_standard.js", "window.AKERPULS_MERGE_STANDARD=" + geojson(stdw) + ";\n")
    write_text(data / "merge_veto.js", "window.AKERPULS_MERGE_VETO=" + geojson(vetow) + ";\n")

    html = out / "index.html"
    write_text(html, make_html(chunks))

    qa = {
        "schema_version": "akerpuls-final-skane-review-map-v1-qa",
        "status": STATUS,
        "official_2025_fields": EXPECTED_FIELDS,
        "split_proposals": EXPECTED_SPLIT,
        "split_no_geometry": EXPECTED_SPLIT_NOGEOM,
        "merge_proposals_total": EXPECTED_MERGE,
        "merge_high_confidence_proposals": EXPECTED_MERGE_HIGH,
        "merge_standard_proposals": EXPECTED_MERGE_STANDARD,
        "merge_low_hprior_veto": EXPECTED_VETO,
        "canonical_geometry": "OFFICIAL_2025_GEOMETRY",
        "merge_v1_proposal_only": True,
        "automatic_boundary_removal": False,
        "cross_block_merge_allowed": False,
        "geometry_mutated": False,
        "display_simplification_only_m": DISPLAY_SIMPLIFY_M,
        "exact_geometry_gpkg_sha256": EXPECTED_GPKG_SHA,
    }
    qap = out / "AKERPULS_FINAL_SKANE_REVIEW_MAP_V1_QA.json"
    write_json(qap, qa)

    outputs = [
        exact, html, qap,
        data / "split_proposals.js",
        data / "split_no_geometry.js",
        data / "merge_high.js",
        data / "merge_standard.js",
        data / "merge_veto.js",
    ] + [data / x for x in chunks]
    hashes = {
        p.relative_to(out).as_posix(): {"sha256": sha(p), "bytes": p.stat().st_size}
        for p in outputs
    }
    manifest = {
        "schema_version": "akerpuls-final-skane-review-map-v1",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "parent_policy_freeze_sha256": EXPECTED_POLICY_SHA,
        "parent_exact_gpkg_sha256": EXPECTED_GPKG_SHA,
        "counts": {
            "official_2025_fields": EXPECTED_FIELDS,
            "split_proposals": EXPECTED_SPLIT,
            "merge_proposals": EXPECTED_MERGE,
            "merge_high_confidence": EXPECTED_MERGE_HIGH,
            "merge_standard": EXPECTED_MERGE_STANDARD,
            "low_hprior_veto": EXPECTED_VETO,
        },
        "display_contract": {
            "official_geometry_simplified_for_browser_only_m": DISPLAY_SIMPLIFY_M,
            "proposal_lines_exact": True,
            "exact_self_contained_gpkg_in_output": True,
            "default_visible": ["official_2025_fields", "split_proposals", "merge_high_confidence"],
            "merge_standard_toggle_default": False,
            "veto_toggle_default": False,
        },
        "policy_lock": {
            "canonical_geometry": "OFFICIAL_2025_GEOMETRY",
            "merge_v1_proposal_only": True,
            "automatic_boundary_removal": False,
            "cross_block_merge_allowed": False,
            "no_more_threshold_search_with_same_signals": True,
        },
        "output_hashes": hashes,
        "next": "HUMAN_REVIEW_FINAL_SKANE_SPLIT_AND_MERGE_PROPOSAL_MAP",
    }
    mp = out / "AKERPULS_FINAL_SKANE_REVIEW_MAP_V1_MANIFEST.json"
    write_json(mp, manifest)

    print("AKERPULS FINAL SKANE REVIEW MAP V1")
    print(f"STATUS={STATUS}")
    print(f"PARENT_POLICY_FREEZE_SHA256={EXPECTED_POLICY_SHA}")
    print(f"OFFICIAL_2025_FIELDS={EXPECTED_FIELDS}")
    print(f"SPLIT_PROPOSALS={EXPECTED_SPLIT}")
    print(f"MERGE_PROPOSALS={EXPECTED_MERGE}")
    print(f"MERGE_HIGH_CONFIDENCE={EXPECTED_MERGE_HIGH}")
    print(f"MERGE_STANDARD={EXPECTED_MERGE_STANDARD}")
    print(f"LOW_HPRIOR_VETO={EXPECTED_VETO}")
    print("CANONICAL_GEOMETRY=OFFICIAL_2025_GEOMETRY")
    print("MERGE_V1_PROPOSAL_ONLY=TRUE AUTOMATIC_BOUNDARY_REMOVAL=FALSE")
    print("CROSS_BLOCK_MERGE_ALLOWED=FALSE GEOMETRY_MUTATED=FALSE")
    print(f"EXACT_GPKG_SHA256={sha(exact)}")
    print(f"HTML_SHA256={sha(html)}")
    print(f"MANIFEST_SHA256={sha(mp)}")
    print(f"OPEN_MAP={html}")
    print("NEXT=HUMAN_REVIEW_FINAL_SKANE_SPLIT_AND_MERGE_PROPOSAL_MAP")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
