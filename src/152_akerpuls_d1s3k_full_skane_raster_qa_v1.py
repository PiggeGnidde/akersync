#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D1-S3k: zero-network full-Skane raster and field-validity QA.

Scans the completed D1-S3j snapshot tiles only. No STAC, S3, Process API,
model/fusion execution or persisted geometry mutation occurs. All 128,636 frozen
2025 fields are rasterized tile-by-tile on the exact 10 m D0 grid and VALID
coverage is accumulated for all four frozen snapshots and their intersection.

The source geometry is required to be the exact frozen, valid geometry accepted
by D0. If reprojection to EPSG:32633 alone creates a numerically invalid polygon,
a tightly area-bounded in-memory make-valid repair is allowed for QA
rasterization only; it is reported and is never persisted as field geometry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_d1s3k_full_skane_raster_qa_v1.json"


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


def q(values: np.ndarray, p: float) -> float:
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    return float(np.quantile(x, p)) if x.size else float("nan")


def polygonal_make_valid(geom):
    """Return a valid polygonal geometry, dropping only non-area make-valid debris."""
    from shapely.geometry import Polygon, MultiPolygon
    from shapely.ops import unary_union
    try:
        from shapely import make_valid
    except ImportError:  # pragma: no cover - Shapely <2 compatibility
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
        raise RuntimeError(f"Projected geometry repair is not a valid polygon/multipolygon: {out.geom_type}")
    return out


def validate_config(cfg: dict[str, Any]) -> None:
    if cfg.get("schema_version") != "akerpuls-d1s3k-full-skane-raster-qa-v1":
        raise RuntimeError("Unexpected D1-S3k config schema")
    if any(bool(v) for v in cfg["guards"].values()):
        raise RuntimeError("D1-S3k forbidden-scope guard unexpectedly enabled")
    if not bool(cfg["acceptance"]["frozen_before_full_skane_field_validity_outcomes"]):
        raise RuntimeError("D1-S3k acceptance was not frozen before field-validity outcomes")
    exp = cfg["expected"]
    if int(exp["fields"]) != 128636 or int(exp["raster_tiles"]) != 142 or int(exp["snapshot_tiles"]) != 568:
        raise RuntimeError("Frozen full-Skane domain changed")
    if int(exp["minimum_b2_valid_pixels"]) != 24:
        raise RuntimeError("B2 minimum-valid-pixels reference changed")
    gp = cfg["projection_geometry_policy"]
    if not bool(gp["require_source_geometry_valid_before_reprojection"]):
        raise RuntimeError("D1-S3k must require valid source geometry")
    if not bool(gp["repair_invalid_projected_geometry_for_qa_rasterization_only"]):
        raise RuntimeError("D1-S3k projected-geometry repair policy unexpectedly disabled")
    if gp["repair_method"] != "SHAPELY_MAKE_VALID_POLYGONAL_ONLY":
        raise RuntimeError("Unexpected projected-geometry repair method")
    if bool(gp["persist_repaired_geometry"]) or bool(gp["automatic_geometry_replacement"]):
        raise RuntimeError("Projected-geometry QA repair must never be persisted/replaced")


def main() -> int:
    import geopandas as gpd
    import rasterio
    from rasterio.crs import CRS
    from rasterio.features import rasterize
    from rasterio.transform import from_bounds
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

    log("D1S3K_PROGRESS=VERIFY_D1S3J_PARENT_AND_FROZEN_INDEXES")
    jman_path = Path(cfg["d1s3j_manifest"])
    snap_index_path = Path(cfg["d1s3j_snapshot_outputs"])
    vrt_index_path = Path(cfg["d1s3j_vrt_outputs"])
    if not jman_path.is_file() or not snap_index_path.is_file() or not vrt_index_path.is_file():
        raise FileNotFoundError("D1-S3j manifest/output indexes missing")
    jman = read_json(jman_path)
    if jman.get("status") != cfg["required_d1s3j_status"]:
        raise RuntimeError(f"D1-S3j status changed: {jman.get('status')}")
    if int(jman.get("public_stac_http_calls", -1)) != 0 or int(jman.get("process_api_calls", -1)) != 0:
        raise RuntimeError("D1-S3j provenance contains forbidden STAC/Process calls")
    if bool(jman.get("full_skane_model_executed")) or bool(jman.get("automatic_geometry_replacement")):
        raise RuntimeError("D1-S3j provenance unexpectedly executed model/geometry mutation")
    snap_index_sha = sha256_file(snap_index_path)
    vrt_index_sha = sha256_file(vrt_index_path)
    if snap_index_sha != cfg["expected_snapshot_output_index_sha256"]:
        raise RuntimeError(f"Snapshot output index hash changed: {snap_index_sha}")
    if vrt_index_sha != cfg["expected_vrt_output_index_sha256"]:
        raise RuntimeError(f"VRT output index hash changed: {vrt_index_sha}")
    if jman.get("output_index_hashes", {}).get("snapshot_outputs_index_sha256") != snap_index_sha:
        raise RuntimeError("D1-S3j manifest/snapshot-index SHA mismatch")
    if jman.get("output_index_hashes", {}).get("vrt_outputs_index_sha256") != vrt_index_sha:
        raise RuntimeError("D1-S3j manifest/VRT-index SHA mismatch")

    jcfg_path = ROOT / cfg["d1s3j_config"]
    jcfg = read_json(jcfg_path)
    exp = cfg["expected"]
    snap_names = list(jman["derived"]["snapshot_validity_all_tile_pixels"].keys())
    snap_names = sorted(snap_names, key=lambda s: min(str(d) for d in read_json(Path(jcfg["full_skane_s3_execution_contract"]))["frozen_snapshots"][s]))
    if len(snap_names) != int(exp["snapshot_count"]):
        raise RuntimeError("D1-S3j snapshot count changed")

    snap_idx = pd.read_csv(snap_index_path, encoding="utf-8-sig", dtype={"tile_id": str, "snapshot": str})
    vrt_idx = pd.read_csv(vrt_index_path, encoding="utf-8-sig", dtype={"snapshot": str})
    if len(snap_idx) != int(exp["snapshot_tiles"]) or len(vrt_idx) != int(exp["snapshot_count"]):
        raise RuntimeError("D1-S3j output index row count changed")
    if snap_idx[["snapshot", "tile_id"]].duplicated().any():
        raise RuntimeError("Duplicate snapshot/tile index row")
    if set(snap_idx.snapshot.astype(str)) != set(snap_names):
        raise RuntimeError("Snapshot names in index differ from parent manifest")

    log("D1S3K_PROGRESS=VERIFY_4_VRT_HEADERS")
    expected_bands = list(exp["snapshot_bands"])
    crs_expected = CRS.from_epsg(int(exp["target_crs_epsg"]))
    vrt_checks = []
    for r in vrt_idx.itertuples(index=False):
        path = Path(str(r.path))
        if not path.is_file():
            raise FileNotFoundError(path)
        with rasterio.open(path) as ds:
            ok = (
                ds.count == len(expected_bands)
                and ds.crs == crs_expected
                and list(ds.descriptions) == expected_bands
                and float(abs(ds.transform.a)) == float(exp["resolution_m"])
                and float(abs(ds.transform.e)) == float(exp["resolution_m"])
            )
            if not ok:
                raise RuntimeError(f"VRT header/band contract mismatch: {path}")
            vrt_checks.append({"snapshot": str(r.snapshot), "path": str(path), "width": ds.width, "height": ds.height,
                               "bands": ds.count, "crs": str(ds.crs), "resolution_m": abs(float(ds.transform.a))})
    pd.DataFrame(vrt_checks).to_csv(out / "d1s3k_vrt_header_qa.csv", index=False, encoding="utf-8-sig")

    log("D1S3K_PROGRESS=VERIFY_FROZEN_GEOMETRY_AND_FIELD_PARTITION")
    local_paths_path = ROOT / cfg["local_paths"] if not Path(cfg["local_paths"]).is_absolute() else Path(cfg["local_paths"])
    local_paths = read_json(local_paths_path)
    geom_path = Path(local_paths[cfg["geometry_local_paths_key"]])
    if not geom_path.is_file():
        raise FileNotFoundError(geom_path)
    geom_sha = sha256_file(geom_path)
    if geom_sha != cfg["expected_geometry_sha256"]:
        raise RuntimeError(f"Frozen geometry SHA changed: {geom_sha}")
    g0 = gpd.read_file(geom_path)
    if len(g0) != int(exp["fields"]):
        raise RuntimeError(f"Frozen field count changed: {len(g0)}")
    if g0.crs is None:
        raise RuntimeError("Frozen geometry has no CRS")
    ids = infer_ids(g0)
    if ids.duplicated().any():
        raise RuntimeError("Frozen field IDs are not unique")

    # Match the original D0 source-geometry invariant before any reprojection.
    source_good = g0.geometry.notna() & ~g0.geometry.is_empty & g0.geometry.is_valid
    source_invalid = int((~source_good).sum())
    if source_invalid:
        raise RuntimeError(f"Frozen source geometry contains {source_invalid} null/empty/invalid rows; source freeze no longer matches D0 validity invariant")

    g = g0.to_crs(int(exp["target_crs_epsg"])).copy().reset_index(drop=True)
    g["parent_field_id_2025"] = ids.to_numpy()
    projected_present = g.geometry.notna() & ~g.geometry.is_empty
    if not bool(projected_present.all()):
        bad = int((~projected_present).sum())
        raise RuntimeError(f"Reprojection created {bad} null/empty geometries")

    # CRS transformation can occasionally introduce a tiny topology defect through
    # floating-point coordinate transformation even though the frozen source polygon
    # is valid. Repair only that projected in-memory rasterization view and bound the
    # area change tightly before continuing.
    projected_invalid_positions = np.flatnonzero(~g.geometry.is_valid.to_numpy())
    gp = cfg["projection_geometry_policy"]
    max_abs_allowed = float(gp["maximum_absolute_area_change_m2"])
    max_rel_allowed = float(gp["maximum_relative_area_change"])
    repair_rows = []
    for pos in projected_invalid_positions:
        geom = g.geometry.iloc[int(pos)]
        before_area = float(geom.area)
        fixed = polygonal_make_valid(geom)
        after_area = float(fixed.area)
        abs_delta = abs(after_area - before_area)
        rel_delta = abs_delta / max(abs(before_area), 1.0)
        fid = str(g.parent_field_id_2025.iloc[int(pos)])
        repair_rows.append({
            "parent_field_id_2025": fid,
            "position": int(pos),
            "before_geom_type": str(geom.geom_type),
            "after_geom_type": str(fixed.geom_type),
            "before_area_m2": before_area,
            "after_area_m2": after_area,
            "absolute_area_change_m2": abs_delta,
            "relative_area_change": rel_delta,
        })
        if abs_delta > max_abs_allowed and rel_delta > max_rel_allowed:
            raise RuntimeError(
                f"Projected geometry repair exceeds frozen QA tolerance for {fid}: "
                f"abs_delta_m2={abs_delta:.12g} rel_delta={rel_delta:.12g}"
            )
        g.at[int(pos), "geometry"] = fixed
    if not bool((g.geometry.notna() & ~g.geometry.is_empty & g.geometry.is_valid).all()):
        raise RuntimeError("Projected geometry remains invalid after bounded QA-only repair")
    repair_df = pd.DataFrame(repair_rows, columns=[
        "parent_field_id_2025", "position", "before_geom_type", "after_geom_type",
        "before_area_m2", "after_area_m2", "absolute_area_change_m2", "relative_area_change",
    ])
    repair_df.to_csv(out / "d1s3k_projected_geometry_repairs.csv", index=False, encoding="utf-8-sig")
    max_repair_abs = float(repair_df.absolute_area_change_m2.max()) if len(repair_df) else 0.0
    max_repair_rel = float(repair_df.relative_area_change.max()) if len(repair_df) else 0.0
    log(
        f"D1S3K_GEOMETRY SOURCE_INVALID={source_invalid} PROJECTED_INVALID_BEFORE_REPAIR={len(projected_invalid_positions)} "
        f"REPAIRED_FOR_QA={len(repair_df)} MAX_ABS_AREA_DELTA_M2={max_repair_abs:.12g} MAX_REL_AREA_DELTA={max_repair_rel:.12g}"
    )

    contract = read_json(Path(cfg["d0b_final_execution_contract"]))
    part_path = Path(cfg["d0_field_partition"])
    if sha256_file(part_path) != contract["field_partition"]["sha256"]:
        raise RuntimeError("D0 field partition SHA changed")
    part = pd.read_csv(part_path, encoding="utf-8-sig", dtype={"parent_field_id_2025": str, "analysis_cell_id": str, "home_raster_tile_id": str})
    if len(part) != len(g) or set(part.parent_field_id_2025) != set(g.parent_field_id_2025):
        raise RuntimeError("D0 field partition population differs from frozen geometry")

    tiles = pd.read_csv(cfg["d0_raster_tiles"], encoding="utf-8-sig", dtype={"tile_id": str})
    if len(tiles) != int(exp["raster_tiles"]):
        raise RuntimeError("D0 raster tile count changed")
    index_lookup = {(str(r.snapshot), str(r.tile_id)): Path(str(r.path)) for r in snap_idx.itertuples(index=False)}
    if len(index_lookup) != int(exp["snapshot_tiles"]):
        raise RuntimeError("Snapshot index is not complete")

    nfields = len(g)
    field_pixels = np.zeros(nfields + 1, dtype=np.int64)
    all4_pixels = np.zeros(nfields + 1, dtype=np.int64)
    valid_counts = {snap: np.zeros(nfields + 1, dtype=np.int64) for snap in snap_names}
    invalid_binary = 0; invalid_scl_on_valid = 0; nonfinite_indices = 0; bad_source_index = 0
    tile_stats = []
    sidx = g.sindex

    log("D1S3K_PROGRESS=SCAN_142_TILES_RASTERIZE_128636_FIELDS")
    for ti, tr in enumerate(tiles.sort_values("tile_id").itertuples(index=False), 1):
        tid = str(tr.tile_id)
        width = height = int(exp["tile_pixels"])
        transform = from_bounds(float(tr.minx), float(tr.miny), float(tr.maxx), float(tr.maxy), width, height)
        tile_geom = box(float(tr.minx), float(tr.miny), float(tr.maxx), float(tr.maxy))
        pos = list(sidx.query(tile_geom, predicate="intersects"))
        shapes = [(g.geometry.iloc[p], int(p) + 1) for p in pos]
        labels = rasterize(shapes, out_shape=(height, width), transform=transform, fill=0, dtype="int32", all_touched=False)
        field_pixels += np.bincount(labels.ravel(), minlength=nfields + 1).astype(np.int64)

        valids = []
        for snap in snap_names:
            path = index_lookup.get((snap, tid))
            if path is None or not path.is_file():
                raise FileNotFoundError(f"Missing snapshot tile {snap}/{tid}: {path}")
            with rasterio.open(path) as ds:
                if ds.width != width or ds.height != height or ds.count != len(expected_bands) or ds.crs != crs_expected or ds.transform != transform:
                    raise RuntimeError(f"Snapshot tile grid/header mismatch: {path}")
                if list(ds.descriptions) != expected_bands:
                    raise RuntimeError(f"Snapshot band descriptions changed: {path}")
                valid = ds.read(8).astype(np.float32)
                scl = ds.read(6).astype(np.float32)
                ndvi = ds.read(9).astype(np.float32)
                lswi = ds.read(10).astype(np.float32)
                source_idx = ds.read(11).astype(np.float32)
            is_valid = valid > 0.5
            invalid_binary += int(np.count_nonzero(~np.isin(valid, [0.0, 1.0])))
            rounded_scl = np.rint(scl).astype(np.int16)
            invalid_scl_on_valid += int(np.count_nonzero(is_valid & ~np.isin(rounded_scl, [2, 4, 5])))
            nonfinite_indices += int(np.count_nonzero(is_valid & (~np.isfinite(ndvi) | ~np.isfinite(lswi))))
            max_source = 1 if "+" in str(snap_idx.loc[snap_idx.snapshot.astype(str).eq(snap), "dates"].iloc[0]) else 0
            rounded_source = np.rint(source_idx).astype(np.int16)
            bad_source_index += int(np.count_nonzero((rounded_source < 0) | (rounded_source > max_source)))
            valid_counts[snap] += np.bincount(labels[is_valid].ravel(), minlength=nfields + 1).astype(np.int64)
            valids.append(is_valid)

        all4 = np.logical_and.reduce(valids)
        all4_pixels += np.bincount(labels[all4].ravel(), minlength=nfields + 1).astype(np.int64)
        field_mask = labels > 0
        tile_stats.append({"tile_id": tid, "intersecting_fields": len(pos), "field_pixels": int(field_mask.sum()),
                           "all4_valid_field_pixels": int(np.count_nonzero(field_mask & all4)),
                           "all4_valid_field_pixel_fraction": float(np.count_nonzero(field_mask & all4) / field_mask.sum()) if field_mask.any() else float("nan")})
        if ti % 10 == 0 or ti == len(tiles):
            log(f"D1S3K_TILE_PROGRESS={ti}/{len(tiles)}")

    fp = field_pixels[1:]
    a4 = all4_pixels[1:]
    denom = np.where(fp > 0, fp, 1)
    field_df = pd.DataFrame({
        "parent_field_id_2025": g.parent_field_id_2025.astype(str),
        "field_pixels": fp,
        "all4_valid_pixels": a4,
        "all4_valid_fraction": np.where(fp > 0, a4 / denom, np.nan),
    })
    for snap in snap_names:
        v = valid_counts[snap][1:]
        field_df[f"valid_pixels_{snap.lower()}"] = v
        field_df[f"valid_fraction_{snap.lower()}"] = np.where(fp > 0, v / denom, np.nan)
    minpix = int(exp["minimum_b2_valid_pixels"])
    field_df["pre_b2_ge24_all4_valid_pixels"] = field_df.all4_valid_pixels >= minpix
    field_df = field_df.merge(part[["parent_field_id_2025", "analysis_cell_id", "home_raster_tile_id", "area_ha_2025"]], on="parent_field_id_2025", how="left", validate="one_to_one")
    if field_df.analysis_cell_id.isna().any():
        raise RuntimeError("Field QA merge lost D0 partition rows")
    field_df.to_csv(out / "d1s3k_field_validity.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(tile_stats).to_csv(out / "d1s3k_tile_field_validity.csv", index=False, encoding="utf-8-sig")

    cell_rows = []
    for cid, x in field_df.groupby("analysis_cell_id", sort=True):
        total_pix = int(x.field_pixels.sum()); all4_pix = int(x.all4_valid_pixels.sum())
        cell_rows.append({
            "analysis_cell_id": cid,
            "owner_fields": int(len(x)),
            "fields_with_pixels": int((x.field_pixels > 0).sum()),
            "fields_ge24_all4_valid_pixels": int(x.pre_b2_ge24_all4_valid_pixels.sum()),
            "fraction_fields_ge24_all4_valid_pixels": float(x.pre_b2_ge24_all4_valid_pixels.mean()),
            "field_pixel_all4_valid_fraction": float(all4_pix / total_pix) if total_pix else float("nan"),
        })
    cells = pd.DataFrame(cell_rows)
    cells.to_csv(out / "d1s3k_analysis_cell_validity.csv", index=False, encoding="utf-8-sig")

    total_field_pixels = int(fp.sum())
    field_fraction_rasterized = float((fp > 0).mean())
    all4_field_pixel_fraction = float(a4.sum() / total_field_pixels) if total_field_pixels else 0.0
    pre_b2_fraction = float(field_df.pre_b2_ge24_all4_valid_pixels.mean())
    snap_summary = {}
    for snap in snap_names:
        vv = valid_counts[snap][1:]
        frac = np.where(fp > 0, vv / denom, np.nan)
        snap_summary[snap] = {
            "field_valid_pixels": int(vv.sum()),
            "field_pixel_valid_fraction": float(vv.sum() / total_field_pixels) if total_field_pixels else 0.0,
            "fields_ge_0p8_valid_fraction": int(np.count_nonzero(frac >= 0.8)),
            "fields_ge_0p5_valid_fraction": int(np.count_nonzero(frac >= 0.5)),
            "field_valid_fraction_p10": q(frac, .10),
            "field_valid_fraction_p50": q(frac, .50),
            "field_valid_fraction_p90": q(frac, .90),
        }

    acc = cfg["acceptance"]
    checks = {
        "parent_d1s3j_pass": jman.get("status") == cfg["required_d1s3j_status"],
        "geometry_and_partition_exact": len(field_df) == int(exp["fields"]) and geom_sha == cfg["expected_geometry_sha256"],
        "projected_geometry_qa_repair_bounded": source_invalid == 0 and all(
            (float(r["absolute_area_change_m2"]) <= max_abs_allowed) or (float(r["relative_area_change"]) <= max_rel_allowed)
            for r in repair_rows
        ),
        "snapshot_index_exact": snap_index_sha == cfg["expected_snapshot_output_index_sha256"] and len(snap_idx) == int(exp["snapshot_tiles"]),
        "vrt_index_exact": vrt_index_sha == cfg["expected_vrt_output_index_sha256"] and len(vrt_idx) == int(exp["snapshot_count"]),
        "field_rasterization_fraction": field_fraction_rasterized >= float(acc["minimum_fraction_fields_rasterized"]),
        "each_snapshot_field_pixel_valid_fraction": all(v["field_pixel_valid_fraction"] >= float(acc["minimum_field_pixel_valid_fraction_each_snapshot"]) for v in snap_summary.values()),
        "all4_field_pixel_valid_fraction": all4_field_pixel_fraction >= float(acc["minimum_field_pixel_all4_valid_fraction"]),
        "pre_b2_ge24_fraction": pre_b2_fraction >= float(acc["minimum_fraction_fields_with_at_least_24_all4_valid_pixels"]),
        "valid_band_binary": invalid_binary == 0 if bool(acc["require_binary_valid_band"]) else True,
        "valid_implies_clear_scl": invalid_scl_on_valid == 0 if bool(acc["require_valid_pixels_have_clear_scl"]) else True,
        "finite_indices_on_valid": nonfinite_indices == 0 if bool(acc["require_finite_ndvi_lswi_on_valid_pixels"]) else True,
        "source_date_index_range": bad_source_index == 0 if bool(acc["require_source_date_index_in_range"]) else True,
    }
    status = "PASS_TO_FULL_SKANE_D2_MODEL_PLAN" if all(checks.values()) else "REVIEW"

    worst_cells = cells.nsmallest(min(10, len(cells)), "fraction_fields_ge24_all4_valid_pixels")[[
        "analysis_cell_id", "owner_fields", "fields_ge24_all4_valid_pixels",
        "fraction_fields_ge24_all4_valid_pixels", "field_pixel_all4_valid_fraction",
    ]].to_dict("records")
    manifest = {
        "schema_version": "akerpuls-d1s3k-full-skane-raster-qa-result-v1",
        "status": status,
        "git": {"branch": branch, "head": head},
        "parent_d1s3j_status": jman.get("status"),
        "geometry_sha256": geom_sha,
        "geometry_projection_qa": {
            "source_invalid": source_invalid,
            "projected_invalid_before_repair": int(len(projected_invalid_positions)),
            "repaired_for_qa_rasterization": int(len(repair_rows)),
            "maximum_absolute_area_change_m2": max_repair_abs,
            "maximum_relative_area_change": max_repair_rel,
            "repair_method": gp["repair_method"],
            "persisted": False,
            "automatic_geometry_replacement": False,
        },
        "fields": int(len(field_df)),
        "raster_tiles": int(len(tiles)),
        "snapshot_tiles": int(len(snap_idx)),
        "snapshot_summary": snap_summary,
        "field_rasterization": {"fields_with_pixels": int((fp > 0).sum()), "fields_zero_pixels": int((fp == 0).sum()), "fraction_fields_rasterized": field_fraction_rasterized},
        "all4": {"field_pixel_valid_fraction": all4_field_pixel_fraction, "fields_ge24_all4_valid_pixels": int(field_df.pre_b2_ge24_all4_valid_pixels.sum()), "fraction_fields_ge24_all4_valid_pixels": pre_b2_fraction},
        "raster_semantic_violations": {"nonbinary_valid_pixels": invalid_binary, "valid_pixels_nonclear_scl": invalid_scl_on_valid,
                                       "nonfinite_ndvi_lswi_on_valid": nonfinite_indices, "source_date_index_out_of_range": bad_source_index},
        "analysis_cells": int(len(cells)),
        "worst_cells_by_pre_b2_fraction": worst_cells,
        "checks": checks,
        "network_calls": 0, "process_api_calls": 0, "sentinel_hub_pu_used": 0,
        "model_executed": False, "fusion_executed": False, "automatic_geometry_replacement": False,
        "interpretation": cfg["interpretation"],
    }
    (out / "d1s3k_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    log("AKERPULS D1-S3K FULL-SKANE ZERO-NETWORK RASTER/FIELD QA")
    log(f"STATUS={status}")
    log(f"FIELDS={len(field_df)} FIELDS_WITH_PIXELS={(fp > 0).sum()} ZERO_PIXEL_FIELDS={(fp == 0).sum()} FRACTION_RASTERIZED={field_fraction_rasterized:.6f}")
    for snap in snap_names:
        s = snap_summary[snap]
        log(f"{snap}: FIELD_PIXEL_VALID={s['field_pixel_valid_fraction']:.6f} FIELDS_GE80={s['fields_ge_0p8_valid_fraction']}/{len(field_df)} FIELDS_GE50={s['fields_ge_0p5_valid_fraction']}/{len(field_df)} P10={s['field_valid_fraction_p10']:.6f} P50={s['field_valid_fraction_p50']:.6f}")
    log(f"ALL4_FIELD_PIXEL_VALID={all4_field_pixel_fraction:.6f}")
    log(f"FIELDS_GE24_ALL4_VALID={int(field_df.pre_b2_ge24_all4_valid_pixels.sum())}/{len(field_df)} FRACTION={pre_b2_fraction:.6f}")
    log(f"ANALYSIS_CELLS={len(cells)} WORST_CELL={worst_cells[0]['analysis_cell_id'] if worst_cells else 'NONE'} WORST_CELL_GE24_FRACTION={worst_cells[0]['fraction_fields_ge24_all4_valid_pixels'] if worst_cells else float('nan'):.6f}")
    log(f"RASTER_SEMANTIC_VIOLATIONS=VALID_NONBINARY:{invalid_binary};VALID_NONCLEAR_SCL:{invalid_scl_on_valid};NONFINITE_INDICES:{nonfinite_indices};SOURCE_DATE_RANGE:{bad_source_index}")
    log("CHECKS=" + ";".join(f"{k}:{str(v).upper()}" for k, v in checks.items()))
    log("NETWORK_CALLS=0")
    log("PROCESS_API_CALLS=0")
    log("SENTINEL_HUB_PU_USED=0")
    log("FULL_SKANE_MODEL_EXECUTED=FALSE")
    log("AUTOMATIC_GEOMETRY_REPLACEMENT=FALSE")
    log(f"D1S3K_STATUS={status}")
    log(f"OUTPUT={out}")
    return 0 if status == "PASS_TO_FULL_SKANE_D2_MODEL_PLAN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
