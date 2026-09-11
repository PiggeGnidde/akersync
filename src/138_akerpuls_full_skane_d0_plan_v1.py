#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerPuls full-Skåne D0 execution planner v1.

Public STAC only. No Sentinel Hub Process API calls and zero PU.

The planner freezes the execution topology for applying the already-frozen
split-fusion QA v1 across all 128,636 official 2025 fields without changing
geometry. It validates lineage, rebuilds the exact raster request plan, checks
resource estimates against A0, and creates a deterministic 20 km local
normalization partition before any full-Skåne raster download is started.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import urllib.request
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_full_skane_d0_plan_v1.json"
MASTER = ROOT / "config" / "akerpuls_prelim_fields_2026_v0.json"
FREEZE_CFG = ROOT / "config" / "akerpuls_split_fusion_qa_v1.json"
B2_CFG = ROOT / "config" / "akerpuls_prelim_fields_2026_b2.json"
TRUE_LOO_CFG = ROOT / "config" / "akerpuls_true_loo_diagnostic_v0.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_json_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    if not rows and not fieldnames:
        return
    names = fieldnames or list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=names)
        w.writeheader()
        w.writerows(rows)


def stac_search(url: str, collection: str, bbox: list[float], day: str) -> list[dict[str, Any]]:
    d = date.fromisoformat(day)
    e = d + timedelta(days=1)
    body = json.dumps({
        "collections": [collection],
        "bbox": bbox,
        "datetime": f"{d}T00:00:00Z/{e}T00:00:00Z",
        "limit": 100,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        payload = json.loads(r.read().decode("utf-8"))
    return payload.get("features", [])


def infer_ids(g):
    import pandas as pd

    cols = {c.lower(): c for c in g.columns}
    if "blockid" in cols and "skiftesbeteckning" in cols:
        s = "2025|" + g[cols["blockid"]].astype(str) + "|" + g[cols["skiftesbeteckning"]].astype(str)
        return s.astype(str), "blockid+skiftesbeteckning"
    for key in ("current_field_id", "skiftesid", "skifte_id", "objectid", "id"):
        if key in cols:
            return g[cols[key]].astype(str), cols[key]
    vals = ["G2025_" + hashlib.sha256(geom.wkb).hexdigest()[:20] for geom in g.geometry]
    return pd.Series(vals, index=g.index, dtype=str), "geometry_sha256_20"


def raster_tile_id(x: float, y: float) -> str:
    return f"E{int(round(x)):07d}_N{int(round(y)):07d}"


def analysis_cell_id(ix: int, iy: int) -> str:
    return f"A_E{ix:04d}_N{iy:04d}"


def resource_estimate(requests: int, tile_pixels: int, counted_input_bands: int) -> float:
    return requests * (tile_pixels / 512.0) ** 2 * counted_input_bands / 3.0


def git_lineage_check(cfg: dict[str, Any]) -> tuple[str, str, str]:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != cfg["feature_branch"]:
        raise RuntimeError(f"Expected branch {cfg['feature_branch']}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree is not clean")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    freeze = cfg["split_fusion_freeze"]
    if subprocess.run(["git", "merge-base", "--is-ancestor", freeze["commit"], head], cwd=ROOT).returncode:
        raise RuntimeError("Split-fusion freeze commit is not an ancestor of HEAD")
    tag_commit = subprocess.check_output(["git", "rev-list", "-n", "1", freeze["tag"]], cwd=ROOT, text=True).strip()
    if tag_commit != freeze["commit"]:
        raise RuntimeError(f"Freeze tag resolves to {tag_commit}, expected {freeze['commit']}")
    return branch, head, tag_commit


def validate_contract(cfg: dict[str, Any], master: dict[str, Any], freeze: dict[str, Any]) -> None:
    if cfg["schema_version"] != "akerpuls-full-skane-d0-plan-v1":
        raise RuntimeError("D0 schema version changed")
    if any(bool(v) for v in cfg["guards"].values()):
        raise RuntimeError("D0 guard unexpectedly enables forbidden scope")
    if cfg["frozen_snapshots"] != master["snapshots"]:
        raise RuntimeError("Frozen snapshot dates differ from master contract")
    if cfg["frozen_geometry_2025"]["expected_fields"] != master["upstream_freeze"]["expected_2025_fields"]:
        raise RuntimeError("Frozen field count differs from master contract")
    if cfg["frozen_geometry_2025"]["expected_sha256"] != master["upstream_freeze"]["expected_2025_geometry_sha256"]:
        raise RuntimeError("Frozen geometry SHA differs from master contract")
    f = cfg["split_fusion_freeze"]
    if freeze["status"] != "FROZEN_QA_RANKING_NOT_AUTOMATIC_GEOMETRY":
        raise RuntimeError("Split-fusion freeze status changed")
    if abs(float(freeze["fusion"]["development_p90"]) - float(f["development_p90"])) > 1e-12:
        raise RuntimeError("P90 mismatch")
    if abs(float(freeze["fusion"]["development_p95"]) - float(f["development_p95"])) > 1e-12:
        raise RuntimeError("P95 mismatch")
    if freeze["fusion"]["source_freeze_sha256"] != f["fusion_artifact_sha256"]:
        raise RuntimeError("Fusion artifact SHA mismatch in formal freeze")
    pol = freeze["policy"]
    if pol["automatic_split"] or pol["automatic_merge"] or pol["automatic_geometry_replacement"]:
        raise RuntimeError("Automatic geometry mutation is unexpectedly enabled")
    src = cfg["sentinel_source"]
    if src["source_bands"] != ["B02", "B03", "B04", "B08", "B11", "SCL", "CLD", "dataMask"]:
        raise RuntimeError("Source band contract changed")
    if src["clear_scl_codes"] != [2, 4, 5]:
        raise RuntimeError("Clear SCL contract changed")
    if src["processing_upsampling"] != "NEAREST" or src["processing_downsampling"] != "NEAREST":
        raise RuntimeError("B1 nearest-neighbor preprocessing contract changed")
    if not src["never_average_paired_dates"]:
        raise RuntimeError("Paired-date averaging unexpectedly enabled")
    if cfg["analysis_partition"]["grid_size_m"] != 20000:
        raise RuntimeError("20 km local normalization partition changed")


def main() -> int:
    import geopandas as gpd
    import numpy as np
    import pandas as pd
    from shapely.geometry import shape, box
    from shapely.ops import unary_union

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CFG))
    ap.add_argument("--local-paths", default=str(ROOT / "config" / "local_paths.json"))
    ap.add_argument("--output-dir")
    args = ap.parse_args()

    cfg = read_json(Path(args.config))
    master = read_json(MASTER)
    freeze = read_json(FREEZE_CFG)
    validate_contract(cfg, master, freeze)
    branch, head, tag_commit = git_lineage_check(cfg)

    fusion_artifact = Path(cfg["split_fusion_freeze"]["fusion_artifact"])
    if not fusion_artifact.is_file():
        raise FileNotFoundError(fusion_artifact)
    fusion_hash = sha256_file(fusion_artifact)
    if fusion_hash != cfg["split_fusion_freeze"]["fusion_artifact_sha256"]:
        raise RuntimeError(f"Frozen fusion artifact changed: {fusion_hash}")

    local_paths = read_json(Path(args.local_paths))
    geom_path = Path(local_paths[cfg["frozen_geometry_2025"]["local_paths_key"]])
    if not geom_path.is_file():
        raise FileNotFoundError(geom_path)
    geom_hash = sha256_file(geom_path)
    if geom_hash != cfg["frozen_geometry_2025"]["expected_sha256"]:
        raise RuntimeError("Frozen 2025 geometry SHA256 mismatch")

    g0 = gpd.read_file(geom_path)
    if len(g0) != int(cfg["frozen_geometry_2025"]["expected_fields"]):
        raise RuntimeError(f"Expected {cfg['frozen_geometry_2025']['expected_fields']} fields, got {len(g0)}")
    if g0.crs is None:
        raise RuntimeError("Frozen 2025 geometry has no CRS")
    ids, id_basis = infer_ids(g0)
    g0 = g0.copy()
    g0["parent_field_id_2025"] = ids
    duplicate_ids = int(g0["parent_field_id_2025"].duplicated().sum())
    if duplicate_ids:
        raise RuntimeError(f"Frozen 2025 field IDs are not unique: duplicates={duplicate_ids}")
    valid_mask = g0.geometry.notna() & ~g0.geometry.is_empty & g0.geometry.is_valid
    invalid_geometry = int((~valid_mask).sum())
    if invalid_geometry:
        raise RuntimeError(f"Frozen 2025 geometry contains {invalid_geometry} null/empty/invalid rows; D0 will not silently drop them")
    g = g0.to_crs(32633).reset_index(drop=True)
    g["area_ha_2025"] = g.geometry.area / 10000.0

    out = Path(args.output_dir or cfg["paths"]["output_dir"])
    out.mkdir(parents=True, exist_ok=True)

    # Rebuild exact A0 raster tile topology from the frozen field union.
    fu = g.geometry.union_all() if hasattr(g.geometry, "union_all") else g.geometry.unary_union
    field_union_area_ha = float(fu.area / 10000.0)
    rt = cfg["raster_tiling"]
    tile_pixels = int(rt["tile_pixels"])
    res = int(cfg["sentinel_source"]["resolution_m"])
    side = tile_pixels * res
    if side != int(rt["tile_side_m"]):
        raise RuntimeError("Raster tile side contract inconsistent")
    buffered = fu.buffer(float(rt["field_buffer_m"]))
    minx, miny, maxx, maxy = buffered.bounds
    xs = range(math.floor(minx / side) * side, math.ceil(maxx / side) * side, side)
    ys = range(math.floor(miny / side) * side, math.ceil(maxy / side) * side, side)
    tile_rows: list[dict[str, Any]] = []
    tile_geoms = []
    for y in ys:
        for x in xs:
            q = box(x, y, x + side, y + side)
            if q.intersects(buffered):
                tile_rows.append({
                    "tile_id": raster_tile_id(x, y),
                    "minx": float(x), "miny": float(y), "maxx": float(x + side), "maxy": float(y + side),
                    "width": tile_pixels, "height": tile_pixels, "resolution_m": res,
                })
                tile_geoms.append(q)
    tile_gdf = gpd.GeoDataFrame(tile_rows, geometry=tile_geoms, crs=32633)
    tile_gdf.to_file(out / "d0_raster_tiles.gpkg", layer="raster_tiles", driver="GPKG")
    write_csv(out / "d0_raster_tiles.csv", tile_rows)

    # Public STAC only: inventory scene footprints and build one exact Process request row
    # for each daily tile that can contain source pixels.
    bbox4326 = [float(x) for x in g.to_crs(4326).total_bounds]
    scene_rows: list[dict[str, Any]] = []
    daily_union_32633: dict[str, Any] = {}
    snapshot_union_32633: dict[str, Any] = {}
    coverage_rows: list[dict[str, Any]] = []
    src = cfg["sentinel_source"]
    for snapshot, days in cfg["frozen_snapshots"].items():
        snap_geoms = []
        for day in days:
            items = stac_search(src["stac_search_url"], src["collection"], bbox4326, day)
            geoms4326 = [shape(item["geometry"]) for item in items if item.get("geometry")]
            if not geoms4326:
                raise RuntimeError(f"No STAC footprint for frozen date {day}")
            u4326 = unary_union(geoms4326)
            u32633 = gpd.GeoSeries([u4326], crs=4326).to_crs(32633).iloc[0]
            daily_union_32633[day] = u32633
            snap_geoms.append(u32633)
            for item in items:
                p = item.get("properties", {})
                scene_rows.append({
                    "snapshot": snapshot,
                    "date": day,
                    "item_id": item.get("id", ""),
                    "datetime": p.get("datetime", ""),
                    "eo_cloud_cover": p.get("eo:cloud_cover", ""),
                })
        su = unary_union(snap_geoms)
        snapshot_union_32633[snapshot] = su
        cov = float(fu.intersection(su).area / fu.area)
        coverage_rows.append({
            "snapshot": snapshot,
            "dates": "+".join(days),
            "field_union_coverage_percent": round(100.0 * cov, 4),
        })
    write_csv(out / "d0_scene_inventory.csv", scene_rows)
    write_csv(out / "d0_snapshot_coverage.csv", coverage_rows)

    request_rows: list[dict[str, Any]] = []
    requests_by_date: dict[str, int] = {}
    requests_by_snapshot: dict[str, int] = {}
    for snapshot, days in cfg["frozen_snapshots"].items():
        requests_by_snapshot[snapshot] = 0
        for day in days:
            nday = 0
            u = daily_union_32633[day]
            for row, q in zip(tile_rows, tile_geoms):
                if not q.intersects(u):
                    continue
                request_rows.append({
                    "snapshot": snapshot,
                    "date": day,
                    "tile_id": row["tile_id"],
                    "minx": row["minx"], "miny": row["miny"], "maxx": row["maxx"], "maxy": row["maxy"],
                    "width": tile_pixels, "height": tile_pixels,
                    "source_bands": ",".join(src["source_bands"]),
                    "upsampling": src["processing_upsampling"],
                    "downsampling": src["processing_downsampling"],
                    "harmonize_values": bool(src["harmonize_values"]),
                    "daily_output_relative": cfg["paths"]["daily_source_template"].format(date=day, tile_id=row["tile_id"]),
                })
                nday += 1
            requests_by_date[day] = nday
            requests_by_snapshot[snapshot] += nday
    request_rows = sorted(request_rows, key=lambda r: (r["date"], r["tile_id"]))
    req_path = out / "d0_process_request_plan.csv"
    write_csv(req_path, request_rows)
    request_plan_sha = sha256_file(req_path)

    # Every raster tile gets one four-snapshot output set. A tile/snapshot can have zero,
    # one or two daily source requests; missing source regions remain VALID=0.
    snapshot_tile_rows: list[dict[str, Any]] = []
    req_lookup = {(r["snapshot"], r["tile_id"]): 0 for r in request_rows}
    for r in request_rows:
        req_lookup[(r["snapshot"], r["tile_id"])] = req_lookup.get((r["snapshot"], r["tile_id"]), 0) + 1
    for tile in tile_rows:
        for snapshot, days in cfg["frozen_snapshots"].items():
            nsrc = int(req_lookup.get((snapshot, tile["tile_id"]), 0))
            snapshot_tile_rows.append({
                "snapshot": snapshot,
                "tile_id": tile["tile_id"],
                "source_request_count": nsrc,
                "frozen_dates": "+".join(days),
                "snapshot_output_relative": cfg["paths"]["snapshot_tile_template"].format(snapshot=snapshot.lower(), tile_id=tile["tile_id"]),
                "missing_source_policy": "WRITE_VALID_0_WHERE_NO_FROZEN_DATE_SOURCE_PIXEL",
            })
    write_csv(out / "d0_snapshot_tile_plan.csv", snapshot_tile_rows)

    # Deterministic 20 km analysis partition. Owner assignment is unique by representative
    # point; the normalization pool mirrors holdout selection more closely by including all
    # fields intersecting the owner's 20 km cell.
    part = cfg["analysis_partition"]
    grid = float(part["grid_size_m"])
    reps = g.geometry.representative_point()
    owner_ix = np.floor(reps.x.to_numpy() / grid).astype(int)
    owner_iy = np.floor(reps.y.to_numpy() / grid).astype(int)
    owner_ids = [analysis_cell_id(int(ix), int(iy)) for ix, iy in zip(owner_ix, owner_iy)]
    home_tile_x = np.floor(reps.x.to_numpy() / side).astype(int) * side
    home_tile_y = np.floor(reps.y.to_numpy() / side).astype(int) * side
    home_tile_ids = [raster_tile_id(float(x), float(y)) for x, y in zip(home_tile_x, home_tile_y)]
    known_tiles = {r["tile_id"] for r in tile_rows}
    if any(t not in known_tiles for t in home_tile_ids):
        bad = sorted({t for t in home_tile_ids if t not in known_tiles})[:10]
        raise RuntimeError(f"Field owner raster tile missing from raster tile plan: {bad}")

    field_partition = pd.DataFrame({
        "parent_field_id_2025": g["parent_field_id_2025"].astype(str),
        "analysis_cell_id": owner_ids,
        "home_raster_tile_id": home_tile_ids,
        "area_ha_2025": g["area_ha_2025"].round(6),
    })
    field_partition.to_csv(out / "d0_field_partition.csv", index=False, encoding="utf-8-sig")
    field_partition_sha = sha256_file(out / "d0_field_partition.csv")

    unique_cells = sorted(set(owner_ids))
    sidx = g.sindex
    cell_rows: list[dict[str, Any]] = []
    cell_geoms = []
    sparse_cells = 0
    min_norm = int(part["minimum_normalization_fields"])
    for cid in unique_cells:
        # Parse indices from the deterministic ID instead of relying on row order.
        p = cid.replace("A_E", "").split("_N")
        ix, iy = int(p[0]), int(p[1])
        cell = box(ix * grid, iy * grid, (ix + 1) * grid, (iy + 1) * grid)
        owner_n = int(sum(1 for x in owner_ids if x == cid))
        pos = list(sidx.query(cell, predicate="intersects"))
        norm_n = int(len(pos))
        norm_area = float(g.iloc[pos]["area_ha_2025"].sum()) if pos else 0.0
        status = "PASS" if norm_n >= min_norm else "REVIEW_SPARSE_NORMALIZATION_CELL"
        sparse_cells += int(status != "PASS")
        cell_rows.append({
            "analysis_cell_id": cid,
            "ix": ix,
            "iy": iy,
            "owner_fields": owner_n,
            "normalization_fields_intersecting_cell": norm_n,
            "normalization_area_ha": round(norm_area, 3),
            "normalization_status": status,
        })
        cell_geoms.append(cell)
    cell_df = pd.DataFrame(cell_rows).sort_values("analysis_cell_id").reset_index(drop=True)
    cell_df.to_csv(out / "d0_analysis_cells.csv", index=False, encoding="utf-8-sig")
    gpd.GeoDataFrame(cell_df.copy(), geometry=cell_geoms, crs=32633).to_file(
        out / "d0_analysis_cells.gpkg", layer="analysis_cells", driver="GPKG"
    )

    # Resource estimate and continuity check against the earlier A0 planning run.
    guard = cfg["resource_guard"]
    requests = len(request_rows)
    pu_upper = float(resource_estimate(requests, tile_pixels, int(guard["counted_input_bands_for_planning"])))
    a0 = cfg["a0_reference"]
    a0_manifest_path = Path(a0["manifest"])
    if not a0_manifest_path.is_file():
        raise FileNotFoundError(a0_manifest_path)
    a0_manifest = read_json(a0_manifest_path)
    a0_match = (
        int(a0_manifest["tile_plan"]["tiles"]) == int(a0["expected_tiles"]) == len(tile_rows)
        and int(a0_manifest["resource_estimate"]["requests"]) == int(a0["expected_planned_requests"]) == requests
        and abs(float(a0_manifest["resource_estimate"]["estimated_pu_upper"]) - float(a0["expected_estimated_pu_upper"])) <= float(a0["pu_tolerance"])
        and abs(pu_upper - float(a0["expected_estimated_pu_upper"])) <= float(a0["pu_tolerance"])
    )
    resource_guard_pass = (
        requests <= int(guard["maximum_planned_process_requests"])
        and pu_upper <= float(guard["maximum_estimated_pu_upper"])
    )

    # Theoretical uncompressed sizes are deliberately pessimistic planning upper bounds.
    raw_bytes = requests * tile_pixels * tile_pixels * len(src["source_bands"]) * 4
    snapshot_bytes = len(tile_rows) * len(cfg["frozen_snapshots"]) * tile_pixels * tile_pixels * len(rt["snapshot_bands"]) * 4

    repo_hashes = {
        "formal_split_fusion_config_sha256": sha256_file(FREEZE_CFG),
        "b2_config_sha256": sha256_file(B2_CFG),
        "true_loo_config_sha256": sha256_file(TRUE_LOO_CFG),
    }

    execution_contract = {
        "schema_version": "akerpuls-full-skane-d1-execution-contract-v1",
        "status": "FROZEN_FOR_D1_EXECUTION_NOT_AUTOMATIC_GEOMETRY",
        "split_fusion_freeze_tag": cfg["split_fusion_freeze"]["tag"],
        "split_fusion_freeze_commit": tag_commit,
        "fusion_artifact_sha256": fusion_hash,
        "repo_contract_hashes": repo_hashes,
        "geometry": {
            "sha256": geom_hash,
            "fields": int(len(g)),
            "id_basis": id_basis,
            "field_union_area_ha": round(field_union_area_ha, 3),
        },
        "snapshots": cfg["frozen_snapshots"],
        "sentinel_source": cfg["sentinel_source"],
        "raster_tiling": cfg["raster_tiling"],
        "analysis_partition": cfg["analysis_partition"],
        "model_application": cfg["model_application"],
        "request_plan": {
            "path": str(req_path),
            "sha256": request_plan_sha,
            "rows": requests,
            "requests_by_date": requests_by_date,
            "requests_by_snapshot": requests_by_snapshot,
            "estimated_pu_upper": round(pu_upper, 6),
        },
        "field_partition": {
            "path": str(out / "d0_field_partition.csv"),
            "sha256": field_partition_sha,
            "rows": int(len(field_partition)),
            "analysis_cells": int(len(cell_df)),
            "sparse_normalization_cells": int(sparse_cells),
        },
        "paths": cfg["paths"],
        "policy": {
            "automatic_split": False,
            "automatic_merge": False,
            "automatic_geometry_replacement": False,
            "product_use": "QA_RANKING_AND_REVIEW_PRIORITY_ONLY",
        },
    }
    contract_bytes = stable_json_bytes(execution_contract)
    contract_path = out / "D1_EXECUTION_CONTRACT.json"
    contract_path.write_bytes(contract_bytes)
    contract_sha = sha256_bytes(contract_bytes)

    status = "PASS"
    reasons: list[str] = []
    if not a0_match:
        status = "REVIEW"
        reasons.append("FRESH_STAC_REQUEST_PLAN_DIFFERS_FROM_FROZEN_A0_REFERENCE")
    if not resource_guard_pass:
        status = "REVIEW"
        reasons.append("RESOURCE_GUARD_FAILED")
    if sparse_cells:
        status = "REVIEW"
        reasons.append("SPARSE_20KM_NORMALIZATION_CELLS_EXIST")

    cell_owner = cell_df["owner_fields"]
    cell_norm = cell_df["normalization_fields_intersecting_cell"]
    manifest = {
        "schema_version": cfg["schema_version"],
        "status": status,
        "review_reasons": reasons,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git": {"branch": branch, "head": head, "freeze_tag": cfg["split_fusion_freeze"]["tag"], "freeze_commit": tag_commit},
        "frozen_geometry": {"path": str(geom_path), "sha256": geom_hash, "fields": int(len(g)), "id_basis": id_basis, "field_union_area_ha": round(field_union_area_ha, 3)},
        "raster_tiles": int(len(tile_rows)),
        "snapshot_tiles": int(len(snapshot_tile_rows)),
        "planned_process_requests": requests,
        "requests_by_date": requests_by_date,
        "requests_by_snapshot": requests_by_snapshot,
        "estimated_pu_upper": round(pu_upper, 6),
        "a0_reference_match": bool(a0_match),
        "resource_guard_pass": bool(resource_guard_pass),
        "snapshot_coverage": coverage_rows,
        "analysis_partition": {
            "cells": int(len(cell_df)),
            "sparse_cells": int(sparse_cells),
            "owner_fields_min": int(cell_owner.min()),
            "owner_fields_p10": round(float(cell_owner.quantile(0.1)), 1),
            "owner_fields_p50": round(float(cell_owner.median()), 1),
            "owner_fields_max": int(cell_owner.max()),
            "normalization_fields_min": int(cell_norm.min()),
            "normalization_fields_p10": round(float(cell_norm.quantile(0.1)), 1),
            "normalization_fields_p50": round(float(cell_norm.median()), 1),
            "normalization_fields_max": int(cell_norm.max()),
            "minimum_required": min_norm,
        },
        "storage_upper_bounds": {
            "daily_source_uncompressed_gib": round(raw_bytes / (1024 ** 3), 2),
            "snapshot_tiles_uncompressed_gib": round(snapshot_bytes / (1024 ** 3), 2),
            "combined_uncompressed_gib": round((raw_bytes + snapshot_bytes) / (1024 ** 3), 2),
            "note": "Actual DEFLATE GeoTIFF storage should be lower; these are not quota estimates.",
        },
        "d1_execution_contract_sha256": contract_sha,
        "sentinel_hub_pu_used": 0,
        "process_api_called": False,
        "thresholds_tuned": False,
        "fusion_refit": False,
        "automatic_geometry_replacement": False,
    }
    (out / "d0_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    qa = [
        "# ÅkerPuls full-Skåne — STOPPUNKT D0",
        "",
        f"- Status: **{status}**",
        f"- Frozen 2025 fields: {len(g):,}",
        f"- Raster tiles: {len(tile_rows)}",
        f"- Planned Process API requests for D1: {requests}",
        f"- Estimated PU upper: {pu_upper:.2f}",
        f"- A0 continuity: {'PASS' if a0_match else 'REVIEW'}",
        f"- 20 km analysis cells: {len(cell_df)}; sparse normalization cells: {sparse_cells}",
        f"- D1 execution-contract SHA256: `{contract_sha}`",
        "",
        "D0 itself used public STAC only and zero Sentinel Hub PU.",
        "No thresholds were changed, the fusion was not refit, and 2025 geometry remains the default.",
    ]
    if reasons:
        qa += ["", "## Review reasons"] + [f"- {r}" for r in reasons]
    (out / "d0_qa.md").write_text("\n".join(qa) + "\n", encoding="utf-8")

    print("AKERPULS FULL SKANE D0 - ZERO PU EXECUTION PLAN")
    print(f"STATUS={status}")
    print(f"FIELDS_2025={len(g)} FIELD_UNION_AREA_HA={field_union_area_ha:.3f}")
    print(f"SPLIT_FUSION_FREEZE_TAG={cfg['split_fusion_freeze']['tag']} COMMIT={tag_commit}")
    print(f"FUSION_FREEZE_SHA256={fusion_hash}")
    print(f"RASTER_TILES={len(tile_rows)} SNAPSHOT_TILES={len(snapshot_tile_rows)}")
    print(f"PLANNED_PROCESS_REQUESTS={requests}")
    for day in sorted(requests_by_date):
        print(f"REQUESTS_{day}={requests_by_date[day]}")
    print(f"ESTIMATED_PU_UPPER={pu_upper:.2f}")
    print(f"A0_REFERENCE_MATCH={'PASS' if a0_match else 'REVIEW'}")
    print(f"RESOURCE_GUARD={'PASS' if resource_guard_pass else 'REVIEW'}")
    print(f"ANALYSIS_CELLS={len(cell_df)} SPARSE_NORMALIZATION_CELLS={sparse_cells} MIN_NORM_FIELDS={int(cell_norm.min())} P10_NORM_FIELDS={float(cell_norm.quantile(.1)):.1f} MEDIAN_NORM_FIELDS={float(cell_norm.median()):.1f}")
    print(f"UNCOMPRESSED_DAILY_GIB={raw_bytes/(1024**3):.2f} SNAPSHOT_GIB={snapshot_bytes/(1024**3):.2f} COMBINED_GIB={(raw_bytes+snapshot_bytes)/(1024**3):.2f}")
    print(f"D1_EXECUTION_CONTRACT_SHA256={contract_sha}")
    print("NORMALIZATION_CONTRACT=LOCAL_20KM_INTERSECTING_FIELDS")
    print("WHOLE_SKANE_IN_MEMORY=FALSE")
    print("AUTOMATIC_SPLIT=FALSE")
    print("AUTOMATIC_MERGE=FALSE")
    print("AUTOMATIC_GEOMETRY_REPLACEMENT=FALSE")
    print("PROCESS_API_CALLED=FALSE")
    print("SENTINEL_HUB_PU_USED=0")
    print("THRESHOLDS_TUNED=FALSE")
    print("FUSION_REFIT=FALSE")
    print(f"D0_STATUS={status}")
    print(f"OUTPUT={out}")
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
