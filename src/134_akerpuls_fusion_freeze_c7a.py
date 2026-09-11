#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freeze a label-free 3-signal fusion score, then select a fourth geographic holdout.

Fusion reference population is ALL baseline SPLIT_CANDIDATE rows from C and C5.
No C3/C5D visual labels are read. Each signal is mapped to its empirical midrank
CDF in the frozen development population; the fusion score is the equal-weight
mean of history prior, Sentinel separation, and TRUE-LOO minimum child Dice.

C7A holdout selection uses only frozen 2025 geometry, public STAC footprints and
geographic distance from B, C and C5 pilots. No Sentinel Process API calls / PU.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import urllib.request
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_fusion_freeze_c7a.json"
MASTER = ROOT / "config" / "akerpuls_prelim_fields_2026_v0.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_field_id(v: Any) -> str:
    s = str(v).strip()
    p = s.split("|")
    if len(p) >= 3 and p[0] == "2025":
        return "|".join(p[1:])
    return s


def empirical_midrank(ref_sorted: np.ndarray, values: np.ndarray) -> np.ndarray:
    ref = np.asarray(ref_sorted, dtype=float)
    x = np.asarray(values, dtype=float)
    if len(ref) == 0 or np.any(~np.isfinite(ref)):
        raise ValueError("reference must be nonempty and finite")
    left = np.searchsorted(ref, x, side="left")
    right = np.searchsorted(ref, x, side="right")
    return (left + right) / (2.0 * len(ref))


def locate_true_loo_csv(root: Path) -> Path:
    req = {"dataset", "parent_field_id_2025", "true_loo_min_child_dice"}
    hits = []
    for p in sorted(root.glob("*.csv")):
        try:
            cols = set(pd.read_csv(p, nrows=1).columns)
        except Exception:
            continue
        if req.issubset(cols):
            hits.append(p)
    if len(hits) != 1:
        raise RuntimeError(f"Expected exactly one TRUE-LOO candidate CSV in {root}, found {hits}")
    return hits[0]


def build_development_frame(cfg: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, str], Path]:
    d = cfg["development_inputs"]
    c2p = Path(d["c2_validation"])
    c5p = Path(d["c5c_validation"])
    priorp = Path(d["rolling_prior"])
    lood = Path(d["true_loo_dir"])
    for p in (c2p, c5p, priorp, lood):
        if not p.exists():
            raise FileNotFoundError(p)
    loop = locate_true_loo_csv(lood)

    frames = []
    for dataset, p in (("C", c2p), ("C5", c5p)):
        x = pd.read_csv(p, dtype={"parent_field_id_2025": str})
        if "discovery_type" not in x or "separation_ratio" not in x:
            raise RuntimeError(f"{p} lacks discovery_type/separation_ratio")
        x = x[x["discovery_type"].astype(str) == "SPLIT_CANDIDATE"].copy()
        x["dataset"] = dataset
        x["field_id_normalized"] = x["parent_field_id_2025"].map(normalize_field_id)
        frames.append(x[["dataset", "parent_field_id_2025", "field_id_normalized", "separation_ratio"]])
    dev = pd.concat(frames, ignore_index=True)

    expected = int(cfg["fusion_contract"]["required_development_candidates"])
    if len(dev) != expected:
        raise RuntimeError(f"Expected {expected} C+C5 baseline candidates, got {len(dev)}")

    loo = pd.read_csv(loop, dtype={"parent_field_id_2025": str})
    loo["dataset"] = loo["dataset"].astype(str)
    loo["field_id_normalized"] = loo["parent_field_id_2025"].map(normalize_field_id)
    loo = loo[["dataset", "field_id_normalized", "true_loo_min_child_dice"]]
    if loo.duplicated(["dataset", "field_id_normalized"]).any():
        raise RuntimeError("TRUE-LOO candidate IDs are not unique by dataset")
    dev = dev.merge(loo, on=["dataset", "field_id_normalized"], how="left", validate="one_to_one")

    prior = pd.read_csv(priorp, dtype={"field_id": str})
    need = {"field_id", "prototype_p_splitmerge_2026"}
    if not need.issubset(prior.columns):
        raise RuntimeError(f"Prior file lacks {sorted(need - set(prior.columns))}")
    prior["field_id_normalized"] = prior["field_id"].map(normalize_field_id)
    if prior["field_id_normalized"].duplicated().any():
        raise RuntimeError("Rolling prior normalized field IDs are not unique")
    dev = dev.merge(
        prior[["field_id_normalized", "prototype_p_splitmerge_2026"]],
        on="field_id_normalized", how="left", validate="many_to_one",
    )

    signals = list(cfg["fusion_contract"]["signals"])
    for col in signals:
        dev[col] = pd.to_numeric(dev[col], errors="coerce")
        if dev[col].isna().any() or (~np.isfinite(dev[col])).any():
            raise RuntimeError(f"Development signal {col} has missing/nonfinite values")
    hashes = {str(p): sha256_file(p) for p in (c2p, c5p, loop, priorp)}
    return dev, hashes, loop


def make_fusion_freeze(dev: pd.DataFrame, cfg: dict[str, Any], out: Path, hashes: dict[str, str]) -> tuple[dict[str, Any], pd.DataFrame]:
    fc = cfg["fusion_contract"]
    signals = list(fc["signals"])
    weights = np.asarray(fc["weights"], dtype=float)
    if len(signals) != 3 or len(weights) != 3 or not np.isclose(weights.sum(), 1.0):
        raise RuntimeError("Fusion contract must contain three weights summing to one")

    refs: dict[str, list[float]] = {}
    score_parts = []
    scored = dev.copy()
    for sig in signals:
        ref = np.sort(dev[sig].to_numpy(dtype=float))
        refs[sig] = [float(v) for v in ref]
        s = empirical_midrank(ref, dev[sig].to_numpy(dtype=float))
        scored[f"cdf_{sig}"] = s
        score_parts.append(s)
    mat = np.vstack(score_parts).T
    scored["fusion_score"] = mat @ weights
    p90 = float(np.quantile(scored["fusion_score"], .90))
    p95 = float(np.quantile(scored["fusion_score"], .95))
    scored["fusion_ge_dev_p90"] = scored["fusion_score"] >= p90
    scored["fusion_ge_dev_p95"] = scored["fusion_score"] >= p95

    freeze = {
        "schema_version": "akerpuls-fusion-score-freeze-v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "status": fc["status"],
        "development_population": fc["development_population"],
        "development_n": int(len(scored)),
        "signals": signals,
        "weights": [float(v) for v in weights],
        "transform": fc["transform"],
        "fusion_score": fc["fusion_score"],
        "uses_visual_labels": False,
        "reference_sorted_values": refs,
        "development_fusion_p90": p90,
        "development_fusion_p95": p95,
        "source_sha256": hashes,
        "product_rule": False,
    }
    fp = out / "FUSION_SCORE_FREEZE_BEFORE_C7.json"
    fp.write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scored.to_csv(out / "fusion_development_candidates_367.csv", index=False)
    return freeze, scored


def stac(url: str, collection: str, bbox: list[float], day: str) -> list[dict[str, Any]]:
    d = date.fromisoformat(day)
    e = d + timedelta(days=1)
    payload = {"collections": [collection], "bbox": bbox,
               "datetime": f"{d}T00:00:00Z/{e}T00:00:00Z", "limit": 100}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))["features"]


def union_geometry(gdf):
    return gdf.geometry.union_all() if hasattr(gdf.geometry, "union_all") else gdf.geometry.unary_union


def select_c7_holdout(cfg: dict[str, Any], master: dict[str, Any], local_paths: Path, out: Path) -> dict[str, Any]:
    import geopandas as gpd
    from shapely.geometry import shape, box
    from shapely.ops import unary_union

    lp = read_json(local_paths)
    g = gpd.read_file(Path(lp["skiften"]))
    expected = int(master["upstream_freeze"]["expected_2025_fields"])
    if len(g) != expected:
        raise RuntimeError(f"Frozen field count mismatch: expected {expected}, got {len(g)}")
    g = g[g.geometry.notna() & ~g.geometry.is_empty & g.geometry.is_valid].copy().to_crs(32633)
    g["area_ha_2025"] = g.geometry.area / 10000.0
    g["parent_field_id_2025"] = "2025|" + g["blockid"].astype(str) + "|" + g["skiftesbeteckning"].astype(str)

    pp = cfg["prior_pilot_dirs"]
    paths = {
        "B": Path(pp["B"]) / "pilot_fields_2025.gpkg",
        "C": Path(pp["C"]) / "c0_pilot_fields_2025.gpkg",
        "C5": Path(pp["C5"]) / "c5a_pilot_fields_2025.gpkg",
    }
    pilots = {}
    for name, p in paths.items():
        if not p.exists():
            raise FileNotFoundError(p)
        pilots[name] = union_geometry(gpd.read_file(p).to_crs(32633))

    bbox4326 = list(map(float, g.to_crs(4326).total_bounds))
    cover = {}
    for snap, days in master["snapshots"].items():
        footprints = []
        for day in days:
            footprints += [shape(item["geometry"]) for item in stac(
                master["sentinel2"]["stac_search_url"], master["sentinel2"]["collection"], bbox4326, day)]
        if not footprints:
            raise RuntimeError(f"No STAC footprints found for {snap}")
        cover[snap] = gpd.GeoSeries([unary_union(footprints)], crs=4326).to_crs(32633).iloc[0]

    sel = cfg["holdout_selection"]
    eligible = (g["area_ha_2025"] >= float(sel["minimum_area_ha"])) & (g["area_ha_2025"] <= float(sel["maximum_area_ha"]))
    for snap, u in cover.items():
        frac = g.geometry.intersection(u).area / g.geometry.area
        g[f"footprint_{snap.lower()}"] = frac
        eligible &= frac >= float(sel["minimum_four_snapshot_footprint_fraction"])
    e = g[eligible].copy()

    md = float(sel["minimum_distance_from_each_prior_pilot_geometry_m"])
    for name, u in pilots.items():
        e[f"distance_from_{name.lower()}_m"] = e.geometry.distance(u)
        e = e[e[f"distance_from_{name.lower()}_m"] >= md].copy()
    if len(e) < int(sel["minimum_fields"]):
        raise RuntimeError(f"Only {len(e)} fields remain after C7 distance + footprint guards")

    grid = float(sel["grid_size_m"])
    minx, miny, maxx, maxy = e.total_bounds
    sidx = e.sindex
    cells = []
    for ix in range(math.floor(minx / grid), math.floor(maxx / grid) + 1):
        for iy in range(math.floor(miny / grid), math.floor(maxy / grid) + 1):
            cell = box(ix * grid, iy * grid, (ix + 1) * grid, (iy + 1) * grid)
            ids = list(sidx.query(cell, predicate="intersects"))
            if len(ids) < int(sel["minimum_fields"]):
                continue
            sub = e.iloc[ids]
            dists = {name: float(cell.distance(u)) for name, u in pilots.items()}
            cells.append({"ix": ix, "iy": iy, "n": len(sub), "area_ha": float(sub["area_ha_2025"].sum()),
                          "min_prior_distance_m": min(dists.values()), **{f"distance_from_{k.lower()}_m": v for k, v in dists.items()},
                          "geometry": cell})
    if not cells:
        raise RuntimeError("No 20 km cell satisfies C7 fourth-holdout guards")

    cdf = gpd.GeoDataFrame(cells, geometry="geometry", crs=32633).sort_values(
        ["n", "min_prior_distance_m"], ascending=[False, False]).reset_index(drop=True)
    best = cdf.iloc[0]
    ids = list(e.sindex.query(best.geometry, predicate="intersects"))
    cand = e.iloc[ids].copy()
    cand["distance_to_cell_center_m"] = cand.geometry.centroid.distance(best.geometry.centroid)
    target = min(int(sel["target_fields"]), int(sel["maximum_fields"]), len(cand))
    pilot = cand.nsmallest(target, "distance_to_cell_center_m").drop(columns=["distance_to_cell_center_m"], errors="ignore").copy()
    if len(pilot) < int(sel["minimum_fields"]):
        raise RuntimeError(f"Selected C7 cell yields only {len(pilot)} fields")

    pilot.to_file(out / "c7a_pilot_fields_2025.gpkg", layer="pilot_fields", driver="GPKG")
    cdf.head(20).to_file(out / "c7a_candidate_cells.gpkg", layer="candidate_cells", driver="GPKG")
    pgeom = union_geometry(pilot)
    bbox = pilot.to_crs(4326).total_bounds
    summary = {
        "schema_version": "akerpuls-c7a-fourth-holdout-selection-v1",
        "status": "PASS",
        "eligible_independent_four_snapshot_fields": int(len(e)),
        "selected_cell_fields_available": int(len(cand)),
        "pilot_fields": int(len(pilot)),
        "pilot_area_ha": round(float(pilot["area_ha_2025"].sum()), 3),
        "pilot_bbox_wgs84": [round(float(v), 6) for v in bbox],
        "distance_from_b_geometry_km": round(float(pgeom.distance(pilots["B"])) / 1000.0, 2),
        "distance_from_c_geometry_km": round(float(pgeom.distance(pilots["C"])) / 1000.0, 2),
        "distance_from_c5_geometry_km": round(float(pgeom.distance(pilots["C5"])) / 1000.0, 2),
        "selected_grid_cell_ix": int(best["ix"]),
        "selected_grid_cell_iy": int(best["iy"]),
        "sentinel_hub_pu_used": 0,
    }
    (out / "c7a_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CFG))
    ap.add_argument("--local-paths", default=str(ROOT / "config" / "local_paths.json"))
    ap.add_argument("--output-dir")
    args = ap.parse_args()

    cfg = read_json(Path(args.config)); master = read_json(MASTER)
    if any(bool(v) for v in cfg["guards"].values()):
        raise RuntimeError("C7A guards unexpectedly enable forbidden scope")
    if cfg["fusion_contract"].get("uses_visual_labels") is not False or cfg["fusion_contract"].get("uses_c3_or_c5d_labels") is not False:
        raise RuntimeError("Fusion freeze must be label-free")

    out = Path(args.output_dir or cfg["output_dir"]); out.mkdir(parents=True, exist_ok=True)
    dev, hashes, loo_path = build_development_frame(cfg)
    freeze, scored = make_fusion_freeze(dev, cfg, out, hashes)
    hold = select_c7_holdout(cfg, master, Path(args.local_paths), out)

    summary = {
        "schema_version": cfg["schema_version"], "status": "PASS",
        "fusion_development_n": int(len(scored)),
        "fusion_dev_p90": freeze["development_fusion_p90"],
        "fusion_dev_p95": freeze["development_fusion_p95"],
        "true_loo_source": str(loo_path),
        "fusion_freeze_sha256": sha256_file(out / "FUSION_SCORE_FREEZE_BEFORE_C7.json"),
        "holdout": hold,
        "visual_labels_used": False,
        "product_rule_frozen": False,
        "sentinel_hub_pu_used": 0,
    }
    (out / "c7a_fusion_freeze_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("AKERPULS C7A - LABEL-FREE FUSION FREEZE + FOURTH GEOGRAPHIC HOLDOUT")
    print(f"FUSION_DEVELOPMENT_CANDIDATES={len(scored)}")
    print(f"FUSION_DEV_P90={freeze['development_fusion_p90']:.6f} FUSION_DEV_P95={freeze['development_fusion_p95']:.6f}")
    print(f"FUSION_FREEZE_SHA256={summary['fusion_freeze_sha256']}")
    print(f"ELIGIBLE_INDEPENDENT_FOUR_SNAPSHOT_FIELDS={hold['eligible_independent_four_snapshot_fields']}")
    print(f"SELECTED_CELL_FIELDS_AVAILABLE={hold['selected_cell_fields_available']}")
    print(f"PILOT_FIELDS={hold['pilot_fields']} PILOT_AREA_HA={hold['pilot_area_ha']}")
    print(f"PILOT_BBOX_WGS84={hold['pilot_bbox_wgs84']}")
    print(f"DISTANCE_FROM_B_GEOMETRY_KM={hold['distance_from_b_geometry_km']}")
    print(f"DISTANCE_FROM_C_GEOMETRY_KM={hold['distance_from_c_geometry_km']}")
    print(f"DISTANCE_FROM_C5_GEOMETRY_KM={hold['distance_from_c5_geometry_km']}")
    print("FUSION_USES_VISUAL_LABELS=FALSE")
    print("PRODUCT_RULE_FROZEN=FALSE")
    print("SENTINEL_HUB_PU_USED=0")
    print("C7A_STATUS=PASS")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
