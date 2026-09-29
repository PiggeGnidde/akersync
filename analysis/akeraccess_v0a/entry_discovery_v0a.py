#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerAccess MVP v0a - OSM field-entry discovery for one municipality.

STOPPUNKT A is deliberately descriptive. No ÅkerAccess score is fitted here.
The script asks a narrower question: how often does OSM provide geometric
access evidence at the boundary of a known Jordbruksverket field polygon?
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for p in (ROOT, SRC):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from common import MUN_CODES
from analysis.akeraccess_v0a.core import (
    DRIVABLE_HIGHWAYS,
    classify_road_candidate,
    field_key,
    parse_overpass,
    text_id,
)

DEFAULT_CONFIG = ROOT / "config" / "akeraccess_v0a.json"
DEFAULT_OUT = ROOT / "work" / "akeraccess_v0a"


def slug(value: str) -> str:
    table = str.maketrans("åäöÅÄÖ", "aaoAAO")
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value.translate(table)).strip("_")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def resolve_path(value: str, base: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base / path


def discover_field_inputs() -> tuple[Path, Path, Path]:
    """Find an existing local_paths.json from the ÅkerSync worktrees."""
    candidates = [
        ROOT / "config" / "local_paths.json",
        Path(r"C:\AkerSync-Minne\config\local_paths.json"),
        Path(r"C:\AkerSync-AkerFro\config\local_paths.json"),
        Path(r"C:\AkerSync-Prestation\config\local_paths.json"),
        Path(r"C:\AkerSync-Prelim2026\config\local_paths.json"),
        Path(r"C:\AkerSyncRepo\config\local_paths.json"),
    ]
    checked = []
    for cfg_path in candidates:
        checked.append(str(cfg_path))
        if not cfg_path.exists():
            continue
        try:
            cfg = load_json(cfg_path)
            if "blocks" not in cfg or "skiften" not in cfg:
                continue
            base = cfg_path.parent.parent
            blocks = resolve_path(str(cfg["blocks"]), base)
            skiften = resolve_path(str(cfg["skiften"]), base)
            if blocks.exists() and skiften.exists():
                return blocks, skiften, cfg_path
        except Exception:
            continue
    raise FileNotFoundError(
        "Kunde inte hitta fungerande blocks/skiften via local_paths.json. Kontrollerade:\n  "
        + "\n  ".join(checked)
    )


def repair_polygon(geometry):
    if geometry is None or geometry.is_empty:
        return None
    candidate = geometry
    if not candidate.is_valid:
        try:
            from shapely import make_valid
            candidate = make_valid(candidate)
        except Exception:
            candidate = candidate.buffer(0)
    if candidate is None or candidate.is_empty:
        return None
    if candidate.geom_type not in {"Polygon", "MultiPolygon"}:
        parts = [g for g in getattr(candidate, "geoms", []) if g.geom_type in {"Polygon", "MultiPolygon"}]
        if not parts:
            return None
        from shapely.ops import unary_union
        candidate = unary_union(parts)
    return candidate if candidate is not None and not candidate.is_empty else None


def load_fields(municipality: str, blocks_path: Path, skiften_path: Path):
    import geopandas as gpd

    blocks = gpd.read_file(blocks_path).to_crs(3006)
    fields = gpd.read_file(skiften_path).to_crs(3006)
    if "region_kod" not in blocks or "blockid" not in blocks:
        raise RuntimeError("Blockfilen saknar region_kod eller blockid")
    if "blockid" not in fields or "skiftesbeteckning" not in fields:
        raise RuntimeError("Skiftesfilen saknar blockid eller skiftesbeteckning")

    blocks = blocks[["blockid", "region_kod", "geometry"]].copy()
    blocks["blockid"] = blocks["blockid"].map(text_id)
    fields["blockid"] = fields["blockid"].map(text_id)
    fields["skiftesbeteckning"] = fields["skiftesbeteckning"].map(text_id)

    code = MUN_CODES[municipality]
    municipality_blocks = set(
        blocks.loc[blocks["region_kod"].astype(str).str.startswith(code), "blockid"]
    )
    fields = fields[fields["blockid"].isin(municipality_blocks)].copy()
    if fields.empty:
        raise RuntimeError(f"Inga skiften hittades för {municipality} ({code})")

    fields["geometry"] = fields.geometry.map(repair_polygon)
    fields = fields[fields.geometry.notna()].copy()
    fields["field_id"] = [
        field_key(b, s) for b, s in zip(fields["blockid"], fields["skiftesbeteckning"])
    ]
    fields["area_ha"] = fields.geometry.area / 10000.0
    fields = fields.drop_duplicates("field_id", keep="first")
    return gpd.GeoDataFrame(
        fields[["field_id", "blockid", "skiftesbeteckning", "area_ha", "geometry"]],
        geometry="geometry", crs=3006,
    ).reset_index(drop=True)


def overpass_bbox(fields, pad_m: float) -> tuple[float, float, float, float]:
    import geopandas as gpd
    from shapely.geometry import box

    minx, miny, maxx, maxy = fields.total_bounds
    geom = box(minx - pad_m, miny - pad_m, maxx + pad_m, maxy + pad_m)
    wgs = gpd.GeoSeries([geom], crs=3006).to_crs(4326).iloc[0]
    west, south, east, north = wgs.bounds
    return float(south), float(west), float(north), float(east)


def build_overpass_query(bbox: tuple[float, float, float, float]) -> str:
    south, west, north, east = bbox
    allowed = "|".join(sorted(DRIVABLE_HIGHWAYS))
    b = f"{south:.7f},{west:.7f},{north:.7f},{east:.7f}"
    return f"""[out:json][timeout:180];
(
  way["highway"~"^({allowed})$"]({b});
  node["barrier"~"^(gate|lift_gate|swing_gate)$"]({b});
);
out body;
>;
out skel qt;
"""


def download_overpass(query: str, endpoints: list[str], timeout_s: int) -> tuple[dict[str, Any], str]:
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    errors = []
    for endpoint in endpoints:
        request = urllib.request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "User-Agent": "AkerSync-AkerAccess/0a (research MVP)",
                "Accept": "application/json",
            },
        )
        try:
            started = time.time()
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
            payload.setdefault("_akeraccess", {})["download_seconds"] = round(time.time() - started, 3)
            return payload, endpoint
        except Exception as exc:
            errors.append(f"{endpoint}: {exc!r}")
    raise RuntimeError("Alla Overpass-endpoints misslyckades:\n  " + "\n  ".join(errors))


def load_or_download_osm(fields, cfg: dict[str, Any], cache_path: Path, refresh: bool):
    bbox = overpass_bbox(fields, float(cfg["bbox_pad_m"]))
    query = build_overpass_query(bbox)
    query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()

    if cache_path.exists() and not refresh:
        payload = load_json(cache_path)
        meta = payload.get("_akeraccess") or {}
        if meta.get("query_sha256") == query_hash:
            return payload, {
                "source": "cache",
                "endpoint": meta.get("endpoint"),
                "bbox": bbox,
                "query_sha256": query_hash,
            }

    payload, endpoint = download_overpass(
        query,
        list(cfg["overpass_endpoints"]),
        int(cfg.get("overpass_timeout_s", 240)),
    )
    payload.setdefault("_akeraccess", {}).update({
        "query_sha256": query_hash,
        "endpoint": endpoint,
        "bbox": bbox,
    })
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload, {
        "source": "download",
        "endpoint": endpoint,
        "bbox": bbox,
        "query_sha256": query_hash,
    }


def osm_geodataframes(payload):
    import geopandas as gpd
    from shapely.geometry import LineString, Point

    roads, gates = parse_overpass(payload)

    road_rows = []
    for road in roads:
        tags = road["tags"]
        road_rows.append({
            "osm_way_id": road["osm_way_id"],
            "highway": road["highway"],
            "surface": tags.get("surface"),
            "tracktype": tags.get("tracktype"),
            "smoothness": tags.get("smoothness"),
            "width": tags.get("width"),
            "maxwidth": tags.get("maxwidth"),
            "maxheight": tags.get("maxheight"),
            "access": tags.get("access"),
            "service": tags.get("service"),
            "geometry": LineString(road["coords"]),
        })
    if road_rows:
        roads_gdf = gpd.GeoDataFrame(road_rows, geometry="geometry", crs=4326).to_crs(3006)
    else:
        roads_gdf = gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=3006)

    gate_rows = [{
        "osm_node_id": gate["osm_node_id"],
        "barrier": gate["barrier"],
        "access": gate["tags"].get("access"),
        "width": gate["tags"].get("width"),
        "maxwidth": gate["tags"].get("maxwidth"),
        "geometry": Point(gate["coord"]),
    } for gate in gates]
    if gate_rows:
        gates_gdf = gpd.GeoDataFrame(gate_rows, geometry="geometry", crs=4326).to_crs(3006)
    else:
        gates_gdf = gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=3006)
    return roads_gdf, gates_gdf


def representative_entry_point(boundary, line):
    from shapely.geometry import Point
    from shapely.ops import nearest_points

    inter = boundary.intersection(line)
    if not inter.is_empty:
        if inter.geom_type == "Point":
            return inter
        if inter.geom_type == "MultiPoint":
            return list(inter.geoms)[0]
        if inter.geom_type in {"LineString", "MultiLineString"}:
            return inter.interpolate(0.5, normalized=True)
        points = [g for g in getattr(inter, "geoms", []) if g.geom_type == "Point"]
        if points:
            return points[0]
    p_field, _ = nearest_points(boundary, line)
    return Point(p_field.x, p_field.y)


def gate_ids_near(field_geometry, road_geometry, gates, cfg: dict[str, Any]) -> list[int]:
    if gates.empty:
        return []
    gate_boundary_m = float(cfg["thresholds_m"].get("gate_boundary_m", 7.5))
    gate_road_m = float(cfg["thresholds_m"].get("gate_road_m", 3.0))
    idx = gates.sindex.query(field_geometry.boundary.buffer(gate_boundary_m), predicate="intersects")
    result = []
    for gi in np.atleast_1d(idx):
        row = gates.iloc[int(gi)]
        if float(row.geometry.distance(road_geometry)) <= gate_road_m:
            result.append(int(row.osm_node_id))
    return sorted(set(result))


def detect_candidates(fields, roads, gates, cfg: dict[str, Any]):
    import geopandas as gpd

    threshold = cfg["thresholds_m"]
    search_m = max(float(threshold["endpoint_possible_m"]), float(threshold["adjacency_m"]))
    rows = []

    for frow in fields.itertuples(index=False):
        field_geom = frow.geometry
        road_idx = (
            roads.sindex.query(field_geom.buffer(search_m), predicate="intersects")
            if not roads.empty else []
        )
        for ri in np.atleast_1d(road_idx):
            r = roads.iloc[int(ri)]
            gate_ids = gate_ids_near(field_geom, r.geometry, gates, cfg)
            assessment = classify_road_candidate(
                field_geom, r.geometry, str(r.highway), bool(gate_ids), threshold
            )
            if assessment is None:
                continue
            point = representative_entry_point(field_geom.boundary, r.geometry)
            rows.append({
                "field_id": frow.field_id,
                "blockid": frow.blockid,
                "skiftesbeteckning": frow.skiftesbeteckning,
                "area_ha": float(frow.area_ha),
                "candidate_kind": assessment.kind,
                "confidence": float(assessment.confidence),
                "osm_way_id": int(r.osm_way_id),
                "highway": r.highway,
                "surface": r.surface,
                "tracktype": r.tracktype,
                "smoothness": r.smoothness,
                "width": r.width,
                "maxwidth": r.maxwidth,
                "maxheight": r.maxheight,
                "access": r.access,
                "service": r.service,
                "line_distance_m": float(assessment.line_distance_m),
                "endpoint_distance_m": float(assessment.endpoint_distance_m),
                "inside_length_m": float(assessment.inside_length_m),
                "gate_near": bool(gate_ids),
                "gate_ids": ";".join(map(str, gate_ids)),
                "geometry": point,
            })

    if not rows:
        return gpd.GeoDataFrame(columns=["field_id", "geometry"], geometry="geometry", crs=3006)

    candidates = gpd.GeoDataFrame(rows, geometry="geometry", crs=3006)
    candidates = candidates.sort_values(
        ["field_id", "confidence", "inside_length_m", "endpoint_distance_m", "osm_way_id"],
        ascending=[True, False, False, True, True],
    ).reset_index(drop=True)
    candidates["candidate_rank"] = candidates.groupby("field_id").cumcount() + 1
    return candidates


def build_field_summary(fields, candidates):
    base = pd.DataFrame(fields.drop(columns="geometry"))
    if candidates.empty:
        base["n_candidates"] = 0
        base["entry_status"] = "NO_OSM_ENTRY_EVIDENCE"
        base["best_confidence"] = 0.0
        return base

    n = candidates.groupby("field_id").size().rename("n_candidates")
    best = candidates[candidates["candidate_rank"].eq(1)].drop(columns="geometry").copy()
    rename = {
        c: "best_" + c
        for c in best.columns
        if c not in {"field_id", "blockid", "skiftesbeteckning", "area_ha"}
    }
    best = best.rename(columns=rename)
    keep = ["field_id"] + [c for c in best.columns if c.startswith("best_")]
    out = (
        base.merge(n, on="field_id", how="left")
        .merge(best[keep], on="field_id", how="left", validate="one_to_one")
    )
    out["n_candidates"] = out["n_candidates"].fillna(0).astype(int)
    out["best_confidence"] = pd.to_numeric(out["best_confidence"], errors="coerce").fillna(0.0)
    out["entry_status"] = np.select(
        [
            out["best_confidence"] >= 0.85,
            out["best_confidence"] >= 0.50,
            out["best_confidence"] > 0.0,
        ],
        ["STRONG_OSM_EVIDENCE", "POSSIBLE_OSM_EVIDENCE", "ADJACENCY_ONLY"],
        default="NO_OSM_ENTRY_EVIDENCE",
    )
    return out


def deterministic_review_sample(field_summary: pd.DataFrame, n: int) -> pd.DataFrame:
    if n <= 0 or field_summary.empty:
        return field_summary.head(0).copy()
    frame = field_summary.copy()
    frame["_hash"] = frame["field_id"].map(
        lambda x: hashlib.sha256(str(x).encode("utf-8")).hexdigest()
    )
    groups = []
    statuses = [
        "STRONG_OSM_EVIDENCE",
        "POSSIBLE_OSM_EVIDENCE",
        "ADJACENCY_ONLY",
        "NO_OSM_ENTRY_EVIDENCE",
    ]
    per = max(1, n // len(statuses))
    used = set()
    for status in statuses:
        q = frame[frame["entry_status"].eq(status)].sort_values("_hash").head(per)
        groups.append(q)
        used.update(q["field_id"].tolist())
    selected = pd.concat(groups, ignore_index=True) if groups else frame.head(0)
    if len(selected) < n:
        extra = frame[~frame["field_id"].isin(used)].sort_values("_hash").head(n - len(selected))
        selected = pd.concat([selected, extra], ignore_index=True)
    return selected.drop(columns="_hash", errors="ignore").head(n)


def write_outputs(municipality: str, fields, roads, gates, candidates, field_summary, meta, cfg, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    slug_mun = slug(municipality)

    field_csv = out_dir / f"{slug_mun}_field_entry_summary.csv"
    cand_csv = out_dir / f"{slug_mun}_entry_candidates.csv"
    cand_geojson = out_dir / f"{slug_mun}_entry_candidates.geojson"
    sample_csv = out_dir / f"{slug_mun}_manual_review_sample.csv"
    sample_geojson = out_dir / f"{slug_mun}_manual_review_fields.geojson"
    report_json = out_dir / f"{slug_mun}_stoppunkt_a.json"

    field_summary.to_csv(field_csv, index=False, encoding="utf-8-sig")
    candidates.drop(columns="geometry").to_csv(cand_csv, index=False, encoding="utf-8-sig")
    if not candidates.empty:
        candidates.to_crs(4326).to_file(cand_geojson, driver="GeoJSON")

    sample = deterministic_review_sample(field_summary, int(cfg.get("manual_review_n", 100)))
    sample.to_csv(sample_csv, index=False, encoding="utf-8-sig")
    sample_fields = fields[fields["field_id"].isin(set(sample["field_id"]))].copy()
    if not sample_fields.empty:
        sample_fields = sample_fields.merge(
            sample[["field_id", "entry_status", "best_confidence"]],
            on="field_id", how="left"
        )
        sample_fields.to_crs(4326).to_file(sample_geojson, driver="GeoJSON")

    status_counts = field_summary["entry_status"].value_counts().to_dict()
    status_pct = {k: 100.0 * int(v) / len(field_summary) for k, v in status_counts.items()}
    best_highways = (
        field_summary.loc[field_summary["best_confidence"].gt(0), "best_highway"]
        .value_counts(dropna=False).head(20).to_dict()
        if "best_highway" in field_summary else {}
    )
    report = {
        "schema_version": "akeraccess-entry-discovery-v0a",
        "municipality": municipality,
        "municipality_code": MUN_CODES[municipality],
        "n_fields": int(len(fields)),
        "n_osm_roads": int(len(roads)),
        "n_osm_gates": int(len(gates)),
        "n_entry_candidates": int(len(candidates)),
        "n_fields_with_any_candidate": int(field_summary["n_candidates"].gt(0).sum()),
        "status_counts": {str(k): int(v) for k, v in status_counts.items()},
        "status_pct": {str(k): round(float(v), 3) for k, v in status_pct.items()},
        "best_highway_counts": {str(k): int(v) for k, v in best_highways.items()},
        "osm": meta,
        "thresholds_m": cfg["thresholds_m"],
        "outputs": {
            "field_summary": str(field_csv),
            "candidate_csv": str(cand_csv),
            "candidate_geojson": str(cand_geojson),
            "manual_review_sample": str(sample_csv),
            "manual_review_fields_geojson": str(sample_geojson),
        },
        "interpretation": "STOPPUNKT A is descriptive only; no ÅkerAccess score is frozen.",
    }
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report, report_json


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kommun", default="Sjöbo")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--out", default=None)
    ap.add_argument("--refresh-osm", action="store_true")
    args = ap.parse_args()

    municipality = args.kommun
    if municipality not in MUN_CODES:
        aliases = {slug(k): k for k in MUN_CODES}
        municipality = aliases.get(slug(municipality), municipality)
    if municipality not in MUN_CODES:
        raise ValueError(f"Okänd skånsk kommun: {args.kommun}")

    cfg = load_json(Path(args.config))
    out_dir = Path(args.out) if args.out else DEFAULT_OUT / slug(municipality)
    cache_path = (
        ROOT / "data" / "raw" / "akeraccess_osm"
        / f"{slug(municipality)}_roads_gates.json"
    )

    print("=" * 92)
    print("ÅkerAccess MVP v0a - STOPPUNKT A - OSM ENTRY DISCOVERY")
    print("=" * 92)
    print(f"Kommun: {municipality} ({MUN_CODES[municipality]})")

    blocks_path, skiften_path, local_cfg = discover_field_inputs()
    print(f"Input config: {local_cfg}")
    print(f"Blocks: {blocks_path}")
    print(f"Skiften: {skiften_path}")

    fields = load_fields(municipality, blocks_path, skiften_path)
    print(f"Skiften i {municipality}: {len(fields):,}")

    payload, osm_meta = load_or_download_osm(fields, cfg, cache_path, args.refresh_osm)
    roads, gates = osm_geodataframes(payload)
    print(f"OSM source: {osm_meta['source']} ({osm_meta.get('endpoint')})")
    print(f"OSM drivable ways: {len(roads):,}")
    print(f"OSM gates: {len(gates):,}")

    candidates = detect_candidates(fields, roads, gates, cfg)
    summary = build_field_summary(fields, candidates)
    report, report_path = write_outputs(
        municipality, fields, roads, gates, candidates, summary, osm_meta, cfg, out_dir
    )

    print("\nENTRY EVIDENCE")
    for status in [
        "STRONG_OSM_EVIDENCE",
        "POSSIBLE_OSM_EVIDENCE",
        "ADJACENCY_ONLY",
        "NO_OSM_ENTRY_EVIDENCE",
    ]:
        count = int(report["status_counts"].get(status, 0))
        pct = float(report["status_pct"].get(status, 0.0))
        print(f"  {status:24s} {count:6,d}  {pct:6.2f}%")

    print(f"\nCandidate rows: {len(candidates):,}")
    if report["best_highway_counts"]:
        print("Best-candidate highway types:")
        for key, value in report["best_highway_counts"].items():
            print(f"  {key}: {value:,}")

    print(f"\nSTOPPUNKT A JSON: {report_path}")
    print(f"Manual review sample: {report['outputs']['manual_review_sample']}")
    print("=" * 92)
    print("STOPPUNKT A DISCOVERY: PASS")
    print("=" * 92)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
