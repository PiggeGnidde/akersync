#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerPuls full-Skåne D0b: resolve sparse local-normalization edge cells.

Zero PU. No STAC and no Sentinel Hub Process API calls.

For the six D0 edge cells having fewer than 200 normalization fields in the
20x20 km owner cell, use the smallest predeclared symmetric square expansion
(10 km, then 20 km on each side) that reaches at least 200 intersecting 2025
fields. Dense D0 cells are left unchanged. No labels or model outputs are used.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_full_skane_d0b_sparse_norm_v1.json"


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


def parse_cell_id(cid: str) -> tuple[int, int]:
    p = cid.replace("A_E", "").split("_N")
    if len(p) != 2:
        raise ValueError(cid)
    return int(p[0]), int(p[1])


def window_bounds(ix: int, iy: int, grid_m: float, expansion_m: float) -> tuple[float, float, float, float]:
    return (
        ix * grid_m - expansion_m,
        iy * grid_m - expansion_m,
        (ix + 1) * grid_m + expansion_m,
        (iy + 1) * grid_m + expansion_m,
    )


def validate_config(cfg: dict[str, Any]) -> None:
    if cfg.get("schema_version") != "akerpuls-full-skane-d0b-sparse-norm-v1":
        raise RuntimeError("D0b schema changed")
    if any(bool(v) for v in cfg["guards"].values()):
        raise RuntimeError("D0b guard unexpectedly enables forbidden scope")
    fb = cfg["normalization_fallback"]
    if fb["base_grid_size_m"] != 20000:
        raise RuntimeError("Base grid must remain 20 km")
    if fb["minimum_normalization_fields"] != 200:
        raise RuntimeError("Minimum normalization fields must remain 200")
    if fb["expansion_steps_m"] != [10000, 20000]:
        raise RuntimeError("D0b expansion steps changed")
    if not fb["apply_only_when_base_cell_has_fewer_than_minimum"]:
        raise RuntimeError("Fallback must apply only to sparse cells")
    if not fb["no_label_use"] or not fb["no_parameter_tuning"]:
        raise RuntimeError("D0b must remain label-free and untuned")


def git_check(cfg: dict[str, Any]) -> tuple[str, str]:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != cfg["feature_branch"]:
        raise RuntimeError(f"Expected branch {cfg['feature_branch']}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree is not clean")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    return branch, head


def main() -> int:
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import box

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CFG))
    ap.add_argument("--local-paths", default=str(ROOT / "config" / "local_paths.json"))
    ap.add_argument("--output-dir")
    args = ap.parse_args()

    cfg = read_json(Path(args.config))
    validate_config(cfg)
    branch, head = git_check(cfg)

    base = cfg["base_d0"]
    d0dir = Path(base["output_dir"])
    base_contract_path = Path(base["execution_contract"])
    analysis_csv = d0dir / "d0_analysis_cells.csv"
    d0_manifest_path = d0dir / "d0_manifest.json"
    for p in (base_contract_path, analysis_csv, d0_manifest_path):
        if not p.is_file():
            raise FileNotFoundError(p)

    base_contract_sha = sha256_file(base_contract_path)
    if base_contract_sha != base["expected_execution_contract_sha256"]:
        raise RuntimeError(f"D0 execution contract SHA mismatch: {base_contract_sha}")
    base_contract = read_json(base_contract_path)
    d0_manifest = read_json(d0_manifest_path)
    if int(d0_manifest.get("analysis_cells", -1)) != int(base["expected_analysis_cells"]):
        raise RuntimeError("Unexpected D0 analysis-cell count")
    if int(d0_manifest.get("sparse_normalization_cells", -1)) != int(base["expected_sparse_cells"]):
        raise RuntimeError("Unexpected D0 sparse-cell count")
    if int(d0_manifest.get("planned_process_requests", -1)) != int(base["expected_planned_process_requests"]):
        raise RuntimeError("Unexpected D0 request count")
    if abs(float(d0_manifest.get("estimated_pu_upper", -1)) - float(base["expected_estimated_pu_upper"])) > 0.02:
        raise RuntimeError("Unexpected D0 PU estimate")

    cells = pd.read_csv(analysis_csv, encoding="utf-8-sig")
    if len(cells) != int(base["expected_analysis_cells"]):
        raise RuntimeError("D0 analysis CSV row count mismatch")
    min_fields = int(cfg["normalization_fallback"]["minimum_normalization_fields"])
    sparse_mask = cells["normalization_fields_intersecting_cell"].astype(int) < min_fields
    sparse = cells.loc[sparse_mask].copy()
    if len(sparse) != int(base["expected_sparse_cells"]):
        raise RuntimeError("D0 sparse rows differ from frozen D0b expectation")

    local_paths = read_json(Path(args.local_paths))
    geom_path = Path(local_paths[cfg["frozen_geometry_2025"]["local_paths_key"]])
    if not geom_path.is_file():
        raise FileNotFoundError(geom_path)
    geom_sha = sha256_file(geom_path)
    if geom_sha != cfg["frozen_geometry_2025"]["expected_sha256"]:
        raise RuntimeError("Frozen 2025 geometry SHA mismatch")

    print("D0B_PROGRESS=READ_128636_FIELDS", flush=True)
    g = gpd.read_file(geom_path)
    if len(g) != int(cfg["frozen_geometry_2025"]["expected_fields"]):
        raise RuntimeError("Frozen 2025 field count mismatch")
    if g.crs is None:
        raise RuntimeError("Frozen geometry missing CRS")
    valid = g.geometry.notna() & ~g.geometry.is_empty & g.geometry.is_valid
    if not bool(valid.all()):
        raise RuntimeError("Frozen geometry contains invalid/null rows")
    print("D0B_PROGRESS=REPROJECT_FIELDS_TO_EPSG32633", flush=True)
    g = g.to_crs(32633).reset_index(drop=True)
    g["area_ha_2025"] = g.geometry.area / 10000.0
    sidx = g.sindex

    fb = cfg["normalization_fallback"]
    grid = float(fb["base_grid_size_m"])
    steps = [int(x) for x in fb["expansion_steps_m"]]
    resolved_rows: list[dict[str, Any]] = []
    resolved_geoms = []
    unresolved = 0
    sparse_resolutions: list[dict[str, Any]] = []

    print(f"D0B_PROGRESS=RESOLVE_{len(cells)}_ANALYSIS_CELLS", flush=True)
    for _, row in cells.sort_values("analysis_cell_id").iterrows():
        cid = str(row["analysis_cell_id"])
        ix, iy = parse_cell_id(cid)
        owner_fields = int(row["owner_fields"])
        base_n = int(row["normalization_fields_intersecting_cell"])
        base_area = float(row["normalization_area_ha"])
        chosen_expansion = 0
        final_n = base_n
        final_area = base_area
        chosen_bounds = window_bounds(ix, iy, grid, 0)
        status = "PASS_BASE_20KM"

        if base_n < min_fields:
            status = "REVIEW_UNRESOLVED"
            for expansion in steps:
                bounds = window_bounds(ix, iy, grid, expansion)
                win = box(*bounds)
                pos = list(sidx.query(win, predicate="intersects"))
                n = int(len(pos))
                area = float(g.iloc[pos]["area_ha_2025"].sum()) if pos else 0.0
                if n >= min_fields:
                    chosen_expansion = int(expansion)
                    final_n = n
                    final_area = area
                    chosen_bounds = bounds
                    status = "PASS_EXPANDED_LOCAL_WINDOW"
                    break
            if status != "PASS_EXPANDED_LOCAL_WINDOW":
                # Record the largest predeclared window for diagnosis, but do not silently continue to D1.
                expansion = steps[-1]
                bounds = window_bounds(ix, iy, grid, expansion)
                win = box(*bounds)
                pos = list(sidx.query(win, predicate="intersects"))
                chosen_expansion = int(expansion)
                final_n = int(len(pos))
                final_area = float(g.iloc[pos]["area_ha_2025"].sum()) if pos else 0.0
                chosen_bounds = bounds
                unresolved += 1
            sparse_resolutions.append({
                "analysis_cell_id": cid,
                "base_fields": base_n,
                "expansion_m": chosen_expansion,
                "final_fields": final_n,
                "status": status,
            })
            print(
                f"D0B_SPARSE_CELL={cid} BASE_N={base_n} EXPANSION_M={chosen_expansion} FINAL_N={final_n} STATUS={status}",
                flush=True,
            )

        minx, miny, maxx, maxy = chosen_bounds
        resolved_rows.append({
            "analysis_cell_id": cid,
            "ix": ix,
            "iy": iy,
            "owner_fields": owner_fields,
            "base_normalization_fields": base_n,
            "base_normalization_area_ha": round(base_area, 3),
            "normalization_expansion_m": chosen_expansion,
            "normalization_window_side_m": int(grid + 2 * chosen_expansion),
            "resolved_normalization_fields": final_n,
            "resolved_normalization_area_ha": round(final_area, 3),
            "resolved_status": status,
            "minx": float(minx),
            "miny": float(miny),
            "maxx": float(maxx),
            "maxy": float(maxy),
        })
        resolved_geoms.append(box(minx, miny, maxx, maxy))

    out = Path(args.output_dir or cfg["paths"]["output_dir"])
    out.mkdir(parents=True, exist_ok=True)
    resolved_df = pd.DataFrame(resolved_rows).sort_values("analysis_cell_id").reset_index(drop=True)
    resolved_csv = out / "d0b_resolved_normalization_windows.csv"
    resolved_df.to_csv(resolved_csv, index=False, encoding="utf-8-sig")
    resolved_sha = sha256_file(resolved_csv)
    gpd.GeoDataFrame(resolved_df.copy(), geometry=resolved_geoms, crs=32633).to_file(
        out / "d0b_resolved_normalization_windows.gpkg",
        layer="normalization_windows",
        driver="GPKG",
    )

    sparse_df = resolved_df[resolved_df["base_normalization_fields"] < min_fields].copy()
    sparse_df.to_csv(out / "d0b_sparse_cell_resolution.csv", index=False, encoding="utf-8-sig")

    dense_changed = int(((resolved_df["base_normalization_fields"] >= min_fields) & (resolved_df["normalization_expansion_m"] != 0)).sum())
    if dense_changed:
        raise RuntimeError("D0b changed one or more non-sparse normalization cells")

    final_contract = copy.deepcopy(base_contract)
    final_contract["schema_version"] = "akerpuls-full-skane-d1-execution-contract-v1-d0b"
    final_contract["source_d0b_schema"] = cfg["schema_version"]
    final_contract["base_d0_execution_contract_sha256"] = base_contract_sha
    final_contract["analysis_partition"]["sparse_normalization_fallback"] = {
        "minimum_normalization_fields": min_fields,
        "rule": fb["selection_rule"],
        "window_shape": fb["window_shape"],
        "expansion_steps_m": steps,
        "maximum_expansion_m": int(fb["maximum_expansion_m"]),
        "apply_only_to_sparse_cells": True,
        "no_labels_used": True,
        "no_parameter_tuning": True,
    }
    final_contract["resolved_normalization_windows"] = {
        "rows": len(resolved_df),
        "sha256": resolved_sha,
        "sparse_cells": len(sparse_df),
        "unresolved_cells": unresolved,
    }
    final_contract["automatic_split"] = False
    final_contract["automatic_merge"] = False
    final_contract["automatic_geometry_replacement"] = False

    final_contract_path = out / "D1_EXECUTION_CONTRACT_FINAL.json"
    final_contract_path.write_bytes(stable_json_bytes(final_contract))
    final_contract_sha = sha256_file(final_contract_path)

    status = "PASS" if unresolved == 0 and dense_changed == 0 else "REVIEW"
    manifest = {
        "schema_version": "akerpuls-full-skane-d0b-result-v1",
        "status": status,
        "git": {"branch": branch, "head": head},
        "base_d0_execution_contract_sha256": base_contract_sha,
        "frozen_geometry_sha256": geom_sha,
        "analysis_cells": len(resolved_df),
        "base_sparse_cells": len(sparse_df),
        "resolved_sparse_cells": int(len(sparse_df) - unresolved),
        "unresolved_sparse_cells": unresolved,
        "minimum_normalization_fields": min_fields,
        "resolved_windows_sha256": resolved_sha,
        "final_d1_execution_contract_sha256": final_contract_sha,
        "automatic_geometry_replacement": False,
        "sentinel_hub_pu_used": 0,
    }
    (out / "d0b_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("AKERPULS FULL SKANE D0B SPARSE NORMALIZATION RESOLUTION", flush=True)
    print(f"STATUS={status}")
    print(f"ANALYSIS_CELLS={len(resolved_df)}")
    print(f"BASE_SPARSE_CELLS={len(sparse_df)}")
    print(f"RESOLVED_SPARSE_CELLS={len(sparse_df)-unresolved}")
    print(f"UNRESOLVED_SPARSE_CELLS={unresolved}")
    for r in sparse_resolutions:
        print(
            f"RESOLUTION_{r['analysis_cell_id']}=BASE_{r['base_fields']}_EXPAND_{r['expansion_m']}M_FINAL_{r['final_fields']}_{r['status']}"
        )
    print(f"RESOLVED_WINDOWS_SHA256={resolved_sha}")
    print(f"BASE_D0_EXECUTION_CONTRACT_SHA256={base_contract_sha}")
    print(f"FINAL_D1_EXECUTION_CONTRACT_SHA256={final_contract_sha}")
    print("AUTOMATIC_GEOMETRY_REPLACEMENT=FALSE")
    print("SENTINEL_HUB_PU_USED=0")
    print(f"D0B_STATUS={status}")
    print("OUTPUT=" + str(out))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
