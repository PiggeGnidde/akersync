#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D2C freeze of full-Skåne QA ranking + review-only spatial products.

Local disk/CPU only. Consumes the completed D2B ranking, verifies its manifest
and hashes, freezes the exact ranking lineage, and joins unchanged official 2025
field polygons for review. No model execution, threshold tuning, split-line
construction, merge execution, or geometry replacement occurs in this stage.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_d2c_full_skane_freeze_review_v1.json"
THIS = Path(__file__).resolve()


def log(msg: str) -> None:
    print(msg, flush=True)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def stable_json_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_obj(obj: Any) -> str:
    return hashlib.sha256(stable_json_bytes(obj)).hexdigest()


def write_json(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def repo_path(v: str) -> Path:
    p = Path(v)
    return p if p.is_absolute() else ROOT / p


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def git_guard(cfg: dict[str, Any]) -> tuple[str, str]:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != cfg["feature_branch"]:
        raise RuntimeError(f"Expected branch {cfg['feature_branch']}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    return branch, head


def bool_series(x: pd.Series) -> pd.Series:
    if x.dtype == bool:
        return x
    return x.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def validate_config(cfg: dict[str, Any]) -> None:
    if cfg.get("schema_version") != "akerpuls-d2c-full-skane-freeze-review-v1":
        raise RuntimeError("Unexpected D2C config schema")
    auth = cfg["authorization"]
    if auth.get("status") != "AUTHORIZED_AFTER_D2B_REVIEW" or auth.get("user_command") != "GO D2C":
        raise RuntimeError("D2C lacks explicit post-D2B authorization")
    if any(bool(v) for v in cfg["guards"].values()):
        raise RuntimeError("D2C forbidden-scope guard unexpectedly enabled")
    g = cfg["geometry"]
    if not bool(g["review_geometry_only"]) or bool(g["split_line_generation"]) or bool(g["automatic_geometry_replacement"]):
        raise RuntimeError("D2C geometry scope changed")
    p = cfg["parent_d2b"]
    if [int(p[k]) for k in ("expected_candidates", "expected_true_loo_stable", "expected_fusion_ge_p90", "expected_fusion_ge_p95")] != [12676, 10250, 1136, 618]:
        raise RuntimeError("D2C frozen D2B census changed")
    if [int(p[k]) for k in ("expected_high_priority", "expected_split_candidate_tier", "expected_evidence_only")] != [618, 518, 11540]:
        raise RuntimeError("D2C frozen tier census changed")
    m = cfg["frozen_model"]
    if abs(float(m["development_p90"]) - 0.781017) > 1e-12 or abs(float(m["development_p95"]) - 0.843688) > 1e-12:
        raise RuntimeError("D2C frozen thresholds changed")
    a = cfg["review_product"]["audit_sample"]
    if int(a["total"]) != 100 or int(a["high_priority_p95"]) != 50 or int(a["p90_only"]) != 50:
        raise RuntimeError("D2C audit sample contract changed")


def normalized_review_attributes(df: pd.DataFrame) -> pd.DataFrame:
    required = [
        "parent_field_id_2025", "analysis_cell_id", "qa_tier", "fusion_score",
        "fusion_ge_dev_p90", "fusion_ge_dev_p95", "prototype_p_splitmerge_2026",
        "separation_ratio", "true_loo_min_child_dice", "true_loo_mean_child_dice",
        "true_loo_stable", "true_loo_refits_ok",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(f"D2C D2B ranking missing required columns: {missing}")
    out = pd.DataFrame()
    out["parent_field_id_2025"] = df["parent_field_id_2025"].astype(str)
    out["analysis_cell_id"] = df["analysis_cell_id"].astype(str)
    out["qa_tier"] = df["qa_tier"].astype(str)
    numeric = [
        "fusion_score", "prototype_p_splitmerge_2026", "separation_ratio",
        "true_loo_min_child_dice", "true_loo_mean_child_dice", "true_loo_refits_ok",
        "spatial_coherence", "min_child_fraction", "min_child_pixels",
        "supporting_snapshots", "all_valid_fraction", "confidence",
        "cdf_prototype_p_splitmerge_2026", "cdf_separation_ratio",
        "cdf_true_loo_min_child_dice",
    ]
    for c in numeric:
        if c in df.columns:
            out[c] = pd.to_numeric(df[c], errors="coerce")
    out["fusion_ge_dev_p90"] = bool_series(df["fusion_ge_dev_p90"]).astype("int8")
    out["fusion_ge_dev_p95"] = bool_series(df["fusion_ge_dev_p95"]).astype("int8")
    out["true_loo_stable"] = bool_series(df["true_loo_stable"]).astype("int8")
    if not np.isfinite(out[["fusion_score", "prototype_p_splitmerge_2026", "separation_ratio", "true_loo_min_child_dice", "true_loo_mean_child_dice"]].to_numpy(dtype=float)).all():
        raise RuntimeError("D2C review attributes contain non-finite frozen signals")
    return out


def audit_hash(seed: str, group: str, fid: str) -> str:
    return hashlib.sha256(f"{seed}|{group}|{fid}".encode("utf-8")).hexdigest()


def select_geography_then_hash(df: pd.DataFrame, mask: pd.Series, n: int, seed: str, group: str) -> pd.DataFrame:
    x = df.loc[mask].copy()
    if len(x) < n:
        raise RuntimeError(f"D2C audit stratum {group} has only {len(x)} rows; need {n}")
    x["audit_hash"] = [audit_hash(seed, group, fid) for fid in x.parent_field_id_2025.astype(str)]
    x = x.sort_values(["analysis_cell_id", "audit_hash", "parent_field_id_2025"]).reset_index(drop=True)
    first = x.groupby("analysis_cell_id", sort=True, as_index=False).head(1)
    if len(first) > n:
        chosen = first.sort_values(["audit_hash", "parent_field_id_2025"]).head(n).copy()
    else:
        chosen = first.copy()
        need = n - len(chosen)
        if need:
            rest = x[~x.parent_field_id_2025.isin(chosen.parent_field_id_2025)].sort_values(["audit_hash", "parent_field_id_2025"])
            chosen = pd.concat([chosen, rest.head(need)], ignore_index=True)
    chosen["audit_group"] = group
    return chosen.sort_values(["analysis_cell_id", "audit_hash", "parent_field_id_2025"]).reset_index(drop=True)


def add_review_points(gdf):
    projected = gdf.to_crs(32633)
    pts = projected.geometry.representative_point().to_crs(4326)
    out = gdf.copy()
    out["review_lon"] = pts.x.to_numpy()
    out["review_lat"] = pts.y.to_numpy()
    return out


def write_gpkg(gdf, path: Path, layer: str) -> None:
    tmp = path.with_name(path.stem + ".partial.gpkg")
    if tmp.exists():
        tmp.unlink()
    gdf.to_file(tmp, layer=layer, driver="GPKG", index=False)
    tmp.replace(path)


def write_geojson(gdf, path: Path) -> None:
    text = gdf.to_crs(4326).to_json(drop_id=True)
    write_text(path, text + "\n")


def build_html(p90plus_wgs84_json: str, cfg: dict[str, Any]) -> str:
    # Leaflet/OSM are only requested by the browser when the resulting review file is opened.
    # This Python execution itself contains no network path.
    data = p90plus_wgs84_json.replace("</", "<\\/")
    note = cfg["review_product"]["html_note"]
    return f"""<!doctype html>
<html lang=\"sv\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>ÅkerPuls D2C – P90+ review</title>
<link rel=\"stylesheet\" href=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.css\">
<style>html,body,#map{{height:100%;margin:0}} .info{{background:white;padding:8px 10px;font:13px/1.35 Arial,sans-serif;max-width:370px;box-shadow:0 1px 5px #777}} .legend i{{display:inline-block;width:16px;height:10px;margin-right:6px}}</style>
</head><body><div id=\"map\"></div><script src=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.js\"></script>
<script>
const DATA={data};
const map=L.map('map');
L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19,attribution:'&copy; OpenStreetMap contributors'}}).addTo(map);
function esc(v){{return String(v??'').replace(/[&<>\"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}}[c]));}}
function style(f){{const hi=f.properties.qa_tier==='HIGH_PRIORITY_SPLIT_CANDIDATE';return {{color:hi?'#b30000':'#d97706',weight:hi?3:2,fillOpacity:0.18}};}}
function popup(f){{const p=f.properties;return '<b>'+esc(p.qa_tier)+'</b><br>'+esc(p.parent_field_id_2025)+'<br>fusion='+Number(p.fusion_score).toFixed(4)+'<br>history='+Number(p.prototype_p_splitmerge_2026).toFixed(4)+'<br>separation='+Number(p.separation_ratio).toFixed(3)+'<br>TRUE-LOO min Dice='+Number(p.true_loo_min_child_dice).toFixed(3)+'<br>cell='+esc(p.analysis_cell_id);}}
const layer=L.geoJSON(DATA,{{style,onEachFeature:(f,l)=>l.bindPopup(popup(f))}}).addTo(map);
map.fitBounds(layer.getBounds(),{{padding:[10,10]}});
const info=L.control({{position:'topright'}}); info.onAdd=()=>{{const d=L.DomUtil.create('div','info');d.innerHTML='<b>ÅkerPuls D2C – P90+ QA review</b><br>P95/high priority: 618<br>P90-only: 518<br><br>{note}';return d;}};info.addTo(map);
const legend=L.control({{position:'bottomright'}});legend.onAdd=()=>{{const d=L.DomUtil.create('div','info legend');d.innerHTML='<i style=\"background:#b30000\"></i>P95 high priority<br><i style=\"background:#d97706\"></i>P90-only';return d;}};legend.addTo(map);
</script></body></html>"""


def verify_cached_freeze(out: Path, script_sha: str, parent_hashes: dict[str, str]) -> dict[str, Any] | None:
    mpath = out / "d2c_manifest.json"
    if not mpath.is_file():
        return None
    try:
        m = read_json(mpath)
    except Exception:
        return None
    if m.get("status") != "FROZEN_FULL_SKANE_QA_RANKING_V1" or m.get("script_sha256") != script_sha:
        return None
    if m.get("parent_d2b_hashes") != parent_hashes:
        return None
    for name, rec in m.get("output_hashes", {}).items():
        p = Path(rec["path"])
        if not p.is_file() or sha256_file(p) != rec["sha256"]:
            return None
    return m


def main() -> int:
    import geopandas as gpd

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CFG))
    ap.add_argument("--output-dir")
    args = ap.parse_args()
    cfg = read_json(Path(args.config))
    validate_config(cfg)
    branch, head = git_guard(cfg)
    out = Path(args.output_dir or cfg["output_dir"])
    out.mkdir(parents=True, exist_ok=True)
    script_sha = sha256_file(THIS)

    log("D2C_PROGRESS=VERIFY_D2B_PARENT_HASHES_AND_FROZEN_CENSUS")
    p = cfg["parent_d2b"]
    manifest_path = Path(p["manifest"])
    loo_path = Path(p["true_loo_candidates"])
    fusion_path = Path(p["fusion_candidates"])
    cell_path = Path(p["cell_summary"])
    for x in (manifest_path, loo_path, fusion_path, cell_path):
        if not x.is_file():
            raise FileNotFoundError(x)
    pm = read_json(manifest_path)
    if pm.get("status") != p["required_status"]:
        raise RuntimeError(f"D2C parent status changed: {pm.get('status')}")
    parent_hashes = {
        "manifest_sha256": sha256_file(manifest_path),
        "true_loo_candidates_sha256": sha256_file(loo_path),
        "fusion_candidates_sha256": sha256_file(fusion_path),
        "cell_summary_sha256": sha256_file(cell_path),
    }
    ph = pm.get("output_hashes", {})
    expected_parent_hashes = {
        "true_loo_candidates_sha256": ph.get("true_loo_candidates_sha256"),
        "fusion_candidates_sha256": ph.get("fusion_candidates_sha256"),
        "cell_summary_sha256": ph.get("cell_summary_sha256"),
    }
    if any(not v for v in expected_parent_hashes.values()):
        raise RuntimeError("D2C parent manifest lacks D2B output hashes")
    for k, v in expected_parent_hashes.items():
        if parent_hashes[k] != v:
            raise RuntimeError(f"D2C D2B parent hash mismatch for {k}")
    if bool(pm.get("thresholds_tuned")) or bool(pm.get("fusion_refit")) or bool(pm.get("merge_executed")) or bool(pm.get("automatic_geometry_replacement")):
        raise RuntimeError("D2C parent provenance unexpectedly permits post-freeze/model/geometry change")

    expected_counts = {
        "candidates": int(p["expected_candidates"]),
        "true_loo_stable": int(p["expected_true_loo_stable"]),
        "fusion_ge_p90": int(p["expected_fusion_ge_p90"]),
        "fusion_ge_p95": int(p["expected_fusion_ge_p95"]),
    }
    for key, val in expected_counts.items():
        if int(pm.get(key, -1)) != val:
            raise RuntimeError(f"D2C D2B manifest census changed for {key}: {pm.get(key)} != {val}")
    tiers = pm.get("qa_tier_counts", {})
    expected_tiers = {
        "HIGH_PRIORITY_SPLIT_CANDIDATE": int(p["expected_high_priority"]),
        "SPLIT_CANDIDATE": int(p["expected_split_candidate_tier"]),
        "EVIDENCE_ONLY": int(p["expected_evidence_only"]),
    }
    if {k: int(tiers.get(k, 0)) for k in expected_tiers} != expected_tiers:
        raise RuntimeError(f"D2C D2B tier census changed: {tiers}")

    cached = verify_cached_freeze(out, script_sha, parent_hashes)
    if cached is not None:
        log("D2C_CACHE_HIT=TRUE VERIFIED_EXISTING_FREEZE_AND_REVIEW_ARTIFACTS")
        log("AKERPULS D2C FULL-SKANE FREEZE + REVIEW PRODUCT")
        log("STATUS=FROZEN_FULL_SKANE_QA_RANKING_V1")
        log(f"CANDIDATES={cached['census']['candidates']} P90PLUS={cached['census']['p90plus']} P95={cached['census']['p95']} AUDIT_SAMPLE={cached['census']['audit_sample']}")
        log(f"D2C_FREEZE_SHA256={cached['freeze_sha256']}")
        log("MODEL_EXECUTED=FALSE THRESHOLDS_TUNED=FALSE FUSION_REFIT=FALSE GEOMETRY_MUTATED=FALSE")
        log(f"OUTPUT={out}")
        return 0

    model = cfg["frozen_model"]
    formal_path = repo_path(model["formal_fusion_config"])
    model_artifact = Path(model["fusion_artifact"])
    if sha256_file(model_artifact) != model["expected_fusion_artifact_sha256"]:
        raise RuntimeError("D2C frozen fusion artifact SHA changed")
    formal = read_json(formal_path)
    if formal.get("status") != "FROZEN_QA_RANKING_NOT_AUTOMATIC_GEOMETRY":
        raise RuntimeError("D2C formal fusion status changed")
    if formal["fusion"]["source_freeze_sha256"] != model["expected_fusion_artifact_sha256"]:
        raise RuntimeError("D2C formal fusion config/artifact binding changed")
    if abs(float(formal["fusion"]["development_p90"]) - float(model["development_p90"])) > 1e-12 or abs(float(formal["fusion"]["development_p95"]) - float(model["development_p95"])) > 1e-12:
        raise RuntimeError("D2C formal fusion thresholds changed")

    rank = pd.read_csv(fusion_path, encoding="utf-8-sig", dtype={"parent_field_id_2025": str, "analysis_cell_id": str})
    if len(rank) != int(p["expected_candidates"]) or rank.parent_field_id_2025.duplicated().any():
        raise RuntimeError("D2C ranking is not exactly 12,676 unique candidates")
    attrs = normalized_review_attributes(rank)
    p90 = float(model["development_p90"]); p95 = float(model["development_p95"])
    calc90 = attrs.fusion_score >= p90; calc95 = attrs.fusion_score >= p95
    if not np.array_equal(calc90.to_numpy(), attrs.fusion_ge_dev_p90.astype(bool).to_numpy()):
        raise RuntimeError("D2C P90 booleans differ from frozen threshold")
    if not np.array_equal(calc95.to_numpy(), attrs.fusion_ge_dev_p95.astype(bool).to_numpy()):
        raise RuntimeError("D2C P95 booleans differ from frozen threshold")
    tier_calc = np.where(calc95, "HIGH_PRIORITY_SPLIT_CANDIDATE", np.where(calc90, "SPLIT_CANDIDATE", "EVIDENCE_ONLY"))
    if not np.array_equal(tier_calc.astype(str), attrs.qa_tier.to_numpy(dtype=str)):
        raise RuntimeError("D2C QA tiers differ from frozen thresholds")
    if int(calc90.sum()) != int(p["expected_fusion_ge_p90"]) or int(calc95.sum()) != int(p["expected_fusion_ge_p95"]):
        raise RuntimeError("D2C P90/P95 census changed")

    log("D2C_PROGRESS=JOIN_UNCHANGED_OFFICIAL_2025_GEOMETRY")
    geom_cfg = cfg["geometry"]
    local_paths = read_json(repo_path(geom_cfg["local_paths"]))
    geom_path = Path(local_paths[geom_cfg["geometry_local_paths_key"]])
    if sha256_file(geom_path) != geom_cfg["expected_geometry_sha256"]:
        raise RuntimeError("D2C frozen official 2025 geometry SHA changed")
    g0 = gpd.read_file(geom_path)
    if g0.crs is None or g0.geometry.isna().any() or g0.geometry.is_empty.any() or (~g0.geometry.is_valid).any():
        raise RuntimeError("D2C source geometry invalid/null/empty")
    helper = load_module(repo_path(geom_cfg["id_helper_script"]), "d2c_id_helper")
    gids = helper.infer_ids(g0).astype(str)
    if gids.duplicated().any():
        raise RuntimeError("D2C frozen geometry field IDs are not unique")
    base = g0[["geometry"]].copy()
    base.insert(0, "parent_field_id_2025", gids.to_numpy())
    lookup = base.set_index("parent_field_id_2025", drop=False)
    missing_geom = set(attrs.parent_field_id_2025) - set(lookup.index.astype(str))
    if missing_geom:
        raise RuntimeError(f"D2C candidate geometry join missing {len(missing_geom)} fields")
    ranked = lookup.loc[attrs.parent_field_id_2025.tolist()].reset_index(drop=True)
    ranked = ranked.merge(attrs, on="parent_field_id_2025", how="left", validate="one_to_one")
    ranked = gpd.GeoDataFrame(ranked, geometry="geometry", crs=g0.crs)
    if len(ranked) != int(p["expected_candidates"]):
        raise RuntimeError("D2C candidate geometry join count changed")
    ranked = add_review_points(ranked)

    p90plus = ranked[ranked.fusion_ge_dev_p90.astype(bool)].copy().sort_values(["fusion_score", "parent_field_id_2025"], ascending=[False, True]).reset_index(drop=True)
    p95df = ranked[ranked.fusion_ge_dev_p95.astype(bool)].copy().sort_values(["fusion_score", "parent_field_id_2025"], ascending=[False, True]).reset_index(drop=True)
    if len(p90plus) != int(cfg["review_product"]["p90plus_rows"]) or len(p95df) != int(cfg["review_product"]["p95_rows"]):
        raise RuntimeError("D2C review subset census changed")

    log("D2C_PROGRESS=SELECT_DETERMINISTIC_100_FIELD_VISUAL_AUDIT_SAMPLE")
    audit_cfg = cfg["review_product"]["audit_sample"]
    a95 = select_geography_then_hash(attrs, attrs.fusion_ge_dev_p95.astype(bool), int(audit_cfg["high_priority_p95"]), audit_cfg["seed"], "P95_HIGH_PRIORITY")
    a90 = select_geography_then_hash(attrs, attrs.fusion_ge_dev_p90.astype(bool) & ~attrs.fusion_ge_dev_p95.astype(bool), int(audit_cfg["p90_only"]), audit_cfg["seed"], "P90_ONLY")
    audit_attrs = pd.concat([a95, a90], ignore_index=True)
    if len(audit_attrs) != int(audit_cfg["total"]) or audit_attrs.parent_field_id_2025.duplicated().any():
        raise RuntimeError("D2C deterministic audit sample is not exactly 100 unique fields")
    audit = ranked[ranked.parent_field_id_2025.isin(audit_attrs.parent_field_id_2025)].copy()
    audit = audit.merge(audit_attrs[["parent_field_id_2025", "audit_group", "audit_hash"]], on="parent_field_id_2025", how="left", validate="one_to_one")
    audit = gpd.GeoDataFrame(audit, geometry="geometry", crs=ranked.crs).sort_values(["audit_group", "analysis_cell_id", "audit_hash"]).reset_index(drop=True)

    log("D2C_PROGRESS=WRITE_FREEZE_AND_REVIEW_ARTIFACTS")
    ranked_gpkg = out / "d2c_ranked_candidates_2025_geometry.gpkg"
    p90_gpkg = out / "d2c_review_p90plus_2025_geometry.gpkg"
    p95_gpkg = out / "d2c_review_p95_2025_geometry.gpkg"
    audit_gpkg = out / "d2c_visual_audit_sample_100.gpkg"
    p90_geojson = out / "d2c_review_p90plus_wgs84.geojson"
    p95_geojson = out / "d2c_review_p95_wgs84.geojson"
    audit_geojson = out / "d2c_visual_audit_sample_100_wgs84.geojson"
    p90_csv = out / "d2c_review_p90plus.csv"
    p95_csv = out / "d2c_review_p95.csv"
    audit_csv = out / "d2c_visual_audit_sample_100.csv"
    html_path = out / "d2c_review_p90plus_map.html"

    write_gpkg(ranked, ranked_gpkg, "ranked_candidates")
    write_gpkg(p90plus, p90_gpkg, "p90plus")
    write_gpkg(p95df, p95_gpkg, "p95_high_priority")
    write_gpkg(audit, audit_gpkg, "audit_sample_100")
    write_geojson(p90plus, p90_geojson)
    write_geojson(p95df, p95_geojson)
    write_geojson(audit, audit_geojson)
    p90plus.drop(columns="geometry").to_csv(p90_csv, index=False, encoding="utf-8-sig")
    p95df.drop(columns="geometry").to_csv(p95_csv, index=False, encoding="utf-8-sig")
    audit.drop(columns="geometry").to_csv(audit_csv, index=False, encoding="utf-8-sig")
    html = build_html(p90_geojson.read_text(encoding="utf-8"), cfg)
    write_text(html_path, html)

    review_files = [ranked_gpkg, p90_gpkg, p95_gpkg, audit_gpkg, p90_geojson, p95_geojson, audit_geojson, p90_csv, p95_csv, audit_csv, html_path]
    review_hashes = {x.name: {"path": str(x), "sha256": sha256_file(x), "bytes": x.stat().st_size} for x in review_files}
    freeze = {
        "schema_version": "akerpuls-d2c-full-skane-qa-ranking-freeze-v1",
        "status": "FROZEN_FULL_SKANE_QA_RANKING_V1",
        "frozen_utc": datetime.now(timezone.utc).isoformat(),
        "authorization": cfg["authorization"],
        "parent_d2b_hashes": parent_hashes,
        "parent_d2b_census": {**expected_counts, "qa_tiers": expected_tiers},
        "model_freeze": {
            "fusion_artifact_sha256": model["expected_fusion_artifact_sha256"],
            "formal_fusion_config_sha256": sha256_file(formal_path),
            "development_p90": p90, "development_p95": p95,
            "signals": model["signals"], "weights": model["weights"],
        },
        "geometry": {
            "source_sha256": geom_cfg["expected_geometry_sha256"],
            "policy": "OFFICIAL_2025_GEOMETRY_REVIEW_ONLY_NO_SPLIT_LINE",
            "automatic_geometry_replacement": False,
        },
        "review_products": review_hashes,
        "audit_sample": {
            "rows": len(audit), "p95_high_priority": int((audit.audit_group == "P95_HIGH_PRIORITY").sum()),
            "p90_only": int((audit.audit_group == "P90_ONLY").sum()),
            "selection": audit_cfg["selection"], "seed": audit_cfg["seed"],
        },
        "thresholds_tuned": False, "fusion_refit": False, "model_executed": False,
        "split_line_generated": False, "merge_executed": False, "geometry_mutated": False,
    }
    freeze_path = out / "D2C_FULL_SKANE_QA_RANKING_FREEZE_V1.json"
    write_json(freeze_path, freeze)
    freeze_sha = sha256_file(freeze_path)

    note_path = out / "D2C_FREEZE_AND_REVIEW_NOTE.md"
    note = f"""# ÅkerPuls D2C – full-Skåne QA ranking freeze v1

Status: **FROZEN_FULL_SKANE_QA_RANKING_V1**

- D2B baseline candidates: {expected_counts['candidates']:,}
- TRUE-LOO stable: {expected_counts['true_loo_stable']:,}
- Frozen P90+ review candidates: {expected_counts['fusion_ge_p90']:,}
- Frozen P95/high-priority candidates: {expected_counts['fusion_ge_p95']:,}
- P90-only tier: {expected_tiers['SPLIT_CANDIDATE']:,}
- Evidence-only: {expected_tiers['EVIDENCE_ONLY']:,}
- Visual-audit sample: 100 fields (50 P95 + 50 P90-only), deterministic geography-coverage/hash selection.

Frozen thresholds remain P90={p90:.6f} and P95={p95:.6f}. No threshold tuning or fusion refit occurred.
All map polygons are unchanged official 2025 field geometry. D2C generated no proposed split line and authorizes no geometry replacement.

Freeze SHA256: `{freeze_sha}`
Parent D2B fusion CSV SHA256: `{parent_hashes['fusion_candidates_sha256']}`
Frozen model artifact SHA256: `{model['expected_fusion_artifact_sha256']}`

`d2c_review_p90plus_map.html` is a convenience review map. Opening it in a browser uses Leaflet/OpenStreetMap over the network; generation of the file itself was zero-network.
"""
    write_text(note_path, note)

    output_records = dict(review_hashes)
    output_records[freeze_path.name] = {"path": str(freeze_path), "sha256": freeze_sha, "bytes": freeze_path.stat().st_size}
    output_records[note_path.name] = {"path": str(note_path), "sha256": sha256_file(note_path), "bytes": note_path.stat().st_size}
    checks = {
        "parent_d2b_pass": pm.get("status") == p["required_status"],
        "parent_manifest_hashes_match_files": all(parent_hashes[k] == v for k, v in expected_parent_hashes.items()),
        "exact_parent_census": all(int(pm.get(k, -1)) == v for k, v in expected_counts.items()),
        "exact_qa_tier_partition": {k: int(tiers.get(k, 0)) for k in expected_tiers} == expected_tiers,
        "frozen_thresholds_exact": int(calc90.sum()) == 1136 and int(calc95.sum()) == 618,
        "candidate_geometry_join_exact": len(ranked) == 12676,
        "review_p90plus_exact": len(p90plus) == 1136 and len(p95df) == 618,
        "audit_sample_exact": len(audit) == 100 and int((audit.audit_group == "P95_HIGH_PRIORITY").sum()) == 50 and int((audit.audit_group == "P90_ONLY").sum()) == 50,
        "model_not_executed": True, "thresholds_not_tuned": True, "fusion_not_refit": True,
        "split_line_not_generated": True, "merge_not_executed": True, "geometry_not_mutated": True,
    }
    status = "FROZEN_FULL_SKANE_QA_RANKING_V1" if all(checks.values()) else "REVIEW"
    manifest = {
        "schema_version": "akerpuls-d2c-full-skane-freeze-review-result-v1",
        "status": status, "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git": {"branch": branch, "head": head}, "script_sha256": script_sha,
        "authorization": cfg["authorization"], "parent_d2b_hashes": parent_hashes,
        "freeze_sha256": freeze_sha,
        "census": {"candidates": len(ranked), "p90plus": len(p90plus), "p95": len(p95df), "audit_sample": len(audit)},
        "checks": checks, "output_hashes": output_records,
        "network_calls": 0, "process_api_calls": 0, "sentinel_hub_pu_used": 0,
        "model_executed": False, "thresholds_tuned": False, "fusion_refit": False,
        "split_line_generated": False, "merge_executed": False, "geometry_mutated": False,
        "next_step": "Review the frozen 100-field visual-audit sample and P90+/P95 map; proposed split-line generation remains a separate future authorization.",
        "interpretation": cfg["interpretation"],
    }
    write_json(out / "d2c_manifest.json", manifest)

    log("AKERPULS D2C FULL-SKANE FREEZE + REVIEW PRODUCT")
    log(f"STATUS={status}")
    log(f"CANDIDATES={len(ranked)} P90PLUS={len(p90plus)} P95={len(p95df)} EVIDENCE_ONLY={expected_tiers['EVIDENCE_ONLY']}")
    log(f"AUDIT_SAMPLE={len(audit)} P95={int((audit.audit_group == 'P95_HIGH_PRIORITY').sum())} P90_ONLY={int((audit.audit_group == 'P90_ONLY').sum())}")
    log(f"D2C_FREEZE_SHA256={freeze_sha}")
    log(f"PARENT_D2B_FUSION_SHA256={parent_hashes['fusion_candidates_sha256']}")
    log("CHECKS=" + ";".join(f"{k}:{str(v).upper()}" for k, v in checks.items()))
    log("NETWORK_CALLS=0")
    log("PROCESS_API_CALLS=0")
    log("SENTINEL_HUB_PU_USED=0")
    log("MODEL_EXECUTED=FALSE")
    log("THRESHOLDS_TUNED=FALSE")
    log("FUSION_REFIT=FALSE")
    log("SPLIT_LINE_GENERATED=FALSE")
    log("MERGE_EXECUTED=FALSE")
    log("GEOMETRY_MUTATED=FALSE")
    log(f"D2C_STATUS={status}")
    log(f"OUTPUT={out}")
    return 0 if status == "FROZEN_FULL_SKANE_QA_RANKING_V1" else 2


if __name__ == "__main__":
    raise SystemExit(main())
