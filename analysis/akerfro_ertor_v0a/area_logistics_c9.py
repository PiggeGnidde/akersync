#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerFrö – Ärter MVP v0a · C9 area + Bjuv logistics diagnostic.

Purpose:
  Diagnose operational selection structure before adding logistics to the
  product policy.

Inputs:
  - C8 ÄrtKandidat field product
  - existing local field coordinate/geometry sources, discovered read-only
  - fixed Bjuv processor anchor from config

Outputs:
  - area enrichment tables
  - distance enrichment tables (when coordinates can be discovered)
  - area x distance matrix
  - field-level logistics sidecar

C9 deliberately does NOT change C8 A/B/C/D classes and does NOT modify frozen
ÄrtMatch v0a.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.akerfro_ertor_v0a.build_positive_profile_c1 import (
    ROOT_NAMES,
    field_key,
    read_table,
    text_id,
)

DEFAULT_CONFIG = ROOT / "config" / "akerfro_ertor_c9.json"
DEFAULT_C8 = ROOT / "data" / "derived" / "akerfro_ertor_v0a" / "artkandidat_v0a_fields.parquet"
DEFAULT_OUT = ROOT / "work" / "akerfro_ertor_v0a" / "area_logistics_c9"

AREA_COL = "static__field_area_m2"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def candidate_roots() -> list[Path]:
    roots = []
    for name in ROOT_NAMES:
        p = Path("C:/") / name
        if p.exists():
            roots.append(p)
    return roots


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    lat1 = np.radians(np.asarray(lat1, dtype=float))
    lon1 = np.radians(np.asarray(lon1, dtype=float))
    lat2 = math.radians(float(lat2))
    lon2 = math.radians(float(lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * math.cos(lat2) * np.sin(dlon / 2.0) ** 2
    return 2.0 * r * np.arcsin(np.sqrt(a))


def coordinate_pair(frame: pd.DataFrame) -> tuple[str, str, str] | None:
    cols = {str(c).casefold(): str(c) for c in frame.columns}
    named = [
        ("centroid_lon", "centroid_lat"),
        ("centroid_longitude", "centroid_latitude"),
        ("longitude", "latitude"),
        ("lon", "lat"),
        ("lng", "lat"),
        ("x_wgs84", "y_wgs84"),
        ("centroid_x", "centroid_y"),
        ("easting", "northing"),
        ("x", "y"),
    ]
    for xname, yname in named:
        if xname in cols and yname in cols:
            xcol, ycol = cols[xname], cols[yname]
            x = pd.to_numeric(frame[xcol], errors="coerce").dropna()
            y = pd.to_numeric(frame[ycol], errors="coerce").dropna()
            if len(x) == 0 or len(y) == 0:
                continue
            xm = float(x.median())
            ym = float(y.median())
            if -180 <= xm <= 180 and -90 <= ym <= 90:
                return xcol, ycol, "EPSG:4326"
            if 100000 <= xm <= 1000000 and 5000000 <= ym <= 8000000:
                return xcol, ycol, "EPSG:3006"
    return None


def table_candidates() -> list[Path]:
    found: list[Path] = []
    seen = set()
    exact_rel = [
        "data/derived/akerprestation_phase0/skane/field_static_context.parquet",
        "data/derived/geometry_v1a_skiften.csv",
    ]
    patterns = [
        "data/derived/**/*skift*2025*.parquet",
        "data/derived/**/*skift*.parquet",
        "data/raw/**/*skift*2025*.parquet",
        "data/raw/**/*skift*.parquet",
    ]
    for root in candidate_roots():
        for rel in exact_rel:
            p = root / rel
            if p.exists():
                key = str(p.resolve()).casefold()
                if key not in seen:
                    seen.add(key)
                    found.append(p)
        for pattern in patterns:
            try:
                for p in root.glob(pattern):
                    if not p.is_file():
                        continue
                    key = str(p.resolve()).casefold()
                    if key not in seen:
                        seen.add(key)
                        found.append(p)
            except OSError:
                pass
    return found


def vector_candidates() -> list[Path]:
    found: list[Path] = []
    seen = set()
    patterns = [
        "data/derived/**/*skift*2025*.gpkg",
        "data/derived/**/*skift*.gpkg",
        "data/derived/**/*skift*2025*.shp",
        "data/derived/**/*skift*.shp",
        "data/raw/**/*skift*2025*.gpkg",
        "data/raw/**/*skift*.gpkg",
        "data/raw/**/*skift*2025*.shp",
        "data/raw/**/*skift*.shp",
    ]
    for root in candidate_roots():
        for pattern in patterns:
            try:
                for p in root.glob(pattern):
                    if not p.is_file():
                        continue
                    key = str(p.resolve()).casefold()
                    if key not in seen:
                        seen.add(key)
                        found.append(p)
            except OSError:
                pass
    return found


def convert_xy_to_wgs84(x: pd.Series, y: pd.Series, crs: str) -> tuple[pd.Series, pd.Series]:
    xv = pd.to_numeric(x, errors="coerce")
    yv = pd.to_numeric(y, errors="coerce")
    if crs == "EPSG:4326":
        return yv.rename("field_lat"), xv.rename("field_lon")
    if crs != "EPSG:3006":
        raise ValueError(crs)
    try:
        from pyproj import Transformer
    except Exception as exc:
        raise RuntimeError("C9 found SWEREF 99 TM coordinates but pyproj is unavailable") from exc
    transformer = Transformer.from_crs(3006, 4326, always_xy=True)
    lon = np.full(len(xv), np.nan)
    lat = np.full(len(yv), np.nan)
    valid = xv.notna() & yv.notna()
    if valid.any():
        lo, la = transformer.transform(xv[valid].to_numpy(float), yv[valid].to_numpy(float))
        lon[valid.to_numpy()] = lo
        lat[valid.to_numpy()] = la
    return pd.Series(lat, index=x.index, name="field_lat"), pd.Series(lon, index=x.index, name="field_lon")


def assess_tabular_coordinates(path: Path, field_ids: set[str]) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    try:
        frame = read_table(path)
    except Exception as exc:
        return None, {"path": str(path), "type": "table", "status": "READ_FAIL", "error": repr(exc)}
    key = field_key(frame)
    if key is None:
        return None, {"path": str(path), "type": "table", "status": "NO_FIELD_KEY"}
    pair = coordinate_pair(frame)
    if pair is None:
        return None, {"path": str(path), "type": "table", "status": "NO_COORDINATE_PAIR"}
    xcol, ycol, crs = pair
    coords = pd.DataFrame({"current_field_id": key.map(text_id)})
    try:
        lat, lon = convert_xy_to_wgs84(frame[xcol], frame[ycol], crs)
    except Exception as exc:
        return None, {
            "path": str(path), "type": "table", "status": "COORDINATE_CONVERSION_FAIL",
            "xcol": xcol, "ycol": ycol, "crs": crs, "error": repr(exc),
        }
    coords["field_lat"] = lat
    coords["field_lon"] = lon
    coords = coords[
        coords["current_field_id"].ne("")
        & coords["field_lat"].between(54.0, 70.0)
        & coords["field_lon"].between(5.0, 25.0)
    ].drop_duplicates("current_field_id", keep="first")
    hits = int(coords["current_field_id"].isin(field_ids).sum())
    return coords, {
        "path": str(path), "type": "table", "status": "OK",
        "xcol": xcol, "ycol": ycol, "source_crs": crs,
        "rows_with_valid_coords": int(len(coords)),
        "join_hits": hits,
        "join_coverage_pct": 100.0 * hits / len(field_ids),
    }


def assess_vector_coordinates(path: Path, field_ids: set[str]) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    try:
        import geopandas as gpd
    except Exception as exc:
        return None, {"path": str(path), "type": "vector", "status": "GEOPANDAS_UNAVAILABLE", "error": repr(exc)}
    try:
        g = gpd.read_file(path)
    except Exception as exc:
        return None, {"path": str(path), "type": "vector", "status": "READ_FAIL", "error": repr(exc)}
    key = field_key(g)
    if key is None:
        return None, {"path": str(path), "type": "vector", "status": "NO_FIELD_KEY"}
    if g.crs is None:
        return None, {"path": str(path), "type": "vector", "status": "NO_CRS"}
    try:
        metric = g.to_crs(3006)
        cent = metric.geometry.centroid
        gs = gpd.GeoSeries(cent, index=g.index, crs=3006).to_crs(4326)
    except Exception as exc:
        return None, {"path": str(path), "type": "vector", "status": "CRS_CONVERSION_FAIL", "error": repr(exc)}
    coords = pd.DataFrame({
        "current_field_id": key.map(text_id),
        "field_lat": gs.y,
        "field_lon": gs.x,
    })
    coords = coords[
        coords["current_field_id"].ne("")
        & coords["field_lat"].between(54.0, 70.0)
        & coords["field_lon"].between(5.0, 25.0)
    ].drop_duplicates("current_field_id", keep="first")
    hits = int(coords["current_field_id"].isin(field_ids).sum())
    return coords, {
        "path": str(path), "type": "vector", "status": "OK",
        "source_crs": str(g.crs),
        "rows_with_valid_coords": int(len(coords)),
        "join_hits": hits,
        "join_coverage_pct": 100.0 * hits / len(field_ids),
    }


def discover_coordinates(field_ids: set[str]) -> tuple[pd.DataFrame | None, dict[str, Any], pd.DataFrame]:
    reports = []
    best_coords = None
    best_report = {"status": "NOT_FOUND", "join_hits": 0}

    for path in table_candidates():
        coords, report = assess_tabular_coordinates(path, field_ids)
        reports.append(report)
        if coords is not None and int(report.get("join_hits", 0)) > int(best_report.get("join_hits", 0)):
            best_coords, best_report = coords, report
        if int(best_report.get("join_hits", 0)) >= int(0.98 * len(field_ids)):
            break

    if int(best_report.get("join_hits", 0)) < int(0.98 * len(field_ids)):
        for path in vector_candidates():
            coords, report = assess_vector_coordinates(path, field_ids)
            reports.append(report)
            if coords is not None and int(report.get("join_hits", 0)) > int(best_report.get("join_hits", 0)):
                best_coords, best_report = coords, report
            if int(best_report.get("join_hits", 0)) >= int(0.98 * len(field_ids)):
                break

    return best_coords, best_report, pd.DataFrame(reports)


def make_labels(edges: list[float], unit: str) -> list[str]:
    labels = []
    for a, b in zip(edges[:-1], edges[1:]):
        if b >= 999999:
            labels.append(f"{a:g}+ {unit}")
        elif a == 0:
            labels.append(f"<{b:g} {unit}")
        else:
            labels.append(f"{a:g}-{b:g} {unit}")
    return labels


def band(values: pd.Series, edges: list[float], unit: str) -> pd.Series:
    return pd.cut(
        pd.to_numeric(values, errors="coerce"),
        bins=edges,
        right=False,
        include_lowest=True,
        labels=make_labels(edges, unit),
    )


def enrichment_by_band(
    frame: pd.DataFrame,
    band_col: str,
    universe_name: str,
    universe_mask: pd.Series,
) -> pd.DataFrame:
    q = frame[universe_mask & frame[band_col].notna()].copy()
    if q.empty:
        return pd.DataFrame()
    overall = float(q["is_positive"].mean())
    rows = []
    for b, g in q.groupby(band_col, observed=False, sort=False):
        if len(g) == 0:
            continue
        rate = float(g["is_positive"].mean())
        rows.append({
            "universe": universe_name,
            "band": str(b),
            "n_fields": int(len(g)),
            "n_historical_positive": int(g["is_positive"].sum()),
            "historical_positive_rate_pct": 100.0 * rate,
            "enrichment_vs_universe": rate / overall if overall > 0 else np.nan,
            "n_A_2026": int(g["artkandidat_class"].eq("A_STRONG_CANDIDATE").sum()),
            "n_B_2026": int(g["artkandidat_class"].eq("B_PHYSICAL_CANDIDATE").sum()),
            "median_artmatch": float(pd.to_numeric(g["artmatch_score"], errors="coerce").median()),
        })
    return pd.DataFrame(rows)


def area_distance_matrix(frame: pd.DataFrame, universe_mask: pd.Series) -> pd.DataFrame:
    q = frame[
        universe_mask
        & frame["area_band"].notna()
        & frame["distance_band"].notna()
    ].copy()
    if q.empty:
        return pd.DataFrame()
    rows = []
    overall = float(q["is_positive"].mean())
    for (ab, db), g in q.groupby(["area_band", "distance_band"], observed=False, sort=False):
        if len(g) == 0:
            continue
        rate = float(g["is_positive"].mean())
        rows.append({
            "area_band": str(ab),
            "distance_band": str(db),
            "n_fields": int(len(g)),
            "n_historical_positive": int(g["is_positive"].sum()),
            "historical_positive_rate_pct": 100.0 * rate,
            "enrichment_vs_candidate_universe": rate / overall if overall > 0 else np.nan,
            "n_A_2026": int(g["artkandidat_class"].eq("A_STRONG_CANDIDATE").sum()),
            "n_B_2026": int(g["artkandidat_class"].eq("B_PHYSICAL_CANDIDATE").sum()),
        })
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--c8", default=str(DEFAULT_C8))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    cfg = load_json(Path(args.config))
    c8_path = Path(args.c8)
    if not c8_path.exists():
        raise FileNotFoundError(f"Run C8 first: {c8_path}")

    frame = pd.read_parquet(c8_path)
    if len(frame) != 128636:
        raise RuntimeError(f"C9 expected 128,636 C8 rows; got {len(frame):,}")
    if AREA_COL not in frame.columns:
        raise RuntimeError(f"C9 requires {AREA_COL} from frozen ÄrtMatch/C8 field product")
    if "is_positive" not in frame.columns:
        raise RuntimeError("C9 requires historical-positive flag carried from ÄrtMatch")

    frame["field_area_ha"] = pd.to_numeric(frame[AREA_COL], errors="coerce") / 10000.0
    area_edges = [float(x) for x in cfg["area_bins_ha"]]
    frame["area_band"] = band(frame["field_area_ha"], area_edges, "ha")

    field_ids = set(frame["current_field_id"].map(text_id))
    coords, coord_report, discovery = discover_coordinates(field_ids)

    frame["field_lat"] = np.nan
    frame["field_lon"] = np.nan
    frame["distance_bjuv_km"] = np.nan
    frame["distance_band"] = pd.Series(pd.NA, index=frame.index, dtype="string")

    if coords is not None and int(coord_report.get("join_hits", 0)) > 0:
        c = coords[["current_field_id", "field_lat", "field_lon"]].copy()
        c["current_field_id"] = c["current_field_id"].map(text_id)
        frame["current_field_id"] = frame["current_field_id"].map(text_id)
        frame = frame.drop(columns=["field_lat", "field_lon"]).merge(
            c, on="current_field_id", how="left", validate="one_to_one"
        )
        proc = cfg["processor"]
        valid = frame["field_lat"].notna() & frame["field_lon"].notna()
        frame.loc[valid, "distance_bjuv_km"] = haversine_km(
            frame.loc[valid, "field_lat"],
            frame.loc[valid, "field_lon"],
            proc["lat"],
            proc["lon"],
        )
        dist_edges = [float(x) for x in cfg["distance_bins_km"]]
        frame["distance_band"] = band(frame["distance_bjuv_km"], dist_edges, "km").astype("string")

    universes = {
        "all_fields_with_required_measure": pd.Series(True, index=frame.index),
        "high_artmatch_rotation_ok": (
            frame["artmatch_high"].fillna(False).astype(bool)
            & frame["rotation_ok"].fillna(False).astype(bool)
        ),
    }

    area_tables = []
    distance_tables = []
    for name, mask in universes.items():
        area_tables.append(enrichment_by_band(frame, "area_band", name, mask))
        if frame["distance_bjuv_km"].notna().any():
            distance_tables.append(enrichment_by_band(frame, "distance_band", name, mask))

    area_summary = pd.concat([x for x in area_tables if len(x)], ignore_index=True)
    distance_summary = (
        pd.concat([x for x in distance_tables if len(x)], ignore_index=True)
        if any(len(x) for x in distance_tables) else pd.DataFrame()
    )
    matrix = (
        area_distance_matrix(frame, universes["high_artmatch_rotation_ok"])
        if frame["distance_bjuv_km"].notna().any()
        else pd.DataFrame()
    )

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sidecar_path = out / "artkandidat_c9_area_logistics_fields.parquet"
    area_path = out / "area_enrichment.csv"
    distance_path = out / "distance_bjuv_enrichment.csv"
    matrix_path = out / "area_x_distance_enrichment.csv"
    discovery_path = out / "coordinate_source_discovery.csv"

    side_cols = [
        "current_field_id", "municipality", "artkandidat_class", "artmatch_score",
        "rotation_status", "crop_2025_name", "is_positive",
        "field_area_ha", "area_band", "field_lat", "field_lon",
        "distance_bjuv_km", "distance_band",
    ]
    frame[side_cols].to_parquet(sidecar_path, index=False)
    area_summary.to_csv(area_path, index=False, encoding="utf-8-sig")
    distance_summary.to_csv(distance_path, index=False, encoding="utf-8-sig")
    matrix.to_csv(matrix_path, index=False, encoding="utf-8-sig")
    discovery.to_csv(discovery_path, index=False, encoding="utf-8-sig")

    report = {
        "schema_version": "akerfro-ertor-area-logistics-c9-v0a",
        "candidate_year": int(cfg["candidate_year"]),
        "population_fields": int(len(frame)),
        "processor": cfg["processor"],
        "coordinate_source": coord_report,
        "coordinate_coverage_pct": 100.0 * float(frame["distance_bjuv_km"].notna().mean()),
        "area_coverage_pct": 100.0 * float(frame["field_area_ha"].notna().mean()),
        "policy": cfg["policy"],
        "guardrails": cfg["guardrails"],
        "c8_classes_unchanged": True,
        "artmatch_frozen_unchanged": True,
        "outputs": {
            "field_sidecar": str(sidecar_path),
            "area_enrichment": str(area_path),
            "distance_enrichment": str(distance_path),
            "area_x_distance": str(matrix_path),
            "coordinate_discovery": str(discovery_path),
        },
    }
    summary_path = out / "c9_summary.json"
    summary_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("=" * 126)
    print("ÅkerFrö – Ärter MVP v0a · C9 AREA + BJUV LOGISTICS DIAGNOSTIC")
    print("=" * 126)
    print(f"Fields: {len(frame):,} · C8 classes unchanged · ÄrtMatch frozen/read-only")
    print(
        f"Bjuv anchor: {cfg['processor']['name']} · {cfg['processor']['address']} · "
        f"{cfg['processor']['lat']:.4f}, {cfg['processor']['lon']:.4f}"
    )
    print(f"Area coverage: {report['area_coverage_pct']:.2f}%")

    print("\nAREA ENRICHMENT")
    print(area_summary.to_string(index=False, formatters={
        "historical_positive_rate_pct": lambda v: f"{v:.3f}%",
        "enrichment_vs_universe": lambda v: f"{v:.2f}x",
        "median_artmatch": lambda v: f"{v:.2f}",
    }))

    print("\nCOORDINATE SOURCE")
    if coords is None or int(coord_report.get("join_hits", 0)) == 0:
        print("  No usable field-coordinate source discovered.")
        print("  C9 area diagnostic completed; Bjuv-distance diagnostic is intentionally empty.")
    else:
        print(f"  {coord_report.get('path')}")
        print(
            f"  type={coord_report.get('type')} · join_hits={coord_report.get('join_hits'):,} · "
            f"coverage={coord_report.get('join_coverage_pct'):.2f}%"
        )
        print(f"  distance coverage in C9 product: {report['coordinate_coverage_pct']:.2f}%")

        print("\nDISTANCE-TO-BJUV ENRICHMENT")
        print(distance_summary.to_string(index=False, formatters={
            "historical_positive_rate_pct": lambda v: f"{v:.3f}%",
            "enrichment_vs_universe": lambda v: f"{v:.2f}x",
            "median_artmatch": lambda v: f"{v:.2f}",
        }))

        print("\nAREA x DISTANCE · HIGH ÄRTMATCH + ROTATION OK")
        show = matrix.sort_values(
            ["enrichment_vs_candidate_universe", "n_fields"],
            ascending=[False, False],
            kind="mergesort",
        ).head(30)
        print(show.to_string(index=False, formatters={
            "historical_positive_rate_pct": lambda v: f"{v:.3f}%",
            "enrichment_vs_candidate_universe": lambda v: f"{v:.2f}x",
        }))

    print("\nGUARDRAILS")
    for g in cfg["guardrails"]:
        print("  - " + g)

    print(f"\nField sidecar: {sidecar_path}")
    print(f"Area enrichment: {area_path}")
    print(f"Distance enrichment: {distance_path}")
    print(f"Coordinate discovery: {discovery_path}")
    print(f"Summary: {summary_path}")
    print("=" * 126)
    print("C9 AREA + LOGISTICS DIAGNOSTIC: PASS")
    print("=" * 126)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
