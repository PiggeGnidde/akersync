#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerPuls full-Skåne D0 execution planner v1.

Public STAC only. No Sentinel Hub Process API calls and zero PU.

This version deliberately reuses the already frozen A0 tile topology instead of
rebuilding a unary union of all 128,636 field polygons. The frozen geometry hash,
field count and A0 manifest are re-verified first, so this is an execution-speed
optimization only; it does not change the scientific/model contract.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import urllib.request
from collections import Counter
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_full_skane_d0_plan_v1.json"
MASTER = ROOT / "config" / "akerpuls_prelim_fields_2026_v0.json"
FREEZE_CFG = ROOT / "config" / "akerpuls_split_fusion_qa_v1.json"
B2_CFG = ROOT / "config" / "akerpuls_prelim_fields_2026_b2.json"
TRUE_LOO_CFG = ROOT / "config" / "akerpuls_true_loo_diagnostic_v0.json"


def log(msg: str) -> None:
    print(msg, flush=True)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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

    log("D0_PROGRESS=LOAD_AND_VALIDATE_CONTRACT")
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

    log("D0_PROGRESS=READ_128636_FIELDS")
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

    log("D0_PROGRESS=REPROJECT_FIELDS_TO_EPSG32633")
    g = g0.to_crs(32633).reset_index(drop=True)
    g["area_ha_2025"] = g.geometry.area / 10000.0
    out = Path(args.output_dir or cfg["paths"]["output_dir"])
    out.mkdir(parents=True, exist_ok=True)

    # Reuse the exact A0 tile topology. Recomputing unary_union(128636 polygons) was
    # unnecessarily expensive and can take hours on some GEOS/Windows builds.
    log("D0_PROGRESS=VERIFY_AND_REUSE_FROZEN_A0_TILE_TOPOLOGY")
    a0 = cfg["a0_reference"]
    a0_manifest_path = Path(a0["manifest"])
    if not a0_manifest_path.is_file():
        raise FileNotFoundError(a0_manifest_path)
    a0_manifest = read_json(a0_manifest_path)
    a0_geom = a0_manifest.get("frozen_geometry", {})
    if a0_geom.get("sha256") != geom_hash or int(a0_geom.get("rows", -1)) != len(g):
        raise RuntimeError("A0 manifest is not tied to the same frozen 2025 geometry")
    a0_dir = a0_manifest_path.parent
    a0_tiles_path = a0_dir / "tile_plan.csv"
    a0_cov_path = a0_dir / "snapshot_coverage.csv"
    if not a0_tiles_path.is_file() or not a0_cov_path.is_file():
        raise FileNotFoundError("A0 tile_plan.csv or snapshot_coverage.csv missing")

    a0_tiles = pd.read_csv(a0_tiles_path, encoding="utf-8-sig")
    required_tile_cols = ["tile_id", "minx", "miny", "maxx", "maxy"]
    if any(c not in a0_tiles.columns for c in required_tile_cols):
        raise RuntimeError("A0 tile plan columns changed")
    if len(a0_tiles) != int(a0["expected_tiles"]):
        raise RuntimeError(f"A0 tile plan has {len(a0_tiles)} tiles, expected {a0['expected_tiles']}")
    rt = cfg["raster_tiling"]
    tile_pixels = int(rt["tile_pixels"])
    res = int(cfg["sentinel_source"]["resolution_m"])
    side = tile_pixels * res
    tile_rows: list[dict[str, Any]] = []
    tile_geoms = []
    for r in a0_tiles.to_dict("records"):
        minx, miny, maxx, maxy = map(float, (r["minx"], r["miny"], r["maxx"], r["maxy"]))
        if abs((maxx - minx) - side) > 1e-6 or abs((maxy - miny) - side) > 1e-6:
            raise RuntimeError(f"A0 tile {r['tile_id']} side changed")
        expected_id = raster_tile_id(minx, miny)
        if str(r["tile_id"]) != expected_id:
            raise RuntimeError(f"A0 tile ID mismatch: {r['tile_id']} vs {expected_id}")
        tile_rows.append({
            "tile_id": expected_id,
            "minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy,
            "width": tile_pixels, "height": tile_pixels, "resolution_m": res,
        })
        tile_geoms.append(box(minx, miny, maxx, maxy))
    write_csv(out / "d0_raster_tiles.csv", tile_rows)
    gpd.GeoDataFrame(tile_rows, geometry=tile_geoms, crs=32633).to_file(out / "d0_raster_tiles.gpkg", layer="raster_tiles", driver="GPKG")

    # A0 coverage is already the exact expensive union-based result for the same geometry
    # and frozen dates. Preserve it as provenance instead of repeating the unary union.
    a0_cov = pd.read_csv(a0_cov_path, encoding="utf-8-sig")
    a0_cov.to_csv(out / "d0_snapshot_coverage.csv", index=False, encoding="utf-8-sig")
    coverage_rows = a0_cov.to_dict("records")
    field_union_area_ha = float(a0_geom.get("field_union_area_ha", float(g["area_ha_2025"].sum())))

    log("D0_PROGRESS=QUERY_PUBLIC_STAC_6_FROZEN_DATES")
    bbox4326 = [float(x) for x in g0.to_crs(4326).total_bounds]
    scene_rows: list[dict[str, Any]] = []
    daily_union_32633: dict[str, Any] = {}
    src = cfg["sentinel_source"]
    for snapshot, days in cfg["frozen_snapshots"].items():
        for day in days:
            items = stac_search(src["stac_search_url"], src["collection"], bbox4326, day)
            geoms4326 = [shape(item["geometry"]) for item in items if item.get("geometry")]
            if not geoms4326:
                raise RuntimeError(f"No STAC footprint for frozen date {day}")
            u4326 = unary_union(geoms4326)
            daily_union_32633[day] = gpd.GeoSeries([u4326], crs=4326).to_crs(32633).iloc[0]
            for item in items:
                p = item.get("properties", {})
                scene_rows.append({
                    "snapshot": snapshot,
                    "date": day,
                    "item_id": item.get("id", ""),
                    "datetime": p.get("datetime", ""),
                    "eo_cloud_cover": p.get("eo:cloud_cover", ""),
                })
            log(f"D0_STAC_DATE={day} ITEMS={len(items)}")
    write_csv(out / "d0_scene_inventory.csv", scene_rows)

    log("D0_PROGRESS=BUILD_593_REQUEST_PLAN")
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
    request_rows.sort(key=lambda r: (r["date"], r["tile_id"]))
    req_path = out / "d0_process_request_plan.csv"
    write_csv(req_path, request_rows)
    request_plan_sha = sha256_file(req_path)

    snapshot_tile_rows: list[dict[str, Any]] = []
    req_lookup: Counter[tuple[str, str]] = Counter((r["snapshot"], r["tile_id"]) for r in request_rows)
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

    log("D0_PROGRESS=BUILD_20KM_ANALYSIS_PARTITION")
    part = cfg["analysis_partition"]
    grid = float(part["grid_size_m"])
    reps = g.geometry.representative_point()
    owner_ix = np.floor(reps.x.to_numpy() / grid).astype(int)
    owner_iy = np.floor(reps.y.to_numpy() / grid).astype(int)
    owner_ids = [analysis_cell_id(int(ix), int(iy)) for ix, iy in zip(owner_ix, owner_iy)]
    owner_counts = Counter(owner_ids)
    home_tile_x = np.floor(reps.x.to_numpy() / side).astype(int) * side
    home_tile_y = np.floor(reps.y.to_numpy() / side).astype(int) * side
    home_tile_ids = [raster_tile_id(float(x), float(y)) for x, y in zip(home_tile_x, home_tile_y)]
    known_tiles = {r["tile_id"] for r in tile_rows}
    bad_tiles = sorted({t for t in home_tile_ids if t not in known_tiles})
    if bad_tiles:
        raise RuntimeError(f"Field owner raster tile missing from raster plan: {bad_tiles[:10]}")

    field_partition = pd.DataFrame({
        "parent_field_id_2025": g["parent_field_id_2025"].astype(str),
        "analysis_cell_id": owner_ids,
        "home_raster_tile_id": home_tile_ids,
        "area_ha_2025": g["area_ha_2025"].round(6),
    })
    field_partition_path = out / "d0_field_partition.csv"
    field_partition.to_csv(field_partition_path, index=False, encoding="utf-8-sig")
    field_partition_sha = sha256_file(field_partition_path)

    unique_cells = sorted(owner_counts)
    sidx = g.sindex
    min_norm = int(part["minimum_normalization_fields"])
    cell_records: list[dict[str, Any]] = []
    sparse_cells = 0
    for k, cid in enumerate(unique_cells, 1):
        p = cid.replace("A_E", "").split("_N")
        ix, iy = int(p[0]), int(p[1])
        cell = box(ix * grid, iy * grid, (ix + 1) * grid, (iy + 1) * grid)
        pos = list(sidx.query(cell, predicate="intersects"))
        norm_n = len(pos)
        norm_area = float(g.iloc[pos]["area_ha_2025"].sum()) if pos else 0.0
        status = "PASS" if norm_n >= min_norm else "REVIEW_SPARSE_NORMALIZATION_CELL"
        sparse_cells += int(status != "PASS")
        cell_records.append({
            "analysis_cell_id": cid,
            "ix": ix,
            "iy": iy,
            "owner_fields": int(owner_counts[cid]),
            "normalization_fields_intersecting_cell": int(norm_n),
            "normalization_area_ha": round(norm_area, 3),
            "normalization_status": status,
            "geometry": cell,
        })
        if k % 10 == 0 or k == len(unique_cells):
            log(f"D0_ANALYSIS_CELL_PROGRESS={k}/{len(unique_cells)}")

    cells_gdf = gpd.GeoDataFrame(cell_records, geometry="geometry", crs=32633).sort_values("analysis_cell_id").reset_index(drop=True)
    cells_gdf.drop(columns="geometry").to_csv(out / "d0_analysis_cells.csv", index=False, encoding="utf-8-sig")
    cells_gdf.to_file(out / "d0_analysis_cells.gpkg", layer="analysis_cells", driver="GPKG")
    analysis_cells_sha = sha256_file(out / "d0_analysis_cells.csv")

    log("D0_PROGRESS=VERIFY_A0_RESOURCE_CONTINUITY")
    guard = cfg["resource_guard"]
    requests = len(request_rows)
    pu_upper = float(resource_estimate(requests, tile_pixels, int(guard["counted_input_bands_for_planning"])))
    a0_match = (
        int(a0_manifest["tile_plan"]["tiles"]) == int(a0["expected_tiles"]) == len(tile_rows)
        and int(a0_manifest["resource_estimate"]["requests"]) == int(a0["expected_planned_requests"]) == requests
        and abs(float(a0_manifest["resource_estimate"]["estimated_pu_upper"]) - float(a0["expected_estimated_pu_upper"])) <= float(a0["pu_tolerance"])
        and abs(pu_upper - float(a0["expected_estimated_pu_upper"])) <= float(a0["pu_tolerance"])
    )
    resource_guard_pass = requests <= int(guard["maximum_planned_process_requests"]) and pu_upper <= float(guard["maximum_estimated_pu_upper"])

    repo_hashes = {
        "formal_split_fusion_config_sha256": sha256_file(FREEZE_CFG),
        "b2_config_sha256": sha256_file(B2_CFG),
        "true_loo_config_sha256": sha256_file(TRUE_LOO_CFG),
    }
    execution_contract = {
        "schema_version": "akerpuls-full-skane-d1-execution-contract-v1",
        "source_d0_schema": cfg["schema_version"],
        "split_fusion_freeze": {
            "tag": cfg["split_fusion_freeze"]["tag"],
            "commit": cfg["split_fusion_freeze"]["commit"],
            "fusion_artifact_sha256": fusion_hash,
            "development_p90": cfg["split_fusion_freeze"]["development_p90"],
            "development_p95": cfg["split_fusion_freeze"]["development_p95"],
        },
        "frozen_geometry": {"sha256": geom_hash, "fields": len(g)},
        "frozen_snapshots": cfg["frozen_snapshots"],
        "sentinel_source": cfg["sentinel_source"],
        "raster_tiling": cfg["raster_tiling"],
        "analysis_partition": cfg["analysis_partition"],
        "model_application": cfg["model_application"],
        "request_plan": {"rows": requests, "sha256": request_plan_sha},
        "field_partition": {"rows": len(field_partition), "sha256": field_partition_sha},
        "analysis_cells": {"rows": len(cells_gdf), "sha256": analysis_cells_sha},
        "automatic_split": False,
        "automatic_merge": False,
        "automatic_geometry_replacement": False,
        "repo_hashes": repo_hashes,
    }
    contract_path = out / "D1_EXECUTION_CONTRACT.json"
    contract_path.write_bytes(stable_json_bytes(execution_contract))
    contract_sha = sha256_file(contract_path)

    status = "PASS" if a0_match and resource_guard_pass and sparse_cells == 0 else "REVIEW"
    manifest = {
        "schema_version": "akerpuls-full-skane-d0-result-v1",
        "status": status,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git": {"branch": branch, "head": head, "freeze_tag_commit": tag_commit},
        "geometry": {"path": str(geom_path), "sha256": geom_hash, "fields": len(g), "id_basis": id_basis, "field_union_area_ha_from_a0": field_union_area_ha},
        "a0_topology_reused": True,
        "a0_manifest": str(a0_manifest_path),
        "raster_tiles": len(tile_rows),
        "snapshot_tiles": len(snapshot_tile_rows),
        "planned_process_requests": requests,
        "requests_by_date": requests_by_date,
        "requests_by_snapshot": requests_by_snapshot,
        "estimated_pu_upper": round(pu_upper, 6),
        "a0_reference_match": bool(a0_match),
        "resource_guard": bool(resource_guard_pass),
        "analysis_cells": len(cells_gdf),
        "sparse_normalization_cells": int(sparse_cells),
        "minimum_normalization_fields": min_norm,
        "fusion_freeze_sha256": fusion_hash,
        "d1_execution_contract_sha256": contract_sha,
        "sentinel_hub_pu_used": 0,
        "automatic_geometry_replacement": False,
    }
    (out / "d0_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    qa = [
        "# ÅkerPuls full Skåne D0 plan v1",
        f"- Status: **{status}**",
        f"- Fields: {len(g):,}",
        f"- Raster tiles: {len(tile_rows)}",
        f"- Planned Process requests: {requests}",
        f"- Estimated PU upper: {pu_upper:.2f}",
        f"- A0 reference match: **{'PASS' if a0_match else 'REVIEW'}**",
        f"- Resource guard: **{'PASS' if resource_guard_pass else 'REVIEW'}**",
        f"- Analysis cells: {len(cells_gdf)}",
        f"- Sparse normalization cells: {sparse_cells}",
        f"- D1 execution contract SHA256: `{contract_sha}`",
        "- Sentinel Hub PU used: **0**",
        "- Automatic geometry mutation: **FALSE**",
        "",
        "Performance note: exact A0 tile topology and union-based coverage were reused after geometry SHA/count verification; no 128,636-polygon unary union was recomputed.",
    ]
    (out / "d0_qa.md").write_text("\n".join(qa) + "\n", encoding="utf-8")

    print("AKERPULS FULL SKANE D0 ZERO-PU EXECUTION PLAN", flush=True)
    print(f"STATUS={status}")
    print(f"FIELDS={len(g)}")
    print(f"RASTER_TILES={len(tile_rows)}")
    print(f"SNAPSHOT_TILES={len(snapshot_tile_rows)}")
    print(f"PLANNED_PROCESS_REQUESTS={requests}")
    for day in sorted(requests_by_date):
        print(f"REQUESTS_{day}={requests_by_date[day]}")
    print(f"ESTIMATED_PU_UPPER={pu_upper:.2f}")
    print(f"A0_REFERENCE_MATCH={'PASS' if a0_match else 'REVIEW'}")
    print(f"RESOURCE_GUARD={'PASS' if resource_guard_pass else 'REVIEW'}")
    print(f"ANALYSIS_CELLS={len(cells_gdf)}")
    print(f"SPARSE_NORMALIZATION_CELLS={sparse_cells}")
    print(f"MIN_NORM_FIELDS={min_norm}")
    print(f"FUSION_FREEZE_SHA256={fusion_hash}")
    print(f"D1_EXECUTION_CONTRACT_SHA256={contract_sha}")
    print("A0_TILE_TOPOLOGY_REUSED=TRUE")
    print("AUTOMATIC_GEOMETRY_REPLACEMENT=FALSE")
    print("SENTINEL_HUB_PU_USED=0")
    print(f"D0_STATUS={status}")
    print("OUTPUT=" + str(out))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
