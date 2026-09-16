#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate review-only P95 split-line proposals from frozen D2A/B2 evidence.

This post-freeze stage is geometry QA only. It selects exactly the 618 fields in
the frozen D2C P95 tier, verifies the completed human-audit freeze as lineage,
and reconstructs the original D2A/B2 K=2 pixel assignment with the exact D2A
all-owner-field rasterization and saved local normalization statistics.

For each P95 field it emits:
  * the two largest connected B2 child-evidence polygons (same conservative
    mask->geometry rule used by the frozen B2 QA code);
  * the raw 10 m shared pixel-edge interface between the two full K=2 labels;
  * the longest contiguous part of that raw interface as the primary review
    split-line proposal.

No smoothing, threshold tuning, fusion/model refit, merge, crop inference or
replacement of official 2025 geometry occurs. Human audit labels are NOT used
to select or shape proposals.
"""
from __future__ import annotations

import argparse
import gc
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
DEFAULT_D2C = Path(r"C:\AkerSyncRepo\work\akerpuls_d2c_full_skane_freeze_review_v1")
DEFAULT_D2A = Path(r"C:\AkerSyncRepo\work\akerpuls_d2a_full_skane_split_discovery_v1")
D2A_CFG = ROOT / "config" / "akerpuls_d2a_full_skane_split_discovery_v1.json"
D2A_SCRIPT = ROOT / "src" / "154_akerpuls_d2a_full_skane_split_discovery_v1.py"

EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
EXPECTED_D2C_STATUS = "FROZEN_FULL_SKANE_QA_RANKING_V1"
EXPECTED_D2C_FREEZE_SHA256 = "60b021a5eef2483b54ea8d369ebbc7752c164ac51b113eb7faa524c9552be950"
EXPECTED_AUDIT_FREEZE_SHA256 = "5b5bc1d5c427d8a1c8fb54d03643cbb975cc4064c57d9086f69104b1864f9be4"
EXPECTED_AUDIT_STATUS = "FROZEN_D2C_HUMAN_AUDIT_V1"
EXPECTED_D2A_STATUS = "PASS_TO_D2A_REVIEW_STOP"
EXPECTED_P95 = 618
EXPECTED_EPSG = 32633
P95_GPKG = "d2c_review_p95_2025_geometry.gpkg"
AUDIT_FREEZE_REL = Path("d2c_visual_audit_freeze_v1") / "D2C_HUMAN_AUDIT_FREEZE_V1.json"
OUTPUT_DIRNAME = "d2c_p95_split_line_review_v1"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def repo_path(v: str) -> Path:
    p = Path(v)
    return p if p.is_absolute() else ROOT / p


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def write_gpkg(gdf, path: Path, layer: str) -> None:
    tmp = path.with_name(path.stem + ".partial.gpkg")
    if tmp.exists():
        tmp.unlink()
    gdf.to_file(tmp, layer=layer, driver="GPKG", index=False)
    tmp.replace(path)


def line_parts(geom) -> list[Any]:
    from shapely.geometry import LineString, MultiLineString
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom] if geom.length > 0 else []
    if isinstance(geom, MultiLineString):
        return [x for x in geom.geoms if x.length > 0]
    if hasattr(geom, "geoms"):
        out = []
        for x in geom.geoms:
            out.extend(line_parts(x))
        return out
    return []


def raw_and_primary_interface(g0, g1):
    """Return raw shared pixel-edge interface and longest merged contiguous part."""
    from shapely.ops import unary_union, linemerge
    shared = g0.boundary.intersection(g1.boundary)
    parts = line_parts(shared)
    if not parts:
        return None, None, 0, 0.0, 0.0
    raw = unary_union(parts)
    try:
        merged = linemerge(raw)
    except ValueError:
        merged = raw
    merged_parts = line_parts(merged)
    if not merged_parts:
        merged_parts = parts
    primary = max(merged_parts, key=lambda x: float(x.length))
    return raw, primary, len(merged_parts), float(raw.length), float(primary.length)


def metric_equal(got: float, frozen: Any, digits: int = 4) -> bool:
    try:
        fv = float(frozen)
    except Exception:
        return False
    return round(float(got), digits) == round(fv, digits)


def verify_lineage(d2c: Path, d2a_dir: Path) -> tuple[dict[str, Any], Path, pd.DataFrame, dict[str, Any]]:
    d2c_manifest_path = d2c / "d2c_manifest.json"
    d2c_freeze_path = d2c / "D2C_FULL_SKANE_QA_RANKING_FREEZE_V1.json"
    audit_freeze_path = d2c / AUDIT_FREEZE_REL
    p95_path = d2c / P95_GPKG
    for p in (d2c_manifest_path, d2c_freeze_path, audit_freeze_path, p95_path):
        if not p.is_file():
            raise FileNotFoundError(p)

    d2c_manifest = read_json(d2c_manifest_path)
    if d2c_manifest.get("status") != EXPECTED_D2C_STATUS:
        raise RuntimeError(f"D2C status changed: {d2c_manifest.get('status')}")
    if d2c_manifest.get("freeze_sha256") != EXPECTED_D2C_FREEZE_SHA256:
        raise RuntimeError("D2C manifest freeze SHA changed")
    if sha256_file(d2c_freeze_path) != EXPECTED_D2C_FREEZE_SHA256:
        raise RuntimeError("D2C freeze file SHA changed")
    if sha256_file(audit_freeze_path) != EXPECTED_AUDIT_FREEZE_SHA256:
        raise RuntimeError("Human audit freeze SHA changed")
    audit_freeze = read_json(audit_freeze_path)
    if audit_freeze.get("status") != EXPECTED_AUDIT_STATUS:
        raise RuntimeError(f"Human audit status changed: {audit_freeze.get('status')}")
    if audit_freeze.get("parent_d2c_freeze_sha256") != EXPECTED_D2C_FREEZE_SHA256:
        raise RuntimeError("Human audit freeze parent D2C binding changed")

    rec = d2c_manifest.get("output_hashes", {}).get(P95_GPKG)
    if not rec or sha256_file(p95_path) != rec.get("sha256"):
        raise RuntimeError("Frozen D2C P95 review GPKG hash changed")
    census = d2c_manifest.get("census", {})
    if int(census.get("p95", -1)) != EXPECTED_P95:
        raise RuntimeError(f"D2C P95 census changed: {census}")

    d2a_manifest_path = d2a_dir / "d2a_manifest.json"
    d2a_csv_path = d2a_dir / "d2a_field_split_discovery.csv"
    d2a_cells_path = d2a_dir / "d2a_cell_summary.csv"
    for p in (d2a_manifest_path, d2a_csv_path, d2a_cells_path):
        if not p.is_file():
            raise FileNotFoundError(p)
    d2a_manifest = read_json(d2a_manifest_path)
    if d2a_manifest.get("status") != EXPECTED_D2A_STATUS:
        raise RuntimeError(f"D2A status changed: {d2a_manifest.get('status')}")
    oh = d2a_manifest.get("output_hashes", {})
    if sha256_file(d2a_csv_path) != oh.get("field_split_discovery_sha256"):
        raise RuntimeError("D2A frozen field discovery CSV hash changed")
    if sha256_file(d2a_cells_path) != oh.get("cell_summary_sha256"):
        raise RuntimeError("D2A frozen cell summary CSV hash changed")

    d2a = pd.read_csv(d2a_csv_path, encoding="utf-8-sig", dtype={"parent_field_id_2025": str})
    if d2a.parent_field_id_2025.duplicated().any():
        raise RuntimeError("D2A field discovery contains duplicate IDs")
    return d2c_manifest, p95_path, d2a, d2a_manifest


def main() -> int:
    import geopandas as gpd
    import rasterio
    from scipy import ndimage as ndi
    from shapely.geometry import box

    ap = argparse.ArgumentParser()
    ap.add_argument("--d2c-dir", default=str(DEFAULT_D2C))
    ap.add_argument("--d2a-dir", default=str(DEFAULT_D2A))
    ap.add_argument("--output-dir")
    args = ap.parse_args()

    head = git_guard()
    d2c = Path(args.d2c_dir)
    d2a_dir = Path(args.d2a_dir)
    out = Path(args.output_dir) if args.output_dir else d2c / OUTPUT_DIRNAME

    print("P95_SPLIT_LINE_PROGRESS=VERIFY_FROZEN_LINEAGE", flush=True)
    _d2c_manifest, p95_path, d2a_frozen, _d2a_manifest = verify_lineage(d2c, d2a_dir)

    cfg = read_json(D2A_CFG)
    if cfg.get("schema_version") != "akerpuls-d2a-full-skane-split-discovery-v1":
        raise RuntimeError("Unexpected D2A config schema")
    d2a_mod = load_module(D2A_SCRIPT, "akerpuls_d2a_for_p95_geometry")
    d2a_mod.validate_config(cfg)

    inp = cfg["frozen_inputs"]
    b2cfg_path = repo_path(inp["b2_config"])
    b2script_path = repo_path(inp["b2_script"])
    b2cfg = read_json(b2cfg_path)
    b2 = load_module(b2script_path, "akerpuls_b2_for_p95_geometry")
    features = list(b2cfg["feature_bands_per_snapshot"])
    sp = b2cfg["split"]

    # Selection is exactly the frozen D2C P95 tier. Human audit labels are lineage only.
    p95 = gpd.read_file(p95_path)
    if len(p95) != EXPECTED_P95:
        raise RuntimeError(f"Expected {EXPECTED_P95} P95 fields, got {len(p95)}")
    required_p95 = {"parent_field_id_2025", "analysis_cell_id", "qa_tier", "fusion_score", "geometry"}
    missing = sorted(required_p95 - set(p95.columns))
    if missing:
        raise RuntimeError(f"P95 review GPKG missing columns: {missing}")
    p95["parent_field_id_2025"] = p95.parent_field_id_2025.astype(str)
    if p95.parent_field_id_2025.duplicated().any():
        raise RuntimeError("P95 review GPKG contains duplicate field IDs")
    if set(p95.qa_tier.astype(str)) != {"HIGH_PRIORITY_SPLIT_CANDIDATE"}:
        raise RuntimeError("P95 GPKG tier changed")

    fidx = d2a_frozen.set_index("parent_field_id_2025", drop=False)
    missing_d2a = sorted(set(p95.parent_field_id_2025) - set(fidx.index.astype(str)))
    if missing_d2a:
        raise RuntimeError(f"P95 fields missing from D2A frozen discovery: {len(missing_d2a)}")
    frozen_p95 = fidx.loc[p95.parent_field_id_2025.tolist()]
    if set(frozen_p95.discovery_type.astype(str)) != {"SPLIT_CANDIDATE"}:
        raise RuntimeError("P95 population is not entirely D2A SPLIT_CANDIDATE")

    part_path = Path(inp["field_partition"])
    cell_plan_path = Path(cfg["parent_d2_plan"]["cell_plan"])
    vrt_idx_path = Path(inp["d1s3j_vrt_output_index"])
    for p in (part_path, cell_plan_path, vrt_idx_path, b2cfg_path, b2script_path):
        if not p.is_file():
            raise FileNotFoundError(p)

    part = pd.read_csv(part_path, encoding="utf-8-sig", dtype={"parent_field_id_2025": str})
    cell_plan = pd.read_csv(cell_plan_path, encoding="utf-8-sig")
    if part.parent_field_id_2025.duplicated().any():
        raise RuntimeError("Frozen field partition contains duplicate IDs")

    local_paths = read_json(repo_path(inp["local_paths"]))
    geom_path = Path(local_paths[inp["geometry_local_paths_key"]])
    if sha256_file(geom_path) != inp["expected_geometry_sha256"]:
        raise RuntimeError("Frozen official 2025 geometry SHA changed")
    g0 = gpd.read_file(geom_path)
    if len(g0) != int(cfg["expected"]["fields"]) or g0.crs is None:
        raise RuntimeError("Frozen geometry count/CRS changed")
    gp = cfg["projection_geometry_policy"]
    if bool(gp["require_source_geometry_valid_before_reprojection"]):
        valid_source = g0.geometry.notna() & ~g0.geometry.is_empty & g0.geometry.is_valid
        if not bool(valid_source.all()):
            raise RuntimeError("Frozen source geometry contains invalid/null/empty rows")
    ids = d2a_mod.infer_ids(g0)
    if ids.duplicated().any():
        raise RuntimeError("Frozen field IDs are not unique")
    g_raw = g0.to_crs(EXPECTED_EPSG).copy().reset_index(drop=True)
    g_raw["parent_field_id_2025"] = ids.to_numpy()
    g = g_raw.copy()
    g, repair_info = d2a_mod.repair_projected_geometry(g, cfg)
    if set(g.parent_field_id_2025.astype(str)) != set(part.parent_field_id_2025.astype(str)):
        raise RuntimeError("Geometry field population differs from frozen partition")
    id_to_pos = {str(fid): i for i, fid in enumerate(g.parent_field_id_2025.astype(str))}

    vrt_idx = pd.read_csv(vrt_idx_path, encoding="utf-8-sig")
    rows = {str(r.snapshot): r for r in vrt_idx.itertuples(index=False)}
    snap_order = list(cfg["expected"]["snapshot_order"])
    if set(rows) != set(snap_order):
        raise RuntimeError(f"Frozen VRT snapshot set changed: {sorted(rows)}")
    datasets = [rasterio.open(str(rows[s].path)) for s in snap_order]
    band_maps = []
    try:
        for s, ds in zip(snap_order, datasets):
            if ds.crs is None or ds.crs.to_epsg() != EXPECTED_EPSG:
                raise RuntimeError(f"Unexpected VRT CRS for {s}: {ds.crs}")
            bm = {str(n): i + 1 for i, n in enumerate(ds.descriptions) if n}
            needed = set(features) | {"VALID"}
            if not needed.issubset(bm):
                raise RuntimeError(f"VRT {s} missing bands {sorted(needed - set(bm))}")
            band_maps.append(bm)

        if out.exists():
            raise RuntimeError(f"Output directory already exists; refusing to overwrite review package: {out}")

        active_cells = sorted(set(p95.analysis_cell_id.astype(str)))
        cp_index = cell_plan.set_index(cell_plan.analysis_cell_id.astype(str), drop=False)
        part_cells = part.analysis_cell_id.astype(str)
        raw_sidx = g_raw.sindex

        child_rows: list[dict[str, Any]] = []
        raw_line_rows: list[dict[str, Any]] = []
        primary_rows: list[dict[str, Any]] = []
        summary_rows: list[dict[str, Any]] = []
        exact_reproductions = 0

        print(f"P95_SPLIT_LINE_PROGRESS=RECONSTRUCT_D2A_B2_CELLS ACTIVE_CELLS={len(active_cells)}", flush=True)
        for ci, cid in enumerate(active_cells, 1):
            if cid not in cp_index.index:
                raise RuntimeError(f"P95 analysis cell missing from frozen D2 cell plan: {cid}")
            cp = cp_index.loc[cid]
            if isinstance(cp, pd.DataFrame):
                if len(cp) != 1:
                    raise RuntimeError(f"Duplicate cell-plan rows for {cid}")
                cp = cp.iloc[0]

            owner_ids = sorted(part.loc[part_cells.eq(cid), "parent_field_id_2025"].astype(str).tolist())
            if len(owner_ids) != int(cp.owner_fields):
                raise RuntimeError(f"Owner-field count mismatch {cid}: {len(owner_ids)} != {cp.owner_fields}")
            owner_pos = [id_to_pos[x] for x in owner_ids]
            owner_geoms = [g.geometry.iloc[p] for p in owner_pos]
            owner_label_by_id = {fid: i + 1 for i, fid in enumerate(owner_ids)}

            meta_path = d2a_dir / "cells" / cid / "d2a_split_discovery.meta.json"
            cell_csv = d2a_dir / "cells" / cid / "d2a_split_discovery.csv"
            if not meta_path.is_file() or not cell_csv.is_file():
                raise FileNotFoundError(f"Missing completed D2A cell artifact for {cid}")
            meta = read_json(meta_path)
            if sha256_file(cell_csv) != meta.get("csv_sha256"):
                raise RuntimeError(f"D2A cell CSV/meta hash mismatch for {cid}")
            if int(meta.get("owner_fields", -1)) != len(owner_ids):
                raise RuntimeError(f"D2A cell owner census changed for {cid}")
            center = np.asarray(meta.get("normalization_center"), dtype=float)
            scale = np.asarray(meta.get("normalization_scale"), dtype=float)
            expected_dims = len(features) * len(snap_order)
            if center.shape != (expected_dims,) or scale.shape != (expected_dims,) or not np.isfinite(center).all() or not np.isfinite(scale).all() or (scale <= 0).any():
                raise RuntimeError(f"Invalid frozen normalization stats for {cid}")

            wb = (float(cp.normalization_minx), float(cp.normalization_miny),
                  float(cp.normalization_maxx), float(cp.normalization_maxy))
            raw_norm_pos = list(raw_sidx.query(box(*wb), predicate="intersects"))
            if len(raw_norm_pos) != int(cp.resolved_normalization_fields):
                raise RuntimeError(f"Normalization population mismatch {cid}")

            cubes, valids, labels, tr = d2a_mod.read_owner_cell_arrays(
                datasets, band_maps, features, owner_geoms
            )
            all_valid = np.logical_and.reduce(valids)

            cell_targets = sorted(p95.loc[p95.analysis_cell_id.astype(str).eq(cid), "parent_field_id_2025"].astype(str).tolist())
            for fid in cell_targets:
                local_label = owner_label_by_id[fid]
                fm = labels == local_label
                interior = ndi.binary_erosion(
                    fm, structure=np.ones((3, 3), dtype=bool),
                    iterations=int(sp["interior_erosion_pixels"]), border_value=0
                )
                if int(interior.sum()) < int(sp["minimum_valid_pixels"]):
                    interior = fm.copy()
                m = interior & all_valid
                n = int(m.sum())
                if n < int(sp["minimum_valid_pixels"]):
                    raise RuntimeError(f"P95 {fid}: reconstructed valid pixels below frozen B2 minimum")

                raw = np.concatenate([cube[:, m].T for cube in cubes], axis=1).astype(np.float64, copy=False)
                x = (raw - center) / scale
                fit = b2.deterministic_k2(x)
                if fit is None:
                    raise RuntimeError(f"P95 {fid}: deterministic_k2 unexpectedly failed")
                lab, c, between, win = fit
                sep_ratio = float(between / max(win, 0.15))

                full_clusters = []
                comps = []
                comp_counts = []
                for k in (0, 1):
                    km = np.zeros_like(fm, dtype=bool)
                    km[m] = lab == k
                    full_clusters.append(km)
                    cm, count = b2.largest_component(km, ndi)
                    comps.append(cm)
                    comp_counts.append(int(count))

                coherence = float(sum(comp_counts) / max(1, n))
                fractions = [v / max(1, n) for v in comp_counts]
                minfrac = float(min(fractions))
                minpix = int(min(comp_counts))

                support = 0
                snap_ratios = []
                dims_per = len(features)
                for sidx in range(len(snap_order)):
                    sl = slice(sidx * dims_per, (sidx + 1) * dims_per)
                    d = b2.rms(c[0, sl] - c[1, sl])
                    xx = x[:, sl]
                    rr = np.sqrt(np.mean((xx - c[lab][:, sl]) ** 2, axis=1))
                    ww = float(np.sqrt(np.mean(rr ** 2)))
                    ratio = float(d / max(ww, 0.15))
                    snap_ratios.append(ratio)
                    support += int(ratio >= float(sp["snapshot_support_ratio"]))

                fr = fidx.loc[fid]
                checks = [
                    metric_equal(sep_ratio, fr.separation_ratio),
                    metric_equal(coherence, fr.spatial_coherence),
                    metric_equal(minfrac, fr.min_child_fraction),
                    int(minpix) == int(fr.min_child_pixels),
                    int(support) == int(fr.supporting_snapshots),
                    metric_equal(snap_ratios[0], fr.sep_april),
                    metric_equal(snap_ratios[1], fr.sep_may),
                    metric_equal(snap_ratios[2], fr.sep_june),
                    metric_equal(snap_ratios[3], fr.sep_july),
                ]
                if not all(checks):
                    raise RuntimeError(
                        f"P95 {fid}: reconstructed frozen D2A metrics mismatch "
                        f"sep={sep_ratio:.4f}/{fr.separation_ratio} coh={coherence:.4f}/{fr.spatial_coherence} "
                        f"minfrac={minfrac:.4f}/{fr.min_child_fraction} minpix={minpix}/{fr.min_child_pixels} "
                        f"support={support}/{fr.supporting_snapshots}"
                    )
                exact_reproductions += 1

                parent_geom = g.geometry.iloc[id_to_pos[fid]]
                for k, cm in enumerate(comps):
                    child = b2.mask_geom(cm, tr, parent_geom)
                    if child is None or child.is_empty:
                        raise RuntimeError(f"P95 {fid}: missing B2 conservative child evidence for cluster {k}")
                    child_rows.append({
                        "parent_field_id_2025": fid,
                        "proposal_child_id": f"{fid}::P95_REVIEW_C{k+1}",
                        "cluster": k + 1,
                        "cluster_pixels_largest_component": comp_counts[k],
                        "pixel_area_ha": comp_counts[k] * 0.01,
                        "geometry_role": "B2_LARGEST_COMPONENT_EVIDENCE_ONLY",
                        "geometry": child,
                    })

                full_geoms = [b2.mask_geom(km, tr, parent_geom) for km in full_clusters]
                if any(xg is None or xg.is_empty for xg in full_geoms):
                    raise RuntimeError(f"P95 {fid}: missing full K2 label geometry")
                raw_line, primary, nfrag, raw_len, primary_len = raw_and_primary_interface(full_geoms[0], full_geoms[1])
                status = "LINE_AVAILABLE" if primary is not None and primary_len > 0 else "NO_SHARED_INTERFACE"
                if raw_line is not None:
                    raw_line_rows.append({
                        "parent_field_id_2025": fid,
                        "proposal_status": status,
                        "interface_fragments": nfrag,
                        "raw_interface_length_m": raw_len,
                        "geometry_role": "RAW_10M_K2_SHARED_PIXEL_EDGE",
                        "geometry": raw_line,
                    })
                if primary is not None:
                    primary_rows.append({
                        "parent_field_id_2025": fid,
                        "proposal_status": status,
                        "primary_line_length_m": primary_len,
                        "raw_interface_length_m": raw_len,
                        "primary_fraction_of_raw": primary_len / raw_len if raw_len > 0 else 0.0,
                        "interface_fragments": nfrag,
                        "geometry_role": "LONGEST_CONTIGUOUS_RAW_INTERFACE_NO_SMOOTHING",
                        "geometry": primary,
                    })

                p95rec = p95.loc[p95.parent_field_id_2025.eq(fid)].iloc[0]
                summary_rows.append({
                    "parent_field_id_2025": fid,
                    "analysis_cell_id": cid,
                    "fusion_score": float(p95rec.fusion_score),
                    "proposal_status": status,
                    "reconstructed_d2a_exact": True,
                    "analysis_pixels": n,
                    "separation_ratio": round(sep_ratio, 4),
                    "spatial_coherence": round(coherence, 4),
                    "min_child_fraction": round(minfrac, 4),
                    "min_child_pixels": minpix,
                    "supporting_snapshots": support,
                    "interface_fragments": nfrag,
                    "raw_interface_length_m": raw_len,
                    "primary_line_length_m": primary_len,
                    "primary_fraction_of_raw": primary_len / raw_len if raw_len > 0 else 0.0,
                })

            del cubes, valids, labels
            gc.collect()
            if ci == 1 or ci % 5 == 0 or ci == len(active_cells):
                print(f"P95_SPLIT_LINE_CELL_PROGRESS={ci}/{len(active_cells)} RECONSTRUCTED={exact_reproductions}/{EXPECTED_P95}", flush=True)

        if exact_reproductions != EXPECTED_P95 or len(summary_rows) != EXPECTED_P95:
            raise RuntimeError(f"Exact D2A reconstruction census {exact_reproductions}/{len(summary_rows)} != {EXPECTED_P95}")
        if len(child_rows) != 2 * EXPECTED_P95:
            raise RuntimeError(f"Conservative child evidence census {len(child_rows)} != {2*EXPECTED_P95}")

        # Only create the review package after every P95 field has reproduced
        # the frozen D2A metrics exactly; failed reconstruction leaves no output.
        out.mkdir(parents=True, exist_ok=False)

        summary = pd.DataFrame(summary_rows).sort_values("parent_field_id_2025").reset_index(drop=True)
        summary_path = out / "p95_split_proposal_summary.csv"
        summary.to_csv(summary_path, index=False, encoding="utf-8-sig")

        children = gpd.GeoDataFrame(child_rows, geometry="geometry", crs=f"EPSG:{EXPECTED_EPSG}")
        children = children.sort_values(["parent_field_id_2025", "cluster"]).reset_index(drop=True)
        child_path = out / "p95_b2_child_evidence_review.gpkg"
        write_gpkg(children, child_path, "p95_child_evidence")

        raw_path = out / "p95_raw_k2_interface_review.gpkg"
        primary_path = out / "p95_primary_split_line_review.gpkg"
        if raw_line_rows:
            rawg = gpd.GeoDataFrame(raw_line_rows, geometry="geometry", crs=f"EPSG:{EXPECTED_EPSG}")
            rawg = rawg.sort_values("parent_field_id_2025").reset_index(drop=True)
            write_gpkg(rawg, raw_path, "p95_raw_interface")
        if primary_rows:
            primaryg = gpd.GeoDataFrame(primary_rows, geometry="geometry", crs=f"EPSG:{EXPECTED_EPSG}")
            primaryg = primaryg.sort_values("parent_field_id_2025").reset_index(drop=True)
            write_gpkg(primaryg, primary_path, "p95_primary_split_line")

        parent_cols = [c for c in [
            "parent_field_id_2025", "analysis_cell_id", "qa_tier", "fusion_score",
            "prototype_p_splitmerge_2026", "separation_ratio", "true_loo_min_child_dice", "geometry"
        ] if c in p95.columns]
        parents = p95[parent_cols].to_crs(EXPECTED_EPSG).copy()
        parent_path = out / "p95_official_2025_parents_review.gpkg"
        write_gpkg(parents, parent_path, "p95_official_2025_parents")

        output_paths = [summary_path, child_path, parent_path]
        if raw_path.is_file():
            output_paths.append(raw_path)
        if primary_path.is_file():
            output_paths.append(primary_path)
        output_hashes = {
            p.name: {"path": str(p), "sha256": sha256_file(p), "bytes": int(p.stat().st_size)}
            for p in output_paths
        }

        line_available = int((summary.proposal_status == "LINE_AVAILABLE").sum())
        no_interface = EXPECTED_P95 - line_available
        manifest = {
            "schema_version": "akerpuls-d2c-p95-split-line-review-v1",
            "status": "PASS_TO_P95_SPLIT_LINE_HUMAN_REVIEW",
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "git_head": head,
            "parent_d2c_freeze_sha256": EXPECTED_D2C_FREEZE_SHA256,
            "parent_human_audit_freeze_sha256": EXPECTED_AUDIT_FREEZE_SHA256,
            "source_p95_gpkg": str(p95_path),
            "source_p95_gpkg_sha256": sha256_file(p95_path),
            "p95_fields": EXPECTED_P95,
            "selection_rule": "EXACT_FROZEN_D2C_P95_TIER_ONLY_HUMAN_LABELS_NOT_USED",
            "d2a_reconstruction_exact_fields": exact_reproductions,
            "b2_child_evidence_features": len(child_rows),
            "line_available_fields": line_available,
            "no_shared_interface_fields": no_interface,
            "geometry_method": {
                "cluster_assignment": "EXACT_D2A_B2_DETERMINISTIC_K2_WITH_ALL_OWNER_FIELD_RASTERIZATION",
                "child_evidence": "FROZEN_B2_LARGEST_CONNECTED_COMPONENT_MASK_GEOM",
                "raw_interface": "SHARED_BOUNDARY_OF_FULL_K2_10M_PIXEL_LABEL_POLYGONS",
                "primary_line": "LONGEST_CONTIGUOUS_PART_OF_RAW_INTERFACE",
                "smoothing": False,
                "gap_filling": False,
            },
            "projection_geometry_repair_for_raster_ops": repair_info,
            "output_hashes": output_hashes,
            "network_calls": 0,
            "model_refit": False,
            "thresholds_tuned": False,
            "fusion_refit": False,
            "merge_executed": False,
            "human_audit_labels_used_for_selection_or_geometry": False,
            "official_2025_geometry_replaced": False,
            "automatic_geometry_mutation": False,
            "review_only": True,
            "next_step": "Visually review proposed P95 lines against the four frozen 2026 snapshots before any geometry adoption.",
        }
        manifest_path = out / "p95_split_line_review_manifest.json"
        write_json(manifest_path, manifest)

        print("AKERPULS D2C P95 REVIEW-ONLY SPLIT-LINE PROPOSALS")
        print("STATUS=PASS_TO_P95_SPLIT_LINE_HUMAN_REVIEW")
        print(f"PARENT_D2C_FREEZE_SHA256={EXPECTED_D2C_FREEZE_SHA256}")
        print(f"PARENT_HUMAN_AUDIT_FREEZE_SHA256={EXPECTED_AUDIT_FREEZE_SHA256}")
        print(f"P95_FIELDS={EXPECTED_P95} D2A_EXACT_RECONSTRUCTIONS={exact_reproductions}")
        print(f"B2_CHILD_EVIDENCE_FEATURES={len(child_rows)}")
        print(f"LINE_AVAILABLE_FIELDS={line_available} NO_SHARED_INTERFACE_FIELDS={no_interface}")
        print("SELECTION=EXACT_FROZEN_D2C_P95_TIER HUMAN_AUDIT_LABELS_USED=FALSE")
        print("PRIMARY_LINE=LONGEST_CONTIGUOUS_RAW_10M_K2_INTERFACE SMOOTHING=FALSE GAP_FILLING=FALSE")
        print("MODEL_REFIT=FALSE THRESHOLDS_TUNED=FALSE FUSION_REFIT=FALSE MERGE_EXECUTED=FALSE")
        print("OFFICIAL_2025_GEOMETRY_REPLACED=FALSE AUTOMATIC_GEOMETRY_MUTATION=FALSE REVIEW_ONLY=TRUE")
        print(f"OUTPUT={out}")
        return 0
    finally:
        for ds in datasets:
            ds.close()


if __name__ == "__main__":
    raise SystemExit(main())
