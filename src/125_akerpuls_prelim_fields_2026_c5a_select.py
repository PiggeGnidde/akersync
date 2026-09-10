#!/usr/bin/env python3
"""STOPPUNKT C5a: third geographically independent holdout selection. Public STAC only, zero PU."""
from __future__ import annotations

import argparse
import json
import math
import urllib.request
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "config" / "akerpuls_prelim_fields_2026_v0.json"
CFG = ROOT / "config" / "akerpuls_prelim_fields_2026_c5a.json"
C2CFG = ROOT / "config" / "akerpuls_prelim_fields_2026_c2.json"


def stac(url, collection, bbox, day):
    d = date.fromisoformat(day)
    e = d + timedelta(days=1)
    payload = {
        "collections": [collection],
        "bbox": bbox,
        "datetime": f"{d}T00:00:00Z/{e}T00:00:00Z",
        "limit": 100,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))["features"]


def union_geometry(gdf):
    return gdf.geometry.union_all() if hasattr(gdf.geometry, "union_all") else gdf.geometry.unary_union


def main():
    import geopandas as gpd
    from shapely.geometry import shape, box
    from shapely.ops import unary_union

    ap = argparse.ArgumentParser()
    ap.add_argument("--local-paths", default=str(ROOT / "config" / "local_paths.json"))
    ap.add_argument("--output-dir")
    args = ap.parse_args()

    master = json.loads(MASTER.read_text(encoding="utf-8"))
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    c2cfg = json.loads(C2CFG.read_text(encoding="utf-8"))
    sel = cfg["selection"]

    if cfg["split_candidate_rule_frozen_for_test"] != c2cfg["locked_split_rule"]:
        raise RuntimeError("C5a split-candidate rule differs from the independently tested C2 rule")
    hc = cfg["high_confidence_rule_frozen_for_test"]
    if hc.get("requires_split_candidate") is not True or float(hc.get("minimum_separation_ratio")) != 4.0:
        raise RuntimeError("C5a HIGH_CONFIDENCE_SPLIT test rule must be candidate AND separation_ratio>=4.0")
    if cfg["guards"].get("threshold_tuning") is not False:
        raise RuntimeError("Threshold tuning must remain disabled in C5 holdout")

    out = Path(args.output_dir or cfg["output_dir"])
    out.mkdir(parents=True, exist_ok=True)

    lp = json.loads(Path(args.local_paths).read_text(encoding="utf-8-sig"))
    g = gpd.read_file(Path(lp["skiften"]))
    expected = int(master["upstream_freeze"]["expected_2025_fields"])
    if len(g) != expected:
        raise RuntimeError(f"Frozen field count mismatch: expected {expected}, got {len(g)}")
    g = g[g.geometry.notna() & ~g.geometry.is_empty & g.geometry.is_valid].copy().to_crs(32633)
    g["area_ha_2025"] = g.geometry.area / 10000.0
    if "blockid" not in g.columns or "skiftesbeteckning" not in g.columns:
        raise RuntimeError("C5a requires blockid + skiftesbeteckning for stable IDs")
    g["parent_field_id_2025"] = "2025|" + g["blockid"].astype(str) + "|" + g["skiftesbeteckning"].astype(str)

    b = gpd.read_file(Path(cfg["b0_pilot_dir"]) / "pilot_fields_2025.gpkg").to_crs(32633)
    c = gpd.read_file(Path(cfg["c0_pilot_dir"]) / "c0_pilot_fields_2025.gpkg").to_crs(32633)
    bunion = union_geometry(b)
    cunion = union_geometry(c)

    bbox4326 = list(map(float, g.to_crs(4326).total_bounds))
    cover = {}
    for snap, days in master["snapshots"].items():
        footprints = []
        for day in days:
            footprints += [
                shape(item["geometry"])
                for item in stac(
                    master["sentinel2"]["stac_search_url"],
                    master["sentinel2"]["collection"],
                    bbox4326,
                    day,
                )
            ]
        if not footprints:
            raise RuntimeError(f"No STAC footprints found for {snap}")
        cover[snap] = gpd.GeoSeries([unary_union(footprints)], crs=4326).to_crs(32633).iloc[0]

    eligible = (
        (g["area_ha_2025"] >= float(sel["minimum_area_ha"]))
        & (g["area_ha_2025"] <= float(sel["maximum_area_ha"]))
    )
    for snap, u in cover.items():
        frac = g.geometry.intersection(u).area / g.geometry.area
        g[f"footprint_{snap.lower()}"] = frac
        eligible &= frac >= float(sel["minimum_four_snapshot_footprint_fraction"])

    e = g[eligible].copy()
    min_dist = float(sel["minimum_distance_from_prior_pilot_geometry_m"])
    e["distance_from_b_m"] = e.geometry.distance(bunion)
    e["distance_from_c_m"] = e.geometry.distance(cunion)
    e = e[(e["distance_from_b_m"] >= min_dist) & (e["distance_from_c_m"] >= min_dist)].copy()
    if len(e) < int(sel["minimum_fields"]):
        raise RuntimeError(f"Only {len(e)} fields remain after independent-distance and footprint guards")

    grid = float(sel["grid_size_m"])
    minx, miny, maxx, maxy = e.total_bounds
    ix0, ix1 = math.floor(minx / grid), math.floor(maxx / grid)
    iy0, iy1 = math.floor(miny / grid), math.floor(maxy / grid)
    sidx = e.sindex
    cells = []
    for ix in range(ix0, ix1 + 1):
        for iy in range(iy0, iy1 + 1):
            cell = box(ix * grid, iy * grid, (ix + 1) * grid, (iy + 1) * grid)
            ids = list(sidx.query(cell, predicate="intersects"))
            if not ids:
                continue
            sub = e.iloc[ids]
            n = len(sub)
            if n < int(sel["minimum_fields"]):
                continue
            cells.append(
                {
                    "ix": ix,
                    "iy": iy,
                    "n": n,
                    "area_ha": float(sub["area_ha_2025"].sum()),
                    "distance_from_b_geometry_m": float(cell.distance(bunion)),
                    "distance_from_c_geometry_m": float(cell.distance(cunion)),
                    "min_prior_distance_m": float(min(cell.distance(bunion), cell.distance(cunion))),
                    "geometry": cell,
                }
            )
    if not cells:
        raise RuntimeError("No 20 km cell satisfies C5a independent holdout guards")

    cdf = gpd.GeoDataFrame(cells, geometry="geometry", crs=32633)
    cdf = cdf.sort_values(["n", "min_prior_distance_m"], ascending=[False, False]).reset_index(drop=True)
    best = cdf.iloc[0]
    cell = best.geometry
    ids = list(e.sindex.query(cell, predicate="intersects"))
    cand = e.iloc[ids].copy()
    cand["distance_to_cell_center_m"] = cand.geometry.centroid.distance(cell.centroid)
    target = min(int(sel["target_fields"]), int(sel["maximum_fields"]), len(cand))
    if target < int(sel["minimum_fields"]):
        raise RuntimeError(f"Selected C5a cell only has {len(cand)} eligible fields")
    pilot = cand.nsmallest(target, "distance_to_cell_center_m").copy()
    pilot = pilot.drop(columns=["distance_to_cell_center_m"], errors="ignore")

    pilot.to_file(out / "c5a_pilot_fields_2025.gpkg", layer="pilot_fields", driver="GPKG")
    cdf.head(20).to_file(out / "c5a_candidate_cells.gpkg", layer="candidate_cells", driver="GPKG")

    pgeom = union_geometry(pilot)
    bbox = pilot.to_crs(4326).total_bounds
    summary = {
        "schema_version": "akerpuls-prelim-fields-2026-c5a-third-holdout-v1",
        "status": "PASS",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "eligible_independent_four_snapshot_fields": int(len(e)),
        "selected_cell_fields_available": int(len(cand)),
        "pilot_fields": int(len(pilot)),
        "pilot_area_ha": round(float(pilot["area_ha_2025"].sum()), 3),
        "pilot_bbox_wgs84": [round(float(x), 6) for x in bbox],
        "distance_from_b_geometry_km": round(float(pgeom.distance(bunion)) / 1000.0, 2),
        "distance_from_c_geometry_km": round(float(pgeom.distance(cunion)) / 1000.0, 2),
        "selected_grid_cell_ix": int(best["ix"]),
        "selected_grid_cell_iy": int(best["iy"]),
        "selected_grid_cell_available_fields": int(best["n"]),
        "split_candidate_rule_frozen_for_test": cfg["split_candidate_rule_frozen_for_test"],
        "high_confidence_rule_frozen_for_test": cfg["high_confidence_rule_frozen_for_test"],
        "merge_policy": cfg["merge_policy"],
        "sentinel_hub_pu_used": 0,
        "thresholds_tuned": False,
        "product_thresholds_frozen": False,
        "next_step": "C5b bounded raster download using identical B1/C1 preprocessing, then blind validation of candidate+separation>=4.0.",
    }
    (out / "c5a_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("AKERPULS PRELIM FIELDS 2026 - STOPPUNKT C5A THIRD GEOGRAPHIC HOLDOUT")
    print(f'ELIGIBLE_INDEPENDENT_FOUR_SNAPSHOT_FIELDS={summary["eligible_independent_four_snapshot_fields"]}')
    print(f'SELECTED_CELL_FIELDS_AVAILABLE={summary["selected_cell_fields_available"]}')
    print(f'PILOT_FIELDS={summary["pilot_fields"]} PILOT_AREA_HA={summary["pilot_area_ha"]}')
    print(f'PILOT_BBOX_WGS84={summary["pilot_bbox_wgs84"]}')
    print(f'DISTANCE_FROM_B_GEOMETRY_KM={summary["distance_from_b_geometry_km"]}')
    print(f'DISTANCE_FROM_C_GEOMETRY_KM={summary["distance_from_c_geometry_km"]}')
    print("SPLIT_CANDIDATE_RULE_FROZEN_FOR_TEST=" + json.dumps(cfg["split_candidate_rule_frozen_for_test"], separators=(",", ":")))
    print("HIGH_CONFIDENCE_RULE_FROZEN_FOR_TEST=" + json.dumps(cfg["high_confidence_rule_frozen_for_test"], separators=(",", ":")))
    print("THRESHOLDS_TUNED=FALSE")
    print("PRODUCT_THRESHOLDS_FROZEN=FALSE")
    print("SENTINEL_HUB_PU_USED=0")
    print("C5A_STATUS=PASS")
    print("OUTPUT=" + str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
