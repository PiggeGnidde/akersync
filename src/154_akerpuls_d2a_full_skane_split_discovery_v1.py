#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D2A full-Skane frozen B2 baseline split discovery.

Local disk/CPU only. No STAC, S3, Sentinel Hub Process, TRUE-LOO, history-prior
fusion, merge execution, threshold tuning or geometry mutation.

The 128,636 frozen 2025 fields are processed cell-wise using the exact D0b
normalization windows. Each cell gets robust B2 scaling from all valid pixels in
all 2025 fields intersecting its resolved window; only owner fields emit rows.
The stage is resumable per cell and must stop for review before D2B.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.util
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_d2a_full_skane_split_discovery_v1.json"
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


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def repo_path(v: str) -> Path:
    p = Path(v)
    return p if p.is_absolute() else ROOT / p


def git_guard(cfg: dict[str, Any]) -> tuple[str, str]:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != cfg["feature_branch"]:
        raise RuntimeError(f"Expected branch {cfg['feature_branch']}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    return branch, head


def infer_ids(g):
    cols = {c.lower(): c for c in g.columns}
    if "blockid" in cols and "skiftesbeteckning" in cols:
        return ("2025|" + g[cols["blockid"]].astype(str) + "|" + g[cols["skiftesbeteckning"]].astype(str)).astype(str)
    for key in ("current_field_id", "skiftesid", "skifte_id", "objectid", "id"):
        if key in cols:
            return g[cols[key]].astype(str)
    return pd.Series(["G2025_" + hashlib.sha256(geom.wkb).hexdigest()[:20] for geom in g.geometry], index=g.index, dtype=str)


def polygonal_make_valid(geom):
    from shapely.geometry import Polygon, MultiPolygon
    from shapely.ops import unary_union
    try:
        from shapely import make_valid
    except ImportError:  # pragma: no cover
        from shapely.validation import make_valid
    fixed = make_valid(geom)
    polys = []

    def collect(x):
        if x is None or x.is_empty:
            return
        if isinstance(x, Polygon):
            polys.append(x)
        elif isinstance(x, MultiPolygon):
            polys.extend(list(x.geoms))
        elif hasattr(x, "geoms"):
            for part in x.geoms:
                collect(part)

    collect(fixed)
    if not polys:
        raise RuntimeError("make_valid produced no polygonal area")
    out = polys[0] if len(polys) == 1 else unary_union(polys)
    if out.is_empty or not out.is_valid or out.geom_type not in {"Polygon", "MultiPolygon"}:
        raise RuntimeError(f"Projected geometry repair is not polygonally valid: {out.geom_type}")
    return out


def repair_projected_geometry(g, cfg: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    gp = cfg["projection_geometry_policy"]
    invalid = ~g.geometry.is_valid
    n = int(invalid.sum())
    max_abs = 0.0
    max_rel = 0.0
    if n:
        if not bool(gp["repair_invalid_projected_geometry_for_raster_operations_only"]):
            raise RuntimeError(f"Projected geometry has {n} invalid rows and repair is disabled")
        for i in np.flatnonzero(invalid.to_numpy()):
            old = g.geometry.iloc[int(i)]
            old_area = float(old.area)
            new = polygonal_make_valid(old)
            new_area = float(new.area)
            da = abs(new_area - old_area)
            dr = da / max(abs(old_area), 1e-12)
            max_abs = max(max_abs, da)
            max_rel = max(max_rel, dr)
            if da > float(gp["maximum_absolute_area_change_m2"]) and dr > float(gp["maximum_relative_area_change"]):
                raise RuntimeError(
                    f"Projected geometry repair exceeds frozen bounds at row {i}: abs_m2={da:.9g} rel={dr:.9g}"
                )
            g.at[g.index[int(i)], "geometry"] = new
    if (~g.geometry.is_valid).any() or g.geometry.isna().any() or g.geometry.is_empty.any():
        raise RuntimeError("Projected geometry remains invalid/null/empty after bounded in-memory repair")
    return g, {"projected_invalid_before_repair": n, "repaired_for_raster_ops": n,
               "max_abs_area_delta_m2": max_abs, "max_rel_area_delta": max_rel}


def validate_config(cfg: dict[str, Any]) -> None:
    if cfg.get("schema_version") != "akerpuls-d2a-full-skane-split-discovery-v1":
        raise RuntimeError("Unexpected D2A config schema")
    if any(bool(v) for v in cfg["guards"].values()):
        raise RuntimeError("D2A guard unexpectedly enables forbidden scope")
    e = cfg["execution"]
    if e["stage"] != "D2A_ONLY" or not bool(e["stop_after_d2a"]) or not bool(e["d2b_requires_separate_authorization"]):
        raise RuntimeError("D2A/D2B stage boundary changed")
    if bool(e["merge_discovery"]) or bool(e["true_loo"]) or bool(e["history_prior"]) or bool(e["fusion"]):
        raise RuntimeError("D2A scope unexpectedly includes later-stage computation")
    exp = cfg["expected"]
    if int(exp["fields"]) != 128636 or int(exp["analysis_cells"]) != 46 or int(exp["minimum_b2_valid_pixels"]) != 24:
        raise RuntimeError("Frozen D2A domain/B2 minimum changed")
    if list(exp["snapshot_order"]) != ["S2_2026_APRIL", "S2_2026_MAY", "S2_2026_JUNE", "S2_2026_JULY"]:
        raise RuntimeError("Frozen D2A snapshot order changed")


def aligned_window(ds, bounds):
    from rasterio.windows import Window, from_bounds
    raw = from_bounds(*bounds, transform=ds.transform)
    c0 = max(0, int(math.floor(raw.col_off)))
    r0 = max(0, int(math.floor(raw.row_off)))
    c1 = min(ds.width, int(math.ceil(raw.col_off + raw.width)))
    r1 = min(ds.height, int(math.ceil(raw.row_off + raw.height)))
    if c1 <= c0 or r1 <= r0:
        raise RuntimeError(f"Bounds outside raster domain: {bounds}")
    return Window(c0, r0, c1 - c0, r1 - r0)


def bounds_for_geometries(geoms) -> tuple[float, float, float, float]:
    b = np.asarray([x.bounds for x in geoms], dtype=float)
    if b.size == 0:
        raise RuntimeError("No geometries supplied for bounds")
    return float(b[:, 0].min()), float(b[:, 1].min()), float(b[:, 2].max()), float(b[:, 3].max())


def robust_scaling_for_cell(datasets, band_maps, features, norm_geoms, b2cfg):
    from rasterio.features import rasterize
    from rasterio.windows import transform as window_transform

    bounds = bounds_for_geometries(norm_geoms)
    win = aligned_window(datasets[0], bounds)
    tr = window_transform(win, datasets[0].transform)
    h, w = int(win.height), int(win.width)
    mask = rasterize([(geom, 1) for geom in norm_geoms], out_shape=(h, w), transform=tr,
                     fill=0, dtype="uint8", all_touched=False) > 0
    if not mask.any():
        raise RuntimeError("Normalization population rasterized to zero pixels")

    all_valid = mask.copy()
    for ds, bm in zip(datasets, band_maps):
        valid = ds.read(int(bm["VALID"]), window=win).astype(np.float32) > 0.5
        all_valid &= valid
    n = int(all_valid.sum())
    if n <= 0:
        raise RuntimeError("Normalization population has zero four-snapshot-valid field pixels")

    centers = []
    scales = []
    for ds, bm in zip(datasets, band_maps):
        for feat in features:
            arr = ds.read(int(bm[feat]), window=win).astype(np.float32)
            vals = arr[all_valid].astype(np.float64, copy=False)
            center = float(np.nanmedian(vals))
            mad = float(np.nanmedian(np.abs(vals - center)) * 1.4826)
            std = float(np.nanstd(vals))
            scale = mad if mad > 1e-6 else (std if std > 1e-6 else 1.0)
            if not np.isfinite(center) or not np.isfinite(scale) or scale <= 0:
                raise RuntimeError(f"Non-finite normalization statistic for {feat}")
            centers.append(center)
            scales.append(scale)
            del arr, vals
    return np.asarray(centers, dtype=float), np.asarray(scales, dtype=float), n, [float(x) for x in bounds]


def read_owner_cell_arrays(datasets, band_maps, features, owner_geoms):
    from rasterio.features import rasterize
    from rasterio.windows import transform as window_transform

    bounds = bounds_for_geometries(owner_geoms)
    win = aligned_window(datasets[0], bounds)
    tr = window_transform(win, datasets[0].transform)
    h, w = int(win.height), int(win.width)
    labels = rasterize([(geom, i + 1) for i, geom in enumerate(owner_geoms)], out_shape=(h, w),
                       transform=tr, fill=0, dtype="int32", all_touched=False)
    cubes = []
    valids = []
    for ds, bm in zip(datasets, band_maps):
        idx = [int(bm[f]) for f in features]
        cubes.append(ds.read(idx, window=win).astype(np.float32))
        valids.append(ds.read(int(bm["VALID"]), window=win).astype(np.float32) > 0.5)
    return cubes, valids, labels, tr


def classify_owner_fields(owner_ids, cubes, valids, labels, center, scale, b2, b2cfg):
    from scipy import ndimage as ndi

    features = list(b2cfg["feature_bands_per_snapshot"])
    dims_per = len(features)
    sp = b2cfg["split"]
    all_valid = np.logical_and.reduce(valids)
    rows = []

    for local_pos, fid in enumerate(owner_ids, 1):
        fm = labels == local_pos
        total = int(fm.sum())
        interior = ndi.binary_erosion(fm, structure=np.ones((3, 3), dtype=bool),
                                      iterations=int(sp["interior_erosion_pixels"]), border_value=0)
        if int(interior.sum()) < int(sp["minimum_valid_pixels"]):
            interior = fm.copy()
        m = interior & all_valid
        n = int(m.sum())
        valid_fraction = n / max(1, int(interior.sum()))
        if n < int(sp["minimum_valid_pixels"]):
            rows.append({
                "parent_field_id_2025": fid, "discovery_type": "UNCERTAIN", "confidence": 0.0,
                "reason": "TOO_FEW_ALL_VALID_INTERIOR_PIXELS", "pixels": total,
                "analysis_pixels": n, "all_valid_fraction": round(valid_fraction, 4),
            })
            continue

        raw_parts = [cube[:, m].T for cube in cubes]
        raw = np.concatenate(raw_parts, axis=1).astype(np.float64, copy=False)
        x = (raw - center) / scale
        fit = b2.deterministic_k2(x)
        if fit is None:
            rows.append({
                "parent_field_id_2025": fid, "discovery_type": "UNCHANGED", "confidence": 0.75,
                "reason": "NO_STABLE_K2", "pixels": total, "analysis_pixels": n,
                "all_valid_fraction": round(valid_fraction, 4),
            })
            continue

        lab, c, between, win = fit
        sep_ratio = float(between / max(win, 0.15))

        ys, xs = np.nonzero(fm)
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        sub_m = m[y0:y1, x0:x1]
        cluster_img = np.full(sub_m.shape, -1, dtype=np.int8)
        cluster_img[sub_m] = lab
        comp_counts = []
        for k in (0, 1):
            _cm, count = b2.largest_component(cluster_img == k, ndi)
            comp_counts.append(int(count))
        coherence = float(sum(comp_counts) / max(1, n))
        fractions = [v / max(1, n) for v in comp_counts]
        minfrac = float(min(fractions))
        minpix = int(min(comp_counts))

        support = 0
        snap_ratios = []
        for sidx in range(4):
            sl = slice(sidx * dims_per, (sidx + 1) * dims_per)
            d = b2.rms(c[0, sl] - c[1, sl])
            xx = x[:, sl]
            rr = np.sqrt(np.mean((xx - c[lab][:, sl]) ** 2, axis=1))
            ww = float(np.sqrt(np.mean(rr ** 2)))
            ratio = float(d / max(ww, 0.15))
            snap_ratios.append(ratio)
            support += int(ratio >= float(sp["snapshot_support_ratio"]))

        score = (0.30 * min(1.0, max(0.0, (sep_ratio - 1.0) / 1.5))
                 + 0.25 * (support / 4.0)
                 + 0.25 * min(1.0, coherence)
                 + 0.20 * min(1.0, minfrac / 0.30))
        is_split = (
            minpix >= int(sp["minimum_child_pixels"])
            and minfrac >= float(sp["minimum_child_fraction"])
            and coherence >= float(sp["minimum_spatial_coherence"])
            and sep_ratio >= float(sp["minimum_total_separation_ratio"])
            and support >= int(sp["minimum_supporting_snapshots"])
        )
        conf = float(np.clip(score if is_split else 0.55 + 0.35 * (1 - score), 0, 0.99))
        rows.append({
            "parent_field_id_2025": fid,
            "discovery_type": "SPLIT_CANDIDATE" if is_split else "UNCHANGED",
            "confidence": round(conf, 4), "reason": "K2_BASELINE",
            "pixels": total, "analysis_pixels": n, "all_valid_fraction": round(valid_fraction, 4),
            "separation_ratio": round(sep_ratio, 4), "spatial_coherence": round(coherence, 4),
            "min_child_fraction": round(minfrac, 4), "min_child_pixels": minpix,
            "supporting_snapshots": int(support),
            "sep_april": round(snap_ratios[0], 4), "sep_may": round(snap_ratios[1], 4),
            "sep_june": round(snap_ratios[2], 4), "sep_july": round(snap_ratios[3], 4),
        })
    return pd.DataFrame(rows)


def validate_cached_cell(csv_path: Path, meta_path: Path, expected_key: str, owner_ids: list[str]):
    if not csv_path.is_file() or not meta_path.is_file():
        return None
    try:
        meta = read_json(meta_path)
    except Exception:
        return None
    if meta.get("output_key_sha256") != expected_key:
        return None
    if sha256_file(csv_path) != meta.get("csv_sha256"):
        return None
    df = pd.read_csv(csv_path, dtype={"parent_field_id_2025": str})
    if len(df) != len(owner_ids) or set(df.parent_field_id_2025.astype(str)) != set(owner_ids):
        return None
    if df.parent_field_id_2025.duplicated().any():
        return None
    return df


def main() -> int:
    import geopandas as gpd
    import rasterio
    from shapely.geometry import box

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CFG))
    ap.add_argument("--output-dir")
    args = ap.parse_args()
    cfg = read_json(Path(args.config))
    validate_config(cfg)
    branch, head = git_guard(cfg)
    out = Path(args.output_dir or cfg["output_dir"])
    out.mkdir(parents=True, exist_ok=True)

    parent = cfg["parent_d2_plan"]
    pman_path = Path(parent["manifest"])
    contract_path = Path(parent["execution_contract"])
    cell_plan_path = Path(parent["cell_plan"])
    for p in (pman_path, contract_path, cell_plan_path):
        if not p.is_file():
            raise FileNotFoundError(p)
    pman = read_json(pman_path)
    contract = read_json(contract_path)
    contract_sha = sha256_file(contract_path)
    cell_plan_sha = sha256_file(cell_plan_path)
    if pman.get("status") != parent["required_status"]:
        raise RuntimeError(f"D2 plan status changed: {pman.get('status')}")
    if contract_sha != parent["expected_execution_contract_sha256"]:
        raise RuntimeError(f"D2 execution contract SHA changed: {contract_sha}")
    if cell_plan_sha != parent["expected_cell_plan_sha256"]:
        raise RuntimeError(f"D2 cell plan SHA changed: {cell_plan_sha}")
    if pman.get("d2_execution_contract_sha256") != contract_sha:
        raise RuntimeError("D2 plan manifest/contract SHA mismatch")
    sb = contract.get("stage_boundaries", {})
    if sb.get("d2a") != "B2_BASELINE_SPLIT_DISCOVERY_AND_UNCERTAIN_ONLY" or not bool(sb.get("mandatory_stop_after_d2a")) or not bool(sb.get("d2b_requires_separate_authorization")):
        raise RuntimeError("D2 stage-boundary contract changed")
    if bool(contract.get("automatic_split")) or bool(contract.get("automatic_merge")) or bool(contract.get("automatic_geometry_replacement")):
        raise RuntimeError("D2 contract unexpectedly enables automatic geometry mutation")

    inp = cfg["frozen_inputs"]
    partition_path = Path(inp["field_partition"])
    windows_path = Path(inp["resolved_normalization_windows"])
    fieldqa_path = Path(inp["d1s3k_field_validity"])
    vrt_idx_path = Path(inp["d1s3j_vrt_output_index"])
    b2cfg_path = repo_path(inp["b2_config"])
    b2script_path = repo_path(inp["b2_script"])
    for p in (partition_path, windows_path, fieldqa_path, vrt_idx_path, b2cfg_path, b2script_path):
        if not p.is_file():
            raise FileNotFoundError(p)
    frozen_hashes = contract["frozen_inputs"]
    checks_hash = {
        "field_partition": sha256_file(partition_path) == frozen_hashes["field_partition_sha256"],
        "resolved_windows": sha256_file(windows_path) == frozen_hashes["d0b_resolved_windows_sha256"],
        "field_validity": sha256_file(fieldqa_path) == frozen_hashes["d1s3k_field_validity_sha256"],
        "vrt_index": sha256_file(vrt_idx_path) == frozen_hashes["d1s3j_vrt_output_index_sha256"],
        "b2_config": sha256_file(b2cfg_path) == contract["frozen_model"]["b2_config_sha256"],
    }
    if not all(checks_hash.values()):
        raise RuntimeError(f"D2A frozen-input hash mismatch: {checks_hash}")

    cell_plan = pd.read_csv(cell_plan_path, encoding="utf-8-sig", dtype={"analysis_cell_id": str})
    part = pd.read_csv(partition_path, encoding="utf-8-sig", dtype={"parent_field_id_2025": str, "analysis_cell_id": str, "home_raster_tile_id": str})
    windows = pd.read_csv(windows_path, encoding="utf-8-sig", dtype={"analysis_cell_id": str})
    fieldqa = pd.read_csv(fieldqa_path, encoding="utf-8-sig", dtype={"parent_field_id_2025": str})
    vrt_idx = pd.read_csv(vrt_idx_path, encoding="utf-8-sig", dtype={"snapshot": str})
    exp = cfg["expected"]
    if len(cell_plan) != int(exp["analysis_cells"]) or len(windows) != int(exp["analysis_cells"]):
        raise RuntimeError("D2A analysis-cell population changed")
    if len(part) != int(exp["fields"]) or len(fieldqa) != int(exp["fields"]):
        raise RuntimeError("D2A field population changed")
    if int(fieldqa.pre_b2_ge24_all4_valid_pixels.astype(bool).sum()) != int(exp["pre_b2_ge24_all4_fields_from_d1s3k"]):
        raise RuntimeError("D1-S3k pre-B2 >=24 reference changed")
    if int((pd.to_numeric(fieldqa.field_pixels, errors="coerce") <= 0).sum()) != int(exp["zero_raster_pixel_fields_from_d1s3k"]):
        raise RuntimeError("D1-S3k zero-raster-field reference changed")

    local_paths_path = repo_path(inp["local_paths"])
    local_paths = read_json(local_paths_path)
    geom_path = Path(local_paths[inp["geometry_local_paths_key"]])
    if sha256_file(geom_path) != inp["expected_geometry_sha256"]:
        raise RuntimeError("Frozen geometry SHA changed")
    g0 = gpd.read_file(geom_path)
    if len(g0) != int(exp["fields"]) or g0.crs is None:
        raise RuntimeError("Frozen geometry count/CRS changed")
    if bool(cfg["projection_geometry_policy"]["require_source_geometry_valid_before_reprojection"]):
        valid_source = g0.geometry.notna() & ~g0.geometry.is_empty & g0.geometry.is_valid
        if not bool(valid_source.all()):
            raise RuntimeError("Frozen source geometry contains invalid/null/empty rows")
    ids = infer_ids(g0)
    if ids.duplicated().any():
        raise RuntimeError("Frozen field IDs are not unique")
    g_raw = g0.to_crs(int(exp["target_crs_epsg"])).copy().reset_index(drop=True)
    g_raw["parent_field_id_2025"] = ids.to_numpy()
    g = g_raw.copy()
    g, repair_info = repair_projected_geometry(g, cfg)
    if set(g.parent_field_id_2025.astype(str)) != set(part.parent_field_id_2025.astype(str)):
        raise RuntimeError("Geometry field population differs from D0 partition")
    log(f"D2A_GEOMETRY PROJECTED_INVALID_BEFORE_REPAIR={repair_info['projected_invalid_before_repair']} REPAIRED_FOR_RASTER_OPS={repair_info['repaired_for_raster_ops']} MAX_ABS_AREA_DELTA_M2={repair_info['max_abs_area_delta_m2']:.9g} MAX_REL_AREA_DELTA={repair_info['max_rel_area_delta']:.9g}")

    b2cfg = read_json(b2cfg_path)
    if int(b2cfg["split"]["minimum_valid_pixels"]) != int(exp["minimum_b2_valid_pixels"]):
        raise RuntimeError("Frozen B2 minimum-valid-pixels changed")
    b2 = load_module(b2script_path, "d2a_b2")
    features = list(b2cfg["feature_bands_per_snapshot"])
    snaps = list(exp["snapshot_order"])
    if list(getattr(b2, "SNAPS")) != snaps:
        raise RuntimeError("B2 snapshot order differs from D2A freeze")

    vrt_lookup = {str(r.snapshot): Path(str(r.path)) for r in vrt_idx.itertuples(index=False)}
    if set(vrt_lookup) != set(snaps):
        raise RuntimeError(f"VRT snapshot set changed: {sorted(vrt_lookup)}")
    datasets = [rasterio.open(vrt_lookup[s]) for s in snaps]
    try:
        base = datasets[0]
        for ds in datasets[1:]:
            if ds.crs != base.crs or ds.transform != base.transform or ds.width != base.width or ds.height != base.height:
                raise RuntimeError("Full-Skane snapshot VRT grids differ")
        band_maps = []
        for ds in datasets:
            bm = {name: i + 1 for i, name in enumerate(ds.descriptions) if name}
            missing = [x for x in features + ["VALID"] if x not in bm]
            if missing:
                raise RuntimeError(f"VRT missing frozen B2 bands: {missing}")
            band_maps.append(bm)

        id_to_pos = {str(fid): i for i, fid in enumerate(g.parent_field_id_2025.astype(str))}
        raw_sidx = g_raw.sindex
        script_sha = sha256_file(THIS)
        cell_outputs = []
        cell_summaries = []
        cache_hits = built = 0

        log("D2A_PROGRESS=RUN_46_CELLS_FROZEN_B2_DISCOVERY")
        for ci, cp in enumerate(cell_plan.sort_values("execution_order").itertuples(index=False), 1):
            cid = str(cp.analysis_cell_id)
            owner_ids = sorted(part.loc[part.analysis_cell_id.astype(str).eq(cid), "parent_field_id_2025"].astype(str).tolist())
            if len(owner_ids) != int(cp.owner_fields):
                raise RuntimeError(f"Owner-field count mismatch for {cid}")
            owner_pos = [id_to_pos[x] for x in owner_ids]
            owner_geoms = [g.geometry.iloc[p] for p in owner_pos]

            wb = (float(cp.normalization_minx), float(cp.normalization_miny), float(cp.normalization_maxx), float(cp.normalization_maxy))
            raw_norm_pos = list(raw_sidx.query(box(*wb), predicate="intersects"))
            if len(raw_norm_pos) != int(cp.resolved_normalization_fields):
                raise RuntimeError(f"Normalization population mismatch for {cid}: got {len(raw_norm_pos)} expected {cp.resolved_normalization_fields}")
            norm_geoms = [g.geometry.iloc[int(p)] for p in raw_norm_pos]

            cell_dir = out / "cells" / cid
            cell_dir.mkdir(parents=True, exist_ok=True)
            csv_path = cell_dir / "d2a_split_discovery.csv"
            meta_path = cell_dir / "d2a_split_discovery.meta.json"
            key_payload = {
                "schema": "akerpuls-d2a-cell-v1", "contract_sha256": contract_sha,
                "cell_plan_sha256": cell_plan_sha, "script_sha256": script_sha,
                "analysis_cell_id": cid, "owner_ids": owner_ids,
                "normalization_window": list(wb), "resolved_normalization_fields": int(cp.resolved_normalization_fields),
                "b2_config_sha256": sha256_file(b2cfg_path), "geometry_sha256": inp["expected_geometry_sha256"],
                "vrt_index_sha256": sha256_file(vrt_idx_path),
            }
            output_key = sha256_obj(key_payload)
            df = validate_cached_cell(csv_path, meta_path, output_key, owner_ids)
            if df is not None:
                cache_hits += 1
                meta = read_json(meta_path)
                norm_npix = int(meta["normalization_sample_pixels"])
                norm_nfields = int(meta["normalization_fields"])
            else:
                center, scale, norm_npix, norm_bounds = robust_scaling_for_cell(
                    datasets, band_maps, features, norm_geoms, b2cfg
                )
                cubes, valids, labels, _tr = read_owner_cell_arrays(
                    datasets, band_maps, features, owner_geoms
                )
                df = classify_owner_fields(owner_ids, cubes, valids, labels, center, scale, b2, b2cfg)
                if len(df) != len(owner_ids) or set(df.parent_field_id_2025.astype(str)) != set(owner_ids):
                    raise RuntimeError(f"D2A classification population mismatch for {cid}")
                df.insert(1, "analysis_cell_id", cid)
                tmp = csv_path.with_suffix(".csv.partial")
                df.to_csv(tmp, index=False, encoding="utf-8-sig")
                tmp.replace(csv_path)
                csha = sha256_file(csv_path)
                meta = {
                    "schema_version": "akerpuls-d2a-cell-result-v1",
                    "output_key_sha256": output_key,
                    "csv_sha256": csha,
                    "analysis_cell_id": cid,
                    "owner_fields": len(owner_ids),
                    "normalization_fields": len(raw_norm_pos),
                    "normalization_sample_pixels": int(norm_npix),
                    "normalization_full_field_bounds": norm_bounds,
                    "normalization_center": center.tolist(),
                    "normalization_scale": scale.tolist(),
                    "discovery_counts": {k: int(v) for k, v in df.discovery_type.value_counts().to_dict().items()},
                    "true_loo_executed": False, "history_prior_executed": False,
                    "fusion_executed": False, "merge_executed": False,
                    "automatic_geometry_replacement": False,
                    "completed_utc": datetime.now(timezone.utc).isoformat(),
                }
                mtmp = meta_path.with_suffix(".json.partial")
                mtmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                mtmp.replace(meta_path)
                built += 1
                del cubes, valids, labels, center, scale
                gc.collect()
                norm_nfields = len(raw_norm_pos)

            counts = df.discovery_type.value_counts().to_dict()
            cand = int(counts.get("SPLIT_CANDIDATE", 0))
            unc = int(counts.get("UNCERTAIN", 0))
            cell_outputs.append(df)
            cell_summaries.append({
                "execution_order": int(cp.execution_order), "analysis_cell_id": cid,
                "owner_fields": len(owner_ids), "normalization_fields": norm_nfields,
                "normalization_sample_pixels": int(norm_npix),
                "split_candidates": cand,
                "unchanged": int(counts.get("UNCHANGED", 0)),
                "uncertain": unc,
                "split_candidate_fraction": cand / len(owner_ids) if owner_ids else 0.0,
                "uncertain_fraction": unc / len(owner_ids) if owner_ids else 0.0,
                "cache_hit": df is not None and csv_path.is_file() and built + cache_hits >= ci and meta.get("output_key_sha256") == output_key and ci <= built + cache_hits,
                "cell_csv": str(csv_path), "cell_csv_sha256": sha256_file(csv_path),
            })
            if ci % 5 == 0 or ci == len(cell_plan):
                log(f"D2A_CELL_PROGRESS={ci}/{len(cell_plan)} BUILT={built} CACHE_HITS={cache_hits} LAST={cid} CAND={cand} UNCERTAIN={unc}")

        final = pd.concat(cell_outputs, ignore_index=True)
        final = final.sort_values("parent_field_id_2025").reset_index(drop=True)
        if len(final) != int(exp["fields"]) or final.parent_field_id_2025.duplicated().any():
            raise RuntimeError("D2A final owner-row population is not exactly 128,636 unique fields")
        if set(final.parent_field_id_2025.astype(str)) != set(part.parent_field_id_2025.astype(str)):
            raise RuntimeError("D2A final field IDs differ from frozen partition")
        allowed = {"SPLIT_CANDIDATE", "UNCHANGED", "UNCERTAIN"}
        if set(final.discovery_type.astype(str)) - allowed:
            raise RuntimeError("D2A emitted unexpected discovery type")
        cand_df = final[final.discovery_type.astype(str).eq("SPLIT_CANDIDATE")]
        metric_cols = ["separation_ratio", "spatial_coherence", "min_child_fraction", "min_child_pixels", "supporting_snapshots",
                       "sep_april", "sep_may", "sep_june", "sep_july"]
        candidate_metrics_finite = True
        if len(cand_df):
            candidate_metrics_finite = bool(np.isfinite(cand_df[metric_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)).all())

        final_path = out / "d2a_field_split_discovery.csv"
        final.to_csv(final_path, index=False, encoding="utf-8-sig")
        cells_df = pd.DataFrame(cell_summaries).sort_values("execution_order")
        cells_path = out / "d2a_cell_summary.csv"
        cells_df.to_csv(cells_path, index=False, encoding="utf-8-sig")

        counts = final.discovery_type.value_counts().to_dict()
        nsplit = int(counts.get("SPLIT_CANDIDATE", 0))
        nunch = int(counts.get("UNCHANGED", 0))
        nunc = int(counts.get("UNCERTAIN", 0))
        checks = {
            "parent_d2_plan_pass": pman.get("status") == parent["required_status"],
            "d2_contract_exact": contract_sha == parent["expected_execution_contract_sha256"],
            "cell_plan_exact": cell_plan_sha == parent["expected_cell_plan_sha256"],
            "all_46_cells_complete": len(cells_df) == int(exp["analysis_cells"]),
            "exact_128636_owner_rows": len(final) == int(exp["fields"]),
            "unique_owner_field_ids": not final.parent_field_id_2025.duplicated().any(),
            "discovery_partition_complete": nsplit + nunch + nunc == int(exp["fields"]),
            "normalization_population_exact": bool((cells_df.normalization_fields.astype(int).to_numpy() == cell_plan.sort_values("execution_order").resolved_normalization_fields.astype(int).to_numpy()).all()),
            "candidate_metrics_finite": candidate_metrics_finite,
            "frozen_input_hashes": all(checks_hash.values()),
            "true_loo_not_executed": True,
            "history_prior_not_executed": True,
            "fusion_not_executed": True,
            "merge_not_executed": True,
            "automatic_geometry_replacement_false": True,
        }
        status = "PASS_TO_D2A_REVIEW_STOP" if all(checks.values()) else "REVIEW"

        sep = pd.to_numeric(cand_df.separation_ratio, errors="coerce") if len(cand_df) else pd.Series(dtype=float)
        candidate_rate = nsplit / len(final)
        uncertain_rate = nunc / len(final)
        manifest = {
            "schema_version": "akerpuls-d2a-full-skane-split-discovery-result-v1",
            "status": status,
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "git": {"branch": branch, "head": head},
            "parent_d2_execution_contract_sha256": contract_sha,
            "parent_cell_plan_sha256": cell_plan_sha,
            "geometry_repair_for_raster_ops_only": repair_info,
            "fields": len(final), "analysis_cells": len(cells_df),
            "split_candidates": nsplit, "unchanged": nunch, "uncertain": nunc,
            "split_candidate_fraction": candidate_rate, "uncertain_fraction": uncertain_rate,
            "candidate_separation_ratio": {
                "p50": float(sep.quantile(.5)) if len(sep) else None,
                "p90": float(sep.quantile(.9)) if len(sep) else None,
                "p95": float(sep.quantile(.95)) if len(sep) else None,
                "max": float(sep.max()) if len(sep) else None,
            },
            "cell_candidate_fraction": {
                "p10": float(cells_df.split_candidate_fraction.quantile(.1)),
                "p50": float(cells_df.split_candidate_fraction.quantile(.5)),
                "p90": float(cells_df.split_candidate_fraction.quantile(.9)),
                "max": float(cells_df.split_candidate_fraction.max()),
                "max_cell": str(cells_df.loc[cells_df.split_candidate_fraction.idxmax(), "analysis_cell_id"]),
            },
            "cell_uncertain_fraction": {
                "p50": float(cells_df.uncertain_fraction.quantile(.5)),
                "p90": float(cells_df.uncertain_fraction.quantile(.9)),
                "max": float(cells_df.uncertain_fraction.max()),
                "max_cell": str(cells_df.loc[cells_df.uncertain_fraction.idxmax(), "analysis_cell_id"]),
            },
            "normalization_sample_pixels": {
                "min": int(cells_df.normalization_sample_pixels.min()),
                "p50": float(cells_df.normalization_sample_pixels.quantile(.5)),
                "max": int(cells_df.normalization_sample_pixels.max()),
            },
            "checks": checks,
            "output_hashes": {
                "field_split_discovery_sha256": sha256_file(final_path),
                "cell_summary_sha256": sha256_file(cells_path),
            },
            "network_calls": 0, "process_api_calls": 0, "sentinel_hub_pu_used": 0,
            "true_loo_executed": False, "history_prior_executed": False,
            "fusion_executed": False, "merge_executed": False,
            "automatic_geometry_replacement": False,
            "d2b_authorized": False,
            "interpretation": cfg["interpretation"],
        }
        (out / "d2a_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        log("AKERPULS D2A FULL-SKANE FROZEN B2 SPLIT DISCOVERY")
        log(f"STATUS={status}")
        log(f"FIELDS={len(final)} ANALYSIS_CELLS={len(cells_df)}")
        log(f"SPLIT_CANDIDATES={nsplit} FRACTION={candidate_rate:.6f}")
        log(f"UNCHANGED={nunch} FRACTION={nunch/len(final):.6f}")
        log(f"UNCERTAIN={nunc} FRACTION={uncertain_rate:.6f}")
        if len(sep):
            log(f"CANDIDATE_SEPARATION=P50:{sep.quantile(.5):.4f};P90:{sep.quantile(.9):.4f};P95:{sep.quantile(.95):.4f};MAX:{sep.max():.4f}")
        log(f"CELL_CANDIDATE_FRACTION=P10:{cells_df.split_candidate_fraction.quantile(.1):.6f};P50:{cells_df.split_candidate_fraction.quantile(.5):.6f};P90:{cells_df.split_candidate_fraction.quantile(.9):.6f};MAX:{cells_df.split_candidate_fraction.max():.6f}@{cells_df.loc[cells_df.split_candidate_fraction.idxmax(),'analysis_cell_id']}")
        log(f"CELL_UNCERTAIN_FRACTION=P50:{cells_df.uncertain_fraction.quantile(.5):.6f};P90:{cells_df.uncertain_fraction.quantile(.9):.6f};MAX:{cells_df.uncertain_fraction.max():.6f}@{cells_df.loc[cells_df.uncertain_fraction.idxmax(),'analysis_cell_id']}")
        log(f"NORMALIZATION_SAMPLE_PIXELS=MIN:{int(cells_df.normalization_sample_pixels.min())};P50:{cells_df.normalization_sample_pixels.quantile(.5):.0f};MAX:{int(cells_df.normalization_sample_pixels.max())}")
        log(f"CELL_CACHE=BUILT:{built};HITS:{cache_hits}")
        log("CHECKS=" + ";".join(f"{k}:{str(v).upper()}" for k, v in checks.items()))
        log("NETWORK_CALLS=0")
        log("PROCESS_API_CALLS=0")
        log("SENTINEL_HUB_PU_USED=0")
        log("TRUE_LOO_EXECUTED=FALSE")
        log("HISTORY_PRIOR_EXECUTED=FALSE")
        log("FUSION_EXECUTED=FALSE")
        log("MERGE_EXECUTED=FALSE")
        log("AUTOMATIC_GEOMETRY_REPLACEMENT=FALSE")
        log("D2B_AUTHORIZED=FALSE")
        log(f"D2A_STATUS={status}")
        log(f"OUTPUT={out}")
        return 0 if status == "PASS_TO_D2A_REVIEW_STOP" else 2
    finally:
        for ds in datasets:
            ds.close()


if __name__ == "__main__":
    raise SystemExit(main())
