#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerPuls merge M0: full-Skåne satellite-only merge discovery.

Scope:
  * candidate universe = touching 2025 skiften within the same 2025 block;
  * Sentinel-2 evidence only (Apr/May/Jun/Jul 2026);
  * exact frozen B2 merge metrics/thresholds from the earlier pilot;
  * frozen D2A local normalization scales;
  * NO ÅkerMinne/M4 prior, NO fusion, NO threshold tuning, NO geometry mutation.

This stage stops after producing a satellite-only ranking/census for review.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_merge_m0_satellite_only_v1.json"
D2A_SCRIPT = ROOT / "src" / "154_akerpuls_d2a_full_skane_split_discovery_v1.py"
DEFAULT_D2C = Path(r"C:\AkerSyncRepo\work\akerpuls_d2c_full_skane_freeze_review_v1")
PRELIM_FREEZE_REL = Path("akerpuls_preliminary_geometry_v1_freeze") / "AKERPULS_PRELIMINARY_GEOMETRY_V1_FREEZE.json"
EXPECTED_PRELIM_FREEZE_SHA256 = "c2f4fd7ee03124f330d3a06a1d1465592399072ed5729a38e5a66ac27dcef376"
EXPECTED_D2A_STATUS = "PASS_TO_D2A_REVIEW_STOP"
STATUS = "PASS_TO_M0_SATELLITE_MERGE_REVIEW_STOP"

CSV_NAME = "m0_satellite_merge_pairs.csv"
GPKG_NAME = "m0_satellite_merge_boundaries.gpkg"
SUMMARY_NAME = "M0_SATELLITE_ONLY_MERGE_SUMMARY_V1.json"
REPORT_NAME = "M0_SATELLITE_ONLY_MERGE_REPORT_V1.md"
MANIFEST_NAME = "m0_satellite_merge_manifest.json"


def log(msg: str) -> None:
    print(msg, flush=True)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_json(path: Path, obj: Any) -> None:
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def repo_path(v: str) -> Path:
    p = Path(v)
    return p if p.is_absolute() else ROOT / p


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def rms(v) -> float:
    a = np.asarray(v, dtype=float)
    return float(np.sqrt(np.mean(np.square(a)))) if a.size else 0.0


def git_guard(cfg: dict[str, Any]) -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != cfg["feature_branch"]:
        raise RuntimeError(f"Expected branch {cfg['feature_branch']}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def validate_config(cfg: dict[str, Any]) -> None:
    if cfg.get("schema_version") != "akerpuls-merge-m0-satellite-only-v1":
        raise RuntimeError("Unexpected M0 config schema")
    if cfg["features_per_snapshot"] != ["B02", "B03", "B04", "B08", "B11", "NDVI", "LSWI"]:
        raise RuntimeError("M0 feature contract changed")
    if cfg["expected"]["snapshot_order"] != ["S2_2026_APRIL", "S2_2026_MAY", "S2_2026_JUNE", "S2_2026_JULY"]:
        raise RuntimeError("M0 snapshot order changed")
    if int(cfg["expected"]["fields_2025"]) != 128636 or int(cfg["expected"]["blocks_2025"]) != 122970:
        raise RuntimeError("M0 Skåne population contract changed")
    if cfg["adjacency"]["scope"] != "SAME_2025_BLOCK_ONLY":
        raise RuntimeError("M0 adjacency scope changed")
    e = cfg["execution"]
    if not bool(e["satellite_only"]) or any(bool(e[k]) for k in (
        "history_prior", "m4_prior", "fusion", "threshold_tuning", "automatic_merge", "geometry_mutation"
    )):
        raise RuntimeError("M0 must remain satellite-only and non-mutating")
    if not bool(e["stop_after_m0"]):
        raise RuntimeError("M0 stop contract changed")
    mg = cfg["merge"]
    expected = {
        "boundary_dilation_pixels": 3,
        "minimum_strip_pixels_per_side": 4,
        "maximum_field_mean_distance": 0.60,
        "maximum_between_within_ratio": 1.00,
        "maximum_boundary_median_distance": 0.60,
        "strong_edge_distance": 0.90,
        "maximum_strong_edge_snapshots": 1,
        "minimum_valid_boundary_snapshots": 3,
        "minimum_confidence": 0.68,
    }
    for k, v in expected.items():
        if float(mg[k]) != float(v):
            raise RuntimeError(f"Frozen pilot merge parameter changed: {k}={mg[k]} expected={v}")


def merge_score_and_decision(
    mg: dict[str, Any],
    field_dist: float,
    between_within_ratio: float,
    boundary_distances: list[float | None],
) -> tuple[str, float, float | None, int, int]:
    vals = [float(x) for x in boundary_distances if x is not None and np.isfinite(x)]
    valid_snaps = len(vals)
    strong = sum(x >= float(mg["strong_edge_distance"]) for x in vals)
    bmed = float(np.median(vals)) if vals else None
    sim_field = math.exp(-float(field_dist))
    sim_boundary = math.exp(-bmed) if bmed is not None else 0.0
    stability = (valid_snaps / 4.0) * (1.0 - strong / 4.0)
    conf = 0.45 * sim_field + 0.40 * sim_boundary + 0.15 * stability
    assessable = (
        valid_snaps >= int(mg["minimum_valid_boundary_snapshots"])
        and bmed is not None
        and np.isfinite(field_dist)
        and np.isfinite(between_within_ratio)
    )
    if not assessable:
        return "UNCERTAIN", float(conf), bmed, valid_snaps, strong
    cand = (
        field_dist <= float(mg["maximum_field_mean_distance"])
        and between_within_ratio <= float(mg["maximum_between_within_ratio"])
        and bmed <= float(mg["maximum_boundary_median_distance"])
        and strong <= int(mg["maximum_strong_edge_snapshots"])
        and conf >= float(mg["minimum_confidence"])
    )
    return ("MERGE_CANDIDATE" if cand else "KEEP_BOUNDARY"), float(conf), bmed, valid_snaps, strong


def load_frozen_context(cfg: dict[str, Any], d2c: Path):
    import geopandas as gpd

    freeze_path = d2c / PRELIM_FREEZE_REL
    if not freeze_path.is_file():
        raise FileNotFoundError(freeze_path)
    if sha256_file(freeze_path) != EXPECTED_PRELIM_FREEZE_SHA256:
        raise RuntimeError("Parent preliminary geometry v1 freeze SHA changed")
    freeze = read_json(freeze_path)
    if freeze.get("status") != "FROZEN_AKERPULS_PRELIMINARY_GEOMETRY_V1":
        raise RuntimeError("Unexpected parent preliminary geometry v1 freeze status")

    d2cfg = read_json(repo_path(cfg["d2a_config"]))
    if d2cfg.get("schema_version") != "akerpuls-d2a-full-skane-split-discovery-v1":
        raise RuntimeError("Unexpected D2A config schema")
    inp = d2cfg["frozen_inputs"]
    vrt_index_path = Path(inp["d1s3j_vrt_output_index"])
    if not vrt_index_path.is_file():
        raise FileNotFoundError(vrt_index_path)
    if sha256_file(vrt_index_path) != cfg["expected_vrt_index_sha256"]:
        raise RuntimeError("Frozen D1 VRT output index SHA changed")

    local_paths = read_json(repo_path(inp["local_paths"]))
    geom_path = Path(local_paths[inp["geometry_local_paths_key"]])
    if not geom_path.is_file():
        raise FileNotFoundError(geom_path)
    if sha256_file(geom_path) != cfg["official_2025_geometry_sha256"]:
        raise RuntimeError("Official 2025 geometry SHA changed")

    d2a = load_module(D2A_SCRIPT, "akerpuls_d2a_for_merge_m0")
    g0 = gpd.read_file(geom_path)
    if len(g0) != int(cfg["expected"]["fields_2025"]) or g0.crs is None:
        raise RuntimeError(f"Official 2025 geometry count/CRS changed: n={len(g0)} crs={g0.crs}")
    cols = {c.lower(): c for c in g0.columns}
    if "blockid" not in cols or "skiftesbeteckning" not in cols:
        raise RuntimeError("Official 2025 skiften must contain blockid and skiftesbeteckning")
    field_ids = d2a.infer_ids(g0).astype(str)
    if field_ids.duplicated().any():
        raise RuntimeError("Official 2025 field IDs are not unique")
    blocks = g0[cols["blockid"]].astype(str)
    if int(blocks.nunique()) != int(cfg["expected"]["blocks_2025"]):
        raise RuntimeError(f"2025 block census changed: {blocks.nunique()}")

    valid_source = g0.geometry.notna() & ~g0.geometry.is_empty & g0.geometry.is_valid
    if not bool(valid_source.all()):
        raise RuntimeError("Official source geometry contains invalid/null/empty rows")
    g = g0.to_crs(int(cfg["expected"]["target_crs_epsg"])).copy().reset_index(drop=True)
    g["parent_field_id_2025"] = field_ids.to_numpy()
    g["block_id_2025"] = blocks.to_numpy()
    g, repair_info = d2a.repair_projected_geometry(g, d2cfg)

    part_path = Path(inp["field_partition"])
    part = pd.read_csv(part_path, encoding="utf-8-sig", dtype={"parent_field_id_2025": str, "analysis_cell_id": str})
    if len(part) != len(g) or part.parent_field_id_2025.duplicated().any():
        raise RuntimeError("Frozen D0 field partition census changed")
    required = {"parent_field_id_2025", "analysis_cell_id"}
    if not required.issubset(part.columns):
        raise RuntimeError(f"Frozen field partition missing columns {sorted(required - set(part.columns))}")
    cell_map = part.set_index("parent_field_id_2025")["analysis_cell_id"].astype(str)
    if set(g.parent_field_id_2025.astype(str)) != set(cell_map.index.astype(str)):
        raise RuntimeError("Official geometry population differs from frozen D0 field partition")
    g["analysis_cell_id"] = g.parent_field_id_2025.map(cell_map)
    if g.analysis_cell_id.isna().any():
        raise RuntimeError("Missing analysis-cell assignment")

    d2a_dir = Path(cfg["d2a_dir"])
    manifest_path = d2a_dir / "d2a_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    d2a_manifest = read_json(manifest_path)
    if d2a_manifest.get("status") != EXPECTED_D2A_STATUS:
        raise RuntimeError(f"Unexpected D2A status {d2a_manifest.get('status')}")

    dims = len(cfg["features_per_snapshot"]) * len(cfg["expected"]["snapshot_order"])
    cell_scales: dict[str, np.ndarray] = {}
    counts = part.analysis_cell_id.astype(str).value_counts().to_dict()
    cells = sorted(counts)
    if len(cells) != int(cfg["expected"]["analysis_cells"]):
        raise RuntimeError(f"Analysis-cell census changed: {len(cells)}")
    for cid in cells:
        cell_dir = d2a_dir / "cells" / cid
        meta_path = cell_dir / "d2a_split_discovery.meta.json"
        csv_path = cell_dir / "d2a_split_discovery.csv"
        if not meta_path.is_file() or not csv_path.is_file():
            raise FileNotFoundError(f"Missing frozen D2A cell outputs for {cid}")
        meta = read_json(meta_path)
        if meta.get("schema_version") != "akerpuls-d2a-cell-result-v1":
            raise RuntimeError(f"Unexpected D2A cell meta schema for {cid}")
        if str(meta.get("analysis_cell_id")) != cid:
            raise RuntimeError(f"D2A cell meta ID mismatch for {cid}")
        if int(meta.get("owner_fields", -1)) != int(counts[cid]):
            raise RuntimeError(f"D2A owner-field count mismatch for {cid}")
        if sha256_file(csv_path) != meta.get("csv_sha256"):
            raise RuntimeError(f"D2A cell CSV hash changed for {cid}")
        scale = np.asarray(meta.get("normalization_scale", []), dtype=float)
        if scale.shape != (dims,) or not np.isfinite(scale).all() or np.any(scale <= 0):
            raise RuntimeError(f"Invalid frozen D2A normalization scale for {cid}")
        cell_scales[cid] = scale

    vrt_idx = pd.read_csv(vrt_index_path, encoding="utf-8-sig")
    if "snapshot" not in vrt_idx.columns or "path" not in vrt_idx.columns:
        raise RuntimeError("VRT index missing snapshot/path")
    rows = {str(r.snapshot): r for r in vrt_idx.itertuples(index=False)}
    snaps = list(cfg["expected"]["snapshot_order"])
    if set(rows) != set(snaps):
        raise RuntimeError(f"VRT snapshot set changed: {sorted(rows)}")

    return g, cell_scales, rows, repair_info, d2cfg, d2a


def build_same_block_adjacency(g, cfg: dict[str, Any]):
    import geopandas as gpd

    min_shared = float(cfg["adjacency"]["minimum_shared_boundary_m"])
    records = []
    geoms = []
    multi_blocks = 0
    combos_checked = 0
    for block_id, idxs in g.groupby("block_id_2025", sort=True).groups.items():
        pos = list(idxs)
        if len(pos) < 2:
            continue
        multi_blocks += 1
        for i, j in itertools.combinations(pos, 2):
            combos_checked += 1
            gi = g.geometry.iloc[int(i)]
            gj = g.geometry.iloc[int(j)]
            shared = gi.boundary.intersection(gj.boundary)
            shared_len = float(shared.length) if shared is not None and not shared.is_empty else 0.0
            if shared_len < min_shared:
                continue
            ida = str(g.parent_field_id_2025.iloc[int(i)])
            idb = str(g.parent_field_id_2025.iloc[int(j)])
            if ida <= idb:
                ia, ib, a, b = int(i), int(j), ida, idb
            else:
                ia, ib, a, b = int(j), int(i), idb, ida
            records.append({
                "block_id_2025": str(block_id),
                "field_a": a,
                "field_b": b,
                "pos_a": ia,
                "pos_b": ib,
                "analysis_cell_a": str(g.analysis_cell_id.iloc[ia]),
                "analysis_cell_b": str(g.analysis_cell_id.iloc[ib]),
                "cross_cell_pair": str(g.analysis_cell_id.iloc[ia]) != str(g.analysis_cell_id.iloc[ib]),
                "shared_boundary_m_2025": shared_len,
            })
            geoms.append(shared)
    df = pd.DataFrame(records)
    if df.empty:
        raise RuntimeError("No same-block touching field pairs found")
    pair_keys = df.field_a.astype(str) + "||" + df.field_b.astype(str)
    if pair_keys.duplicated().any():
        raise RuntimeError("Duplicate same-block adjacency pair")
    gdf = gpd.GeoDataFrame(df, geometry=geoms, crs=g.crs)
    return gdf, multi_blocks, combos_checked


def field_raw_stats(mask, all_valid, raw28, ndi, erosion_pixels: int, minpix: int, fallback: bool):
    interior = ndi.binary_erosion(
        mask,
        structure=np.ones((3, 3), dtype=bool),
        iterations=int(erosion_pixels),
        border_value=0,
    )
    if int(interior.sum()) < minpix and fallback:
        interior = mask
    m = interior & all_valid
    n = int(m.sum())
    if n < minpix:
        return None
    x = raw28[:, m].T.astype(np.float64, copy=False)
    mu = np.nanmean(x, axis=0)
    mse = np.nanmean(np.square(x - mu), axis=0)
    if not np.isfinite(mu).all() or not np.isfinite(mse).all():
        return None
    return {"mean": mu, "mse": mse, "pixels": n}


def pair_scale(cell_a: str, cell_b: str, scales: dict[str, np.ndarray]) -> np.ndarray:
    sa = scales[cell_a]
    sb = scales[cell_b]
    if cell_a == cell_b:
        return sa
    return np.sqrt(sa * sb)


def evaluate_all_pairs(g, pairs, cell_scales, rows, cfg, d2a):
    import rasterio
    from rasterio.features import rasterize
    from rasterio.windows import transform as window_transform
    from scipy import ndimage as ndi

    features = list(cfg["features_per_snapshot"])
    snaps = list(cfg["expected"]["snapshot_order"])
    dims_per = len(features)
    fsc = cfg["field_stats"]
    mg = cfg["merge"]
    pad_m = (int(mg["boundary_dilation_pixels"]) + 1) * float(cfg["expected"]["resolution_m"])

    datasets = [rasterio.open(str(rows[s].path)) for s in snaps]
    try:
        band_maps = []
        ref_transform = datasets[0].transform
        ref_shape = (datasets[0].height, datasets[0].width)
        for s, ds in zip(snaps, datasets):
            desc = list(ds.descriptions)
            bm = {n: i + 1 for i, n in enumerate(desc) if n}
            missing = [x for x in features + ["VALID"] if x not in bm]
            if missing:
                raise RuntimeError(f"{s} VRT missing bands: {missing}")
            if ds.crs is None or int(ds.crs.to_epsg() or -1) != int(cfg["expected"]["target_crs_epsg"]):
                raise RuntimeError(f"{s} VRT CRS changed: {ds.crs}")
            if ds.transform != ref_transform or (ds.height, ds.width) != ref_shape:
                raise RuntimeError(f"{s} VRT grid differs from first snapshot")
            band_maps.append(bm)

        results = []
        pair_geoms = []
        by_block = pairs.groupby("block_id_2025", sort=True)
        nblocks = len(by_block)
        for bi, (block_id, pblock) in enumerate(by_block, 1):
            positions = sorted(set(pblock.pos_a.astype(int)).union(set(pblock.pos_b.astype(int))))
            geoms = [g.geometry.iloc[p] for p in positions]
            b = np.asarray([x.bounds for x in geoms], dtype=float)
            bounds = (
                float(b[:, 0].min() - pad_m),
                float(b[:, 1].min() - pad_m),
                float(b[:, 2].max() + pad_m),
                float(b[:, 3].max() + pad_m),
            )
            win = d2a.aligned_window(datasets[0], bounds)
            tr = window_transform(win, datasets[0].transform)
            h, w = int(win.height), int(win.width)
            local_by_pos = {p: k + 1 for k, p in enumerate(positions)}
            labels = rasterize(
                [(g.geometry.iloc[p], local_by_pos[p]) for p in positions],
                out_shape=(h, w),
                transform=tr,
                fill=0,
                dtype="int32",
                all_touched=False,
            )

            cubes = []
            valids = []
            for ds, bm in zip(datasets, band_maps):
                idx = [int(bm[x]) for x in features] + [int(bm["VALID"])]
                arr = ds.read(idx, window=win).astype(np.float32)
                cubes.append(arr[:dims_per])
                valids.append(arr[dims_per] > 0.5)
            all_valid = np.logical_and.reduce(valids)
            raw28 = np.concatenate(cubes, axis=0)

            stats = {}
            masks = {}
            for p in positions:
                m = labels == local_by_pos[p]
                masks[p] = m
                stats[p] = field_raw_stats(
                    m,
                    all_valid,
                    raw28,
                    ndi,
                    int(fsc["interior_erosion_pixels"]),
                    int(fsc["minimum_all4_valid_pixels"]),
                    bool(fsc["fallback_to_full_field_if_eroded_too_small"]),
                )

            for pr in pblock.itertuples(index=True):
                ia, ib = int(pr.pos_a), int(pr.pos_b)
                scale = pair_scale(str(pr.analysis_cell_a), str(pr.analysis_cell_b), cell_scales)
                fs_a = stats.get(ia)
                fs_b = stats.get(ib)
                if fs_a is None or fs_b is None:
                    status, conf, bmed, valid_snaps, strong = "UNCERTAIN", 0.0, None, 0, 0
                    field_dist = float("nan")
                    bw_ratio = float("nan")
                    boundary = [None, None, None, None]
                    reason = "INSUFFICIENT_ALL4_FIELD_PIXELS"
                else:
                    field_dist = rms((fs_a["mean"] - fs_b["mean"]) / scale)
                    within_a = math.sqrt(float(np.mean(fs_a["mse"] / np.square(scale))))
                    within_b = math.sqrt(float(np.mean(fs_b["mse"] / np.square(scale))))
                    pooled = 0.5 * (within_a + within_b)
                    bw_ratio = field_dist / max(pooled, 0.15)

                    ma, mb = masks[ia], masks[ib]
                    structure = np.ones((3, 3), dtype=bool)
                    strip_a = ma & ndi.binary_dilation(
                        mb, iterations=int(mg["boundary_dilation_pixels"]), structure=structure
                    )
                    strip_b = mb & ndi.binary_dilation(
                        ma, iterations=int(mg["boundary_dilation_pixels"]), structure=structure
                    )
                    boundary = []
                    for sidx in range(4):
                        va = strip_a & valids[sidx]
                        vb = strip_b & valids[sidx]
                        if (
                            int(va.sum()) < int(mg["minimum_strip_pixels_per_side"])
                            or int(vb.sum()) < int(mg["minimum_strip_pixels_per_side"])
                        ):
                            boundary.append(None)
                            continue
                        sl = slice(sidx * dims_per, (sidx + 1) * dims_per)
                        ma_raw = cubes[sidx][:, va].mean(axis=1).astype(float)
                        mb_raw = cubes[sidx][:, vb].mean(axis=1).astype(float)
                        boundary.append(rms((ma_raw - mb_raw) / scale[sl]))
                    status, conf, bmed, valid_snaps, strong = merge_score_and_decision(
                        mg, field_dist, bw_ratio, boundary
                    )
                    reason = "FROZEN_B2_MERGE_BASELINE"

                results.append({
                    "block_id_2025": str(block_id),
                    "field_a": str(pr.field_a),
                    "field_b": str(pr.field_b),
                    "analysis_cell_a": str(pr.analysis_cell_a),
                    "analysis_cell_b": str(pr.analysis_cell_b),
                    "cross_cell_pair": bool(pr.cross_cell_pair),
                    "shared_boundary_m_2025": round(float(pr.shared_boundary_m_2025), 4),
                    "m0_status": status,
                    "satellite_merge_score": round(float(conf), 6),
                    "field_mean_distance": None if not np.isfinite(field_dist) else round(float(field_dist), 6),
                    "between_within_ratio": None if not np.isfinite(bw_ratio) else round(float(bw_ratio), 6),
                    "boundary_median_distance": None if bmed is None else round(float(bmed), 6),
                    "valid_boundary_snapshots": int(valid_snaps),
                    "strong_edge_snapshots": int(strong),
                    "edge_april": None if boundary[0] is None else round(float(boundary[0]), 6),
                    "edge_may": None if boundary[1] is None else round(float(boundary[1]), 6),
                    "edge_june": None if boundary[2] is None else round(float(boundary[2]), 6),
                    "edge_july": None if boundary[3] is None else round(float(boundary[3]), 6),
                    "history_prior_used": False,
                    "m4_prior_used": False,
                    "fusion_used": False,
                    "reason": reason,
                })
                pair_geoms.append(pairs.geometry.iloc[int(pr.Index)])

            if bi == 1 or bi % 250 == 0 or bi == nblocks:
                log(f"MERGE_M0_BLOCK_PROGRESS={bi}/{nblocks} PAIRS_DONE={len(results)}/{len(pairs)}")

        return pd.DataFrame(results), pair_geoms
    finally:
        for ds in datasets:
            ds.close()


def write_gpkg(gdf, path: Path) -> None:
    tmp = path.with_name(path.stem + ".partial.gpkg")
    if tmp.exists():
        tmp.unlink()
    gdf.to_file(tmp, layer="m0_satellite_merge_boundaries", driver="GPKG", index=False)
    tmp.replace(path)


def main() -> int:
    import geopandas as gpd

    ap = argparse.ArgumentParser()
    ap.add_argument("--d2c-dir", default=str(DEFAULT_D2C))
    ap.add_argument("--output-dir")
    args = ap.parse_args()

    cfg = read_json(CFG)
    validate_config(cfg)
    head = git_guard(cfg)
    d2c = Path(args.d2c_dir)
    out = Path(args.output_dir or cfg["output_dir"])

    if out.exists():
        mp = out / MANIFEST_NAME
        if mp.is_file():
            m = read_json(mp)
            if m.get("status") == STATUS:
                for rec in m.get("output_hashes", {}).values():
                    p = out / rec["relative_path"]
                    if not p.is_file() or sha256_file(p) != rec["sha256"]:
                        raise RuntimeError(f"Existing M0 output changed: {p}")
                print("AKERPULS MERGE M0 SATELLITE-ONLY")
                print("STATUS=PASS_TO_M0_SATELLITE_MERGE_REVIEW_STOP_CACHED")
                print(f"OUTPUT={out}")
                return 0
        raise RuntimeError(f"Output directory already exists without a valid completed manifest: {out}")

    log("MERGE_M0_PROGRESS=VERIFY_FROZEN_LINEAGE_AND_LOAD_CONTEXT")
    g, cell_scales, vrt_rows, repair_info, d2cfg, d2a = load_frozen_context(cfg, d2c)

    log("MERGE_M0_PROGRESS=BUILD_SAME_BLOCK_TOUCHING_ADJACENCY")
    pairs, multi_blocks, combos_checked = build_same_block_adjacency(g, cfg)
    cross_cell_pairs = int(pairs.cross_cell_pair.astype(bool).sum())
    log(
        f"MERGE_M0_ADJACENCY_PAIRS={len(pairs)} MULTI_FIELD_BLOCKS={multi_blocks} "
        f"PAIR_COMBINATIONS_CHECKED={combos_checked} CROSS_CELL_PAIRS={cross_cell_pairs}"
    )

    log("MERGE_M0_PROGRESS=RUN_SATELLITE_ONLY_BOUNDARY_DISAPPEARANCE")
    result, pair_geoms = evaluate_all_pairs(g, pairs, cell_scales, vrt_rows, cfg, d2a)
    if len(result) != len(pairs):
        raise RuntimeError(f"M0 result row count mismatch: {len(result)} vs {len(pairs)}")
    key = result.field_a.astype(str) + "||" + result.field_b.astype(str)
    if key.duplicated().any():
        raise RuntimeError("M0 result contains duplicate pair keys")

    assessable = result.m0_status.astype(str).isin(["MERGE_CANDIDATE", "KEEP_BOUNDARY"])
    if assessable.any():
        rank = result.loc[assessable, "satellite_merge_score"].rank(method="average", pct=True)
        result["satellite_score_percentile"] = np.nan
        result.loc[assessable, "satellite_score_percentile"] = rank.to_numpy()
        vals = result.loc[assessable, "satellite_merge_score"].astype(float).to_numpy()
        q = {f"p{p}": float(np.quantile(vals, p / 100.0)) for p in (50, 90, 95, 99)}
    else:
        result["satellite_score_percentile"] = np.nan
        q = {f"p{p}": None for p in (50, 90, 95, 99)}

    counts = result.m0_status.astype(str).value_counts().to_dict()
    for k in ("MERGE_CANDIDATE", "KEEP_BOUNDARY", "UNCERTAIN"):
        counts.setdefault(k, 0)

    out.mkdir(parents=True, exist_ok=False)
    csv_path = out / CSV_NAME
    result.sort_values(["block_id_2025", "field_a", "field_b"]).to_csv(csv_path, index=False, encoding="utf-8-sig")

    gout = gpd.GeoDataFrame(result.copy(), geometry=pair_geoms, crs=g.crs)
    gpkg_path = out / GPKG_NAME
    write_gpkg(gout, gpkg_path)

    summary = {
        "schema_version": "akerpuls-merge-m0-satellite-only-summary-v1",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "parent_preliminary_geometry_v1_freeze_sha256": EXPECTED_PRELIM_FREEZE_SHA256,
        "official_2025_geometry_sha256": cfg["official_2025_geometry_sha256"],
        "vrt_index_sha256": cfg["expected_vrt_index_sha256"],
        "scope": {
            "candidate_universe": "TOUCHING_2025_SKIFTEN_WITHIN_SAME_2025_BLOCK",
            "same_block_only": True,
            "minimum_shared_boundary_m": float(cfg["adjacency"]["minimum_shared_boundary_m"]),
            "satellite_only": True,
            "history_prior_used": False,
            "m4_prior_used": False,
            "fusion_used": False,
        },
        "census": {
            "fields_2025": int(cfg["expected"]["fields_2025"]),
            "blocks_2025": int(cfg["expected"]["blocks_2025"]),
            "multi_field_blocks": int(multi_blocks),
            "pair_combinations_checked": int(combos_checked),
            "same_block_touching_pairs": int(len(pairs)),
            "cross_analysis_cell_pairs": int(cross_cell_pairs),
            "assessable_pairs": int(assessable.sum()),
            "merge_candidate": int(counts["MERGE_CANDIDATE"]),
            "keep_boundary": int(counts["KEEP_BOUNDARY"]),
            "uncertain": int(counts["UNCERTAIN"]),
        },
        "satellite_score_quantiles_assessable": q,
        "merge_contract": cfg["merge"],
        "normalization_contract": cfg["normalization"],
        "projected_geometry_repair_info": repair_info,
        "guards": {
            "network_calls": False,
            "history_prior_execution": False,
            "m4_prior_execution": False,
            "fusion_execution": False,
            "thresholds_tuned": False,
            "automatic_merge": False,
            "official_geometry_replaced": False,
            "automatic_geometry_mutation": False,
        },
        "interpretation": (
            "M0 is a satellite-only boundary-disappearance ranking. MERGE_CANDIDATE is a review candidate, "
            "not an adopted merge. ÅkerMinne/M4 is intentionally absent so its incremental value can be measured later."
        ),
        "next_step": "REVIEW_AND_FREEZE_M0_BEFORE_M1_AKERMINNE_M4_PAIR_PRIOR",
    }
    summary_path = out / SUMMARY_NAME
    write_json(summary_path, summary)

    report = f"""# ÅkerPuls Merge M0 — satellite-only full Skåne

Status: `{STATUS}`

This stage deliberately excludes ÅkerMinne/M4 and fusion.

## Candidate universe
- 2025 fields: {cfg['expected']['fields_2025']:,}
- 2025 blocks: {cfg['expected']['blocks_2025']:,}
- Multi-field blocks: {multi_blocks:,}
- Same-block touching boundaries evaluated: {len(pairs):,}
- Cross-analysis-cell pairs: {cross_cell_pairs:,}

## M0 result
- Assessable: {int(assessable.sum()):,}
- `MERGE_CANDIDATE`: {counts['MERGE_CANDIDATE']:,}
- `KEEP_BOUNDARY`: {counts['KEEP_BOUNDARY']:,}
- `UNCERTAIN`: {counts['UNCERTAIN']:,}

Satellite score quantiles among assessable pairs:
- P50: {q['p50']}
- P90: {q['p90']}
- P95: {q['p95']}
- P99: {q['p99']}

## Frozen pilot merge logic
The full-Skåne M0 run reuses the original B2 pilot merge features and thresholds:
field-mean similarity, boundary-strip similarity across four snapshots, between/within ratio,
strong-edge count, and the original confidence formula. Frozen D2A local normalization scales
are reused. Cross-cell pairs use the geometric mean of the two frozen cell scales.

## Scope guard
No history prior, M4 crop prior, fusion, threshold tuning, automatic merge, or geometry mutation occurs.
The next stage is to review/freeze this satellite-only result before calculating an ÅkerMinne/M4 pair prior.
"""
    report_path = out / REPORT_NAME
    write_text(report_path, report)

    output_files = [csv_path, gpkg_path, summary_path, report_path]
    output_hashes = {
        p.name: {
            "relative_path": p.name,
            "sha256": sha256_file(p),
            "bytes": int(p.stat().st_size),
        }
        for p in output_files
    }
    manifest = {
        "schema_version": "akerpuls-merge-m0-satellite-only-manifest-v1",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "config_sha256": sha256_file(CFG),
        "output_hashes": output_hashes,
        "history_prior_used": False,
        "m4_prior_used": False,
        "fusion_used": False,
        "automatic_merge": False,
        "geometry_mutation": False,
        "next_stop": "REVIEW_M0_SATELLITE_ONLY_MERGE_CENSUS_AND_SCORE_DISTRIBUTION",
    }
    write_json(out / MANIFEST_NAME, manifest)

    print("AKERPULS MERGE M0 SATELLITE-ONLY")
    print(f"STATUS={STATUS}")
    print(f"SAME_BLOCK_TOUCHING_PAIRS={len(pairs)} ASSESSABLE={int(assessable.sum())}")
    print(
        f"MERGE_CANDIDATE={counts['MERGE_CANDIDATE']} "
        f"KEEP_BOUNDARY={counts['KEEP_BOUNDARY']} UNCERTAIN={counts['UNCERTAIN']}"
    )
    print(
        "SATELLITE_SCORE_QUANTILES="
        f"P50:{q['p50']} P90:{q['p90']} P95:{q['p95']} P99:{q['p99']}"
    )
    print(f"CROSS_ANALYSIS_CELL_PAIRS={cross_cell_pairs}")
    print("HISTORY_PRIOR_USED=FALSE M4_PRIOR_USED=FALSE FUSION_USED=FALSE")
    print("THRESHOLDS_TUNED=FALSE AUTOMATIC_MERGE=FALSE GEOMETRY_MUTATION=FALSE")
    print("NEXT=REVIEW_AND_FREEZE_M0_BEFORE_M1_AKERMINNE_M4_PAIR_PRIOR")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
