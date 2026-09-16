#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the full-Skåne ÅkerPuls preliminary 2026 field-boundary map v1.

This is a downstream visualization/materialization stage from the formally frozen
ÅkerPuls preliminary geometry v1. It does NOT infer, refit or change geometry.
The preliminary 2026 boundary network is represented exactly as:

    official 2025 field boundaries + 613 frozen P95 primary split lines.

This is sufficient to display the implied 2026 field subdivision without
inventing child-polygon edge completions. The five frozen P95 fields with no
shared interface remain unchanged 2025 fields in the map.

Outputs:
  * GeoPackage with exact official 2025 polygons, exact frozen split lines and
    the five no-geometry P95 parents;
  * browser map using display-only simplified 2025 polygons plus exact split
    lines (Leaflet/OSM via CDN/network);
  * QA + manifest with hashes and the implied 129,249 preliminary field units.

Official 2025 geometry remains canonical. No smoothing, gap filling, merge,
automatic replacement or child polygon generation is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
DEFAULT_D2C = Path(r"C:\AkerSyncRepo\work\akerpuls_d2c_full_skane_freeze_review_v1")
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_preliminary_fields_2026_map_v1")
D2A_CFG = ROOT / "config" / "akerpuls_d2a_full_skane_split_discovery_v1.json"
D2A_SCRIPT = ROOT / "src" / "154_akerpuls_d2a_full_skane_split_discovery_v1.py"

EXPECTED_PRELIM_V1_FREEZE_SHA256 = "c2f4fd7ee03124f330d3a06a1d1465592399072ed5729a38e5a66ac27dcef376"
EXPECTED_PROPOSAL_FREEZE_SHA256 = "d3a06356fdd941b47c713535c1f00b388b09a4f23f61acf276528c8f5929e30a"
EXPECTED_OFFICIAL_GEOMETRY_SHA256 = "63f256c012a8f8aab75f22699bc729e60036913429caeb070306f57c19b31706"
EXPECTED_FIELDS_2025 = 128636
EXPECTED_P95 = 618
EXPECTED_SPLIT_LINES = 613
EXPECTED_NO_GEOMETRY = 5
EXPECTED_PRELIM_FIELD_UNITS_2026 = EXPECTED_FIELDS_2025 + EXPECTED_SPLIT_LINES
EXPECTED_EPSG = 32633
DISPLAY_SIMPLIFY_M = 5.0
DISPLAY_CHUNK_SIZE = 5000
STATUS = "PASS_TO_PRELIMINARY_2026_MAP_REVIEW"

PRELIM_FREEZE_REL = Path("akerpuls_preliminary_geometry_v1_freeze") / "AKERPULS_PRELIMINARY_GEOMETRY_V1_FREEZE.json"
PROPOSAL_FREEZE_REL = Path("d2c_p95_split_line_freeze_v1") / "P95_SPLIT_LINE_PROPOSAL_FREEZE_V1.json"
GPKG_NAME = "akerpuls_preliminary_fields_2026_map_v1.gpkg"
HTML_NAME = "index.html"
QA_NAME = "akerpuls_preliminary_fields_2026_map_v1_qa.json"
MANIFEST_NAME = "akerpuls_preliminary_fields_2026_map_v1_manifest.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_json(path: Path, obj: Any) -> None:
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def repo_path(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def verify_frozen_inputs(d2c: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Path]]:
    prelim_path = d2c / PRELIM_FREEZE_REL
    proposal_path = d2c / PROPOSAL_FREEZE_REL
    for p in (prelim_path, proposal_path):
        if not p.is_file():
            raise FileNotFoundError(p)
    if sha256_file(prelim_path) != EXPECTED_PRELIM_V1_FREEZE_SHA256:
        raise RuntimeError("ÅkerPuls preliminary geometry v1 freeze SHA changed")
    if sha256_file(proposal_path) != EXPECTED_PROPOSAL_FREEZE_SHA256:
        raise RuntimeError("P95 proposal freeze SHA changed")

    prelim = read_json(prelim_path)
    prop = read_json(proposal_path)
    if prelim.get("status") != "FROZEN_AKERPULS_PRELIMINARY_GEOMETRY_V1":
        raise RuntimeError("Unexpected preliminary geometry v1 freeze status")
    if prop.get("status") != "FROZEN_P95_SPLIT_LINE_PROPOSALS_V1":
        raise RuntimeError("Unexpected P95 proposal freeze status")
    if int(prop.get("p95_fields", -1)) != EXPECTED_P95:
        raise RuntimeError("P95 census changed")
    if int(prop.get("line_available_fields", -1)) != EXPECTED_SPLIT_LINES:
        raise RuntimeError("LINE_AVAILABLE census changed")
    if int(prop.get("no_shared_interface_fields", -1)) != EXPECTED_NO_GEOMETRY:
        raise RuntimeError("NO_SHARED_INTERFACE census changed")

    policy = prelim.get("policy", {})
    if policy.get("canonical_geometry") != "OFFICIAL_2025_GEOMETRY":
        raise RuntimeError("V1 canonical geometry policy changed")
    if policy.get("smoothing") is not False or policy.get("gap_filling") is not False:
        raise RuntimeError("V1 raw geometry policy changed")
    if policy.get("automatic_geometry_replacement") is not False:
        raise RuntimeError("V1 automatic replacement policy changed")

    hashes = prop.get("source_output_hashes", {})
    required = {
        "p95_split_proposal_summary.csv",
        "p95_primary_split_line_review.gpkg",
        "p95_official_2025_parents_review.gpkg",
        "p95_raw_k2_interface_review.gpkg",
        "p95_b2_child_evidence_review.gpkg",
    }
    if set(hashes) != required:
        raise RuntimeError(f"Proposal output set changed: {sorted(hashes)}")
    paths: dict[str, Path] = {}
    for name, rec in hashes.items():
        p = Path(rec["path"])
        if not p.is_file():
            raise FileNotFoundError(p)
        if sha256_file(p) != rec.get("sha256") or int(p.stat().st_size) != int(rec.get("bytes", -1)):
            raise RuntimeError(f"Frozen proposal artifact changed: {name}")
        paths[name] = p
    return prelim, prop, paths


def load_official_2025():
    import geopandas as gpd

    cfg = read_json(D2A_CFG)
    inp = cfg["frozen_inputs"]
    local_paths = read_json(repo_path(inp["local_paths"]))
    geom_path = Path(local_paths[inp["geometry_local_paths_key"]])
    if not geom_path.is_file():
        raise FileNotFoundError(geom_path)
    got = sha256_file(geom_path)
    if got != EXPECTED_OFFICIAL_GEOMETRY_SHA256 or got != inp["expected_geometry_sha256"]:
        raise RuntimeError(f"Official 2025 geometry SHA changed: {got}")
    g0 = gpd.read_file(geom_path)
    if len(g0) != EXPECTED_FIELDS_2025 or g0.crs is None:
        raise RuntimeError(f"Official 2025 geometry count/CRS changed: n={len(g0)} crs={g0.crs}")
    valid = g0.geometry.notna() & ~g0.geometry.is_empty & g0.geometry.is_valid
    if not bool(valid.all()):
        raise RuntimeError("Official 2025 geometry contains null/empty/invalid rows")
    d2a = load_module(D2A_SCRIPT, "akerpuls_d2a_for_2026_map")
    ids = d2a.infer_ids(g0).astype(str)
    if ids.duplicated().any():
        raise RuntimeError("Official 2025 field IDs are not unique")
    out = g0[[g0.geometry.name]].copy().to_crs(EXPECTED_EPSG).reset_index(drop=True)
    out["parent_field_id_2025"] = ids.to_numpy()
    return out[["parent_field_id_2025", "geometry"]]


def write_gpkg_layers(official, lines, nogeom, dest: Path) -> None:
    tmp = dest.with_name(dest.stem + ".partial.gpkg")
    if tmp.exists():
        tmp.unlink()
    official.to_file(tmp, layer="official_2025_fields", driver="GPKG", index=False)
    lines.to_file(tmp, layer="prelim_2026_split_lines", driver="GPKG", index=False, mode="a")
    nogeom.to_file(tmp, layer="p95_no_geometry_proposal", driver="GPKG", index=False, mode="a")
    tmp.replace(dest)


def json_for_geo(gdf) -> str:
    # GeoPandas emits valid GeoJSON and keeps only the minimal attributes selected by caller.
    return gdf.to_json(drop_id=True, ensure_ascii=False)


def make_html(chunk_files: list[str]) -> str:
    tags = "\n".join(f'<script src="data/{x}"></script>' for x in chunk_files)
    return f'''<!doctype html>
<html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ÅkerPuls – preliminära fält 2026, Skåne</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIINfQ3yn5Ro+zK2v1sZbKXUjMZ7K4Vq4g=" crossorigin="">
<style>html,body,#map{{height:100%;margin:0}}body{{font-family:Arial,sans-serif}}.info{{background:#fff;padding:10px 12px;border-radius:6px;box-shadow:0 1px 5px #777;max-width:360px;line-height:1.35}}.info b{{font-size:15px}}.legend i{{display:inline-block;width:22px;height:4px;margin-right:7px;vertical-align:middle}}.small{{font-size:12px;color:#444}}</style></head><body><div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<script>window.AKERPULS_FIELD_CHUNKS=[];</script>
{tags}
<script src="data/p95_split_lines.js"></script>
<script src="data/p95_no_geometry.js"></script>
<script>
const map=L.map('map',{{preferCanvas:true}}).setView([55.95,13.45],9);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19,attribution:'&copy; OpenStreetMap contributors'}}).addTo(map);
const canvas=L.canvas({{padding:0.4}});
const fields=L.layerGroup();
for(const fc of window.AKERPULS_FIELD_CHUNKS){{L.geoJSON(fc,{{renderer:canvas,style:{{color:'#6b7280',weight:0.55,opacity:0.75,fill:false,interactive:false}}}}).addTo(fields);}}
fields.addTo(map);
const splits=L.geoJSON(window.AKERPULS_SPLIT_LINES,{{renderer:canvas,style:{{color:'#00bcd4',weight:3,opacity:0.95}},onEachFeature:(f,l)=>l.bindPopup(`<b>Preliminär 2026 split</b><br>Parent 2025: ${{f.properties.parent_field_id_2025}}<br>Fusion score: ${{Number(f.properties.fusion_score).toFixed(3)}}<br><span class="small">Fryst P95 v1 · rå 10 m K2-linje</span>`)}}).addTo(map);
const nog=L.geoJSON(window.AKERPULS_NO_GEOMETRY,{{renderer:canvas,style:{{color:'#f59e0b',weight:3,fill:false,opacity:0.95}},onEachFeature:(f,l)=>l.bindPopup(`<b>P95 utan geometri-proposal</b><br>Parent 2025: ${{f.properties.parent_field_id_2025}}`)}});
L.control.layers(null,{{'2025 fältgränser (bas)':fields,'613 preliminära 2026 split-linjer':splits,'5 P95 utan geometri':nog}},{{collapsed:false}}).addTo(map);
const info=L.control({{position:'topleft'}});info.onAdd=()=>{{const d=L.DomUtil.create('div','info');d.innerHTML='<b>ÅkerPuls – preliminära fält 2026</b><br>Skåne · v1<br><br><b>128 636</b> officiella 2025 parent-fält<br><b>+ 613</b> frysta interna split-gränser<br><b>= 129 249</b> implicita preliminära 2026 fältenheter<br><br><span class="small">2025-geometrin är fortsatt canonical. Cyan = review-only P95 split proposal. Kartans grå 2025-geometri är förenklad 5 m endast för visning; GPKG innehåller exakt geometri.</span>';return d;}};info.addTo(map);
const leg=L.control({{position:'bottomright'}});leg.onAdd=()=>{{const d=L.DomUtil.create('div','info legend');d.innerHTML='<i style="background:#6b7280"></i>2025-gräns<br><i style="background:#00bcd4"></i>preliminär 2026 split<br><i style="background:#f59e0b"></i>P95 utan geometri';return d;}};leg.addTo(map);
</script></body></html>'''


def main() -> int:
    import geopandas as gpd

    ap = argparse.ArgumentParser()
    ap.add_argument("--d2c-dir", default=str(DEFAULT_D2C))
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    head = git_guard()
    d2c = Path(args.d2c_dir)
    out = Path(args.output_dir)

    print("PRELIM_2026_MAP_PROGRESS=VERIFY_FROZEN_V1_LINEAGE", flush=True)
    prelim, prop, src = verify_frozen_inputs(d2c)
    official = load_official_2025()
    idset = set(official.parent_field_id_2025.astype(str))

    summary = pd.read_csv(src["p95_split_proposal_summary.csv"], encoding="utf-8-sig", dtype={"parent_field_id_2025": str})
    if len(summary) != EXPECTED_P95 or summary.parent_field_id_2025.duplicated().any():
        raise RuntimeError("Frozen P95 summary is not 618 unique fields")
    status_counts = summary.proposal_status.astype(str).value_counts().to_dict()
    if status_counts != {"LINE_AVAILABLE": EXPECTED_SPLIT_LINES, "NO_SHARED_INTERFACE": EXPECTED_NO_GEOMETRY}:
        raise RuntimeError(f"Frozen P95 status census changed: {status_counts}")
    if not set(summary.parent_field_id_2025.astype(str)).issubset(idset):
        raise RuntimeError("P95 contains parent IDs absent from official 2025 geometry")

    lines = gpd.read_file(src["p95_primary_split_line_review.gpkg"]).to_crs(EXPECTED_EPSG)
    lines["parent_field_id_2025"] = lines.parent_field_id_2025.astype(str)
    if len(lines) != EXPECTED_SPLIT_LINES or lines.parent_field_id_2025.duplicated().any():
        raise RuntimeError("Frozen primary split-line layer is not 613 unique parents")
    expected_line_ids = set(summary.loc[summary.proposal_status.astype(str).eq("LINE_AVAILABLE"), "parent_field_id_2025"].astype(str))
    if set(lines.parent_field_id_2025) != expected_line_ids:
        raise RuntimeError("Split-line IDs differ from frozen LINE_AVAILABLE parents")
    lines = lines.merge(summary[["parent_field_id_2025", "fusion_score"]], on="parent_field_id_2025", how="left", validate="one_to_one")

    no_ids = set(summary.loc[summary.proposal_status.astype(str).eq("NO_SHARED_INTERFACE"), "parent_field_id_2025"].astype(str))
    nogeom = official.loc[official.parent_field_id_2025.isin(no_ids)].copy()
    if len(nogeom) != EXPECTED_NO_GEOMETRY:
        raise RuntimeError("Could not materialize exactly five no-geometry P95 parents")

    # Geometry QA: lines must lie within their official parent (0.5 m numerical tolerance).
    parent_idx = official.set_index("parent_field_id_2025")
    outside_lengths = []
    for r in lines.itertuples(index=False):
        parent = parent_idx.loc[str(r.parent_field_id_2025)].geometry
        outside_lengths.append(float(r.geometry.difference(parent.buffer(0.5)).length))
    max_outside = max(outside_lengths) if outside_lengths else 0.0
    if max_outside > 1e-6:
        raise RuntimeError(f"Frozen split line escapes official parent after 0.5 m tolerance: max outside={max_outside}")

    print("PRELIM_2026_MAP_PROGRESS=WRITE_EXACT_GPKG", flush=True)
    if out.exists():
        shutil.rmtree(out)
    (out / "data").mkdir(parents=True, exist_ok=True)
    gpkg = out / GPKG_NAME
    write_gpkg_layers(official, lines[["parent_field_id_2025", "fusion_score", "geometry"]], nogeom, gpkg)

    print("PRELIM_2026_MAP_PROGRESS=BUILD_BROWSER_DISPLAY_CHUNKS", flush=True)
    display = official.copy()
    display["geometry"] = display.geometry.simplify(DISPLAY_SIMPLIFY_M, preserve_topology=True)
    display = display.to_crs(4326)
    chunk_files: list[str] = []
    for chunk_no, start in enumerate(range(0, len(display), DISPLAY_CHUNK_SIZE), 1):
        part = display.iloc[start:start + DISPLAY_CHUNK_SIZE][["parent_field_id_2025", "geometry"]].copy()
        fc = json_for_geo(part)
        name = f"fields_{chunk_no:03d}.js"
        write_text(out / "data" / name, "window.AKERPULS_FIELD_CHUNKS.push(" + fc + ");\n")
        chunk_files.append(name)
        if chunk_no == 1 or chunk_no % 5 == 0 or start + DISPLAY_CHUNK_SIZE >= len(display):
            print(f"PRELIM_2026_MAP_CHUNKS={chunk_no} FIELDS_DONE={min(start + DISPLAY_CHUNK_SIZE, len(display))}/{len(display)}", flush=True)

    line_wgs = lines[["parent_field_id_2025", "fusion_score", "geometry"]].to_crs(4326)
    no_wgs = nogeom[["parent_field_id_2025", "geometry"]].to_crs(4326)
    write_text(out / "data" / "p95_split_lines.js", "window.AKERPULS_SPLIT_LINES=" + json_for_geo(line_wgs) + ";\n")
    write_text(out / "data" / "p95_no_geometry.js", "window.AKERPULS_NO_GEOMETRY=" + json_for_geo(no_wgs) + ";\n")
    html = out / HTML_NAME
    write_text(html, make_html(chunk_files))

    qa = {
        "schema_version": "akerpuls-preliminary-fields-2026-map-v1-qa",
        "status": STATUS,
        "official_2025_fields": EXPECTED_FIELDS_2025,
        "frozen_p95_fields": EXPECTED_P95,
        "prelim_2026_split_lines": EXPECTED_SPLIT_LINES,
        "p95_no_geometry_proposal": EXPECTED_NO_GEOMETRY,
        "implied_preliminary_2026_field_units": EXPECTED_PRELIM_FIELD_UNITS_2026,
        "boundary_network_definition": "OFFICIAL_2025_FIELD_BOUNDARIES_PLUS_FROZEN_P95_PRIMARY_SPLIT_LINES",
        "max_split_line_length_outside_parent_after_0_5m_tolerance_m": max_outside,
        "child_polygons_materialized": False,
        "display_simplification_only_m": DISPLAY_SIMPLIFY_M,
        "exact_geometry_in_gpkg": True,
        "canonical_geometry": "OFFICIAL_2025_GEOMETRY",
        "proposal_only": True,
        "model_executed": False,
        "thresholds_tuned": False,
        "fusion_refit": False,
        "smoothing": False,
        "gap_filling": False,
        "merge_executed": False,
        "official_2025_geometry_replaced": False,
        "automatic_geometry_mutation": False,
    }
    qa_path = out / QA_NAME
    write_json(qa_path, qa)

    output_files = [gpkg, html, qa_path, out / "data" / "p95_split_lines.js", out / "data" / "p95_no_geometry.js"] + [out / "data" / x for x in chunk_files]
    hashes = {p.relative_to(out).as_posix(): {"sha256": sha256_file(p), "bytes": int(p.stat().st_size)} for p in output_files}
    manifest = {
        "schema_version": "akerpuls-preliminary-fields-2026-map-v1-manifest",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "parent_preliminary_geometry_v1_freeze_sha256": EXPECTED_PRELIM_V1_FREEZE_SHA256,
        "parent_p95_proposal_freeze_sha256": EXPECTED_PROPOSAL_FREEZE_SHA256,
        "official_2025_geometry_sha256": EXPECTED_OFFICIAL_GEOMETRY_SHA256,
        "counts": {
            "official_2025_fields": EXPECTED_FIELDS_2025,
            "p95": EXPECTED_P95,
            "split_lines": EXPECTED_SPLIT_LINES,
            "no_geometry": EXPECTED_NO_GEOMETRY,
            "implied_preliminary_2026_field_units": EXPECTED_PRELIM_FIELD_UNITS_2026,
        },
        "map_contract": {
            "preliminary_2026_boundary_network": "official 2025 boundaries + exact frozen P95 primary split lines",
            "child_polygons_materialized": False,
            "display_official_geometry_simplified_m": DISPLAY_SIMPLIFY_M,
            "split_line_display_geometry_exact": True,
            "gpkg_geometry_exact": True,
            "browser_network_required_for_leaflet_and_osm": True,
        },
        "guards": {k: qa[k] for k in ["model_executed", "thresholds_tuned", "fusion_refit", "smoothing", "gap_filling", "merge_executed", "official_2025_geometry_replaced", "automatic_geometry_mutation"]},
        "output_hashes": hashes,
        "next_stop": "HUMAN_REVIEW_FULL_SKANE_PRELIMINARY_2026_FIELD_MAP",
    }
    write_json(out / MANIFEST_NAME, manifest)

    print("AKERPULS PRELIMINARY FIELDS 2026 MAP V1")
    print(f"STATUS={STATUS}")
    print(f"PARENT_PRELIMINARY_GEOMETRY_V1_FREEZE_SHA256={EXPECTED_PRELIM_V1_FREEZE_SHA256}")
    print(f"OFFICIAL_2025_FIELDS={EXPECTED_FIELDS_2025} SPLIT_LINES={EXPECTED_SPLIT_LINES} NO_GEOMETRY={EXPECTED_NO_GEOMETRY}")
    print(f"IMPLIED_PRELIMINARY_2026_FIELD_UNITS={EXPECTED_PRELIM_FIELD_UNITS_2026}")
    print("BOUNDARY_NETWORK=OFFICIAL_2025_BOUNDARIES_PLUS_FROZEN_P95_PRIMARY_SPLIT_LINES")
    print("CHILD_POLYGONS_MATERIALIZED=FALSE EXACT_GEOMETRY_IN_GPKG=TRUE DISPLAY_SIMPLIFICATION_M=5.0")
    print("CANONICAL_GEOMETRY=OFFICIAL_2025_GEOMETRY PROPOSAL_ONLY=TRUE")
    print("MODEL_EXECUTED=FALSE THRESHOLDS_TUNED=FALSE FUSION_REFIT=FALSE SMOOTHING=FALSE GAP_FILLING=FALSE MERGE_EXECUTED=FALSE")
    print("OFFICIAL_2025_GEOMETRY_REPLACED=FALSE AUTOMATIC_GEOMETRY_MUTATION=FALSE")
    print(f"OPEN_MAP={html}")
    print(f"GPKG={gpkg}")
    print("NEXT=HUMAN_REVIEW_FULL_SKANE_PRELIMINARY_2026_FIELD_MAP")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
