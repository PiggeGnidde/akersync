#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Geometry-only ÅkerMinne identity mapping.

The 2025 field geometry is the reference. Administrative ids are retained as
metadata and may label a high-confidence 1:1 match, but never replace geometry.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely import make_valid

TARGET_CRS = "EPSG:3006"


@dataclass(frozen=True)
class MatchingConfig:
    strict_min_fraction: float = 0.90
    relaxed_max_fraction: float = 0.50
    tie_relative_fraction: float = 0.02

    def validate(self) -> None:
        for name, value in (
            ("strict_min_fraction", self.strict_min_fraction),
            ("relaxed_max_fraction", self.relaxed_max_fraction),
            ("tie_relative_fraction", self.tie_relative_fraction),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0,1], got {value}")
        if self.strict_min_fraction < self.relaxed_max_fraction:
            raise ValueError("strict_min_fraction must be >= relaxed_max_fraction")


def _field_key(frame: pd.DataFrame) -> pd.Series:
    return frame["blockid"].astype(str) + "|" + frame["skiftesbeteckning"].astype(str)


def _repair_geom(geom):
    if geom is None or geom.is_empty:
        return geom, False, False
    if geom.is_valid:
        return geom, False, True
    fixed = make_valid(geom)
    if fixed is None or fixed.is_empty:
        return fixed, True, False
    # Intersections should operate on polygonal area. make_valid can return a
    # GeometryCollection; its area-bearing parts are still valid for area ops.
    return fixed, True, bool(fixed.is_valid)


def prepare_fields(gdf: gpd.GeoDataFrame, role: str) -> tuple[gpd.GeoDataFrame, dict[str, int]]:
    """Validate/repair a field layer without mutating source data."""
    required = {"blockid", "skiftesbeteckning", "geometry"}
    missing = sorted(required - set(gdf.columns))
    if missing:
        raise ValueError(f"{role}: missing required columns {missing}")
    if gdf.crs is None:
        raise ValueError(f"{role}: CRS missing")
    try:
        epsg = gdf.crs.to_epsg()
    except Exception:
        epsg = None
    if epsg != 3006:
        raise ValueError(f"{role}: expected EPSG:3006, got {gdf.crs}")

    out = gdf.copy().reset_index(drop=True)
    repaired = 0
    failed = 0
    fixed_geoms = []
    for geom in out.geometry:
        fixed, was_repaired, ok = _repair_geom(geom)
        repaired += int(was_repaired)
        failed += int(not ok or fixed is None or fixed.is_empty or fixed.area <= 0)
        fixed_geoms.append(fixed)
    out.geometry = gpd.GeoSeries(fixed_geoms, crs=gdf.crs)
    out["field_key"] = _field_key(out)
    out["area_m2"] = out.geometry.area
    out["centroid_geom"] = out.geometry.centroid
    return out, {"rows": int(len(out)), "repaired": repaired, "failed": failed}


def _rank_primary(edges: pd.DataFrame, group_col: str) -> pd.Series:
    """Maximum-overlap primary; centroid distance breaks exact area ties."""
    primary = pd.Series(False, index=edges.index, dtype=bool)
    if edges.empty:
        return primary
    for _, idx in edges.groupby(group_col, sort=False).groups.items():
        sub = edges.loc[list(idx)].copy()
        max_area = float(sub["intersection_m2"].max())
        tied = sub[sub["intersection_m2"] == max_area].sort_values(
            ["centroid_distance_m", "current_field_key", "historical_field_key"],
            ascending=[True, True, True],
            kind="mergesort",
        )
        primary.loc[tied.index[0]] = True
    return primary


def _near_tie_flags(edges: pd.DataFrame, group_col: str, tie_relative_fraction: float) -> pd.Series:
    tied = pd.Series(False, index=edges.index, dtype=bool)
    if edges.empty:
        return tied
    for _, idx in edges.groupby(group_col, sort=False).groups.items():
        idx = list(idx)
        vals = edges.loc[idx, "intersection_m2"].sort_values(ascending=False)
        if len(vals) < 2:
            continue
        top = float(vals.iloc[0])
        second = float(vals.iloc[1])
        if top <= 0:
            continue
        if (top - second) / top <= tie_relative_fraction:
            tied.loc[vals.index[:2]] = True
    return tied


def compute_pair_overlaps(
    current: gpd.GeoDataFrame,
    historical: gpd.GeoDataFrame,
    cfg: MatchingConfig,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Compute every positive exact intersection between current and historical fields."""
    cfg.validate()
    cur, cur_q = prepare_fields(current, "current")
    hist, hist_q = prepare_fields(historical, "historical")

    cur_ok = cur[(cur.geometry.notna()) & (~cur.geometry.is_empty) & (cur["area_m2"] > 0)].copy()
    hist_ok = hist[(hist.geometry.notna()) & (~hist.geometry.is_empty) & (hist["area_m2"] > 0)].copy()

    # Spatial join only creates candidate pairs; exact geometry intersection is
    # calculated below and zero-area touches are retained out of the match graph.
    # Use index pairs from sjoin to avoid carrying two active geometry columns.
    cand = gpd.sjoin(
        cur_ok[["geometry"]],
        hist_ok[["geometry"]],
        how="inner",
        predicate="intersects",
    ).reset_index().rename(columns={"index": "current_idx", "index_right": "historical_idx"})

    rows: list[dict[str, Any]] = []
    for rec in cand.itertuples(index=False):
        ci = int(rec.current_idx)
        hi = int(rec.historical_idx)
        cg = cur_ok.at[ci, "geometry"]
        hg = hist_ok.at[hi, "geometry"]
        inter = cg.intersection(hg)
        area = float(inter.area) if inter is not None and not inter.is_empty else 0.0
        if area <= 0.0:
            continue
        c_area = float(cur_ok.at[ci, "area_m2"])
        h_area = float(hist_ok.at[hi, "area_m2"])
        fc = area / c_area
        fh = area / h_area
        ccent = cur_ok.at[ci, "centroid_geom"]
        hcent = hist_ok.at[hi, "centroid_geom"]
        rows.append({
            "current_idx": ci,
            "historical_idx": hi,
            "current_field_key": cur_ok.at[ci, "field_key"],
            "current_blockid": str(cur_ok.at[ci, "blockid"]),
            "current_skiftesbeteckning": str(cur_ok.at[ci, "skiftesbeteckning"]),
            "historical_field_key": hist_ok.at[hi, "field_key"],
            "historical_blockid": str(hist_ok.at[hi, "blockid"]),
            "historical_skiftesbeteckning": str(hist_ok.at[hi, "skiftesbeteckning"]),
            "intersection_m2": area,
            "current_area_m2": c_area,
            "historical_area_m2": h_area,
            "f_current": fc,
            "f_historical": fh,
            "strict_score": min(fc, fh),
            "relaxed_score": max(fc, fh),
            "centroid_distance_m": float(ccent.distance(hcent)),
            "same_admin_key": bool(cur_ok.at[ci, "field_key"] == hist_ok.at[hi, "field_key"]),
        })

    edges = pd.DataFrame(rows)
    if edges.empty:
        cols = [
            "current_idx", "historical_idx", "current_field_key", "current_blockid",
            "current_skiftesbeteckning", "historical_field_key", "historical_blockid",
            "historical_skiftesbeteckning", "intersection_m2", "current_area_m2",
            "historical_area_m2", "f_current", "f_historical", "strict_score",
            "relaxed_score", "centroid_distance_m", "same_admin_key",
            "is_current_primary", "is_historical_primary", "is_mutual_primary",
            "current_primary_tie", "historical_primary_tie", "qualifies_strict",
            "qualifies_relaxed",
        ]
        edges = pd.DataFrame(columns=cols)
    else:
        edges = edges.sort_values(
            ["current_field_key", "intersection_m2", "centroid_distance_m", "historical_field_key"],
            ascending=[True, False, True, True],
            kind="mergesort",
        ).reset_index(drop=True)
        c_primary = _rank_primary(edges, "current_field_key")
        h_primary = _rank_primary(edges, "historical_field_key")
        edges["is_current_primary"] = c_primary
        edges["is_historical_primary"] = h_primary
        edges["is_mutual_primary"] = c_primary & h_primary
        edges["current_primary_tie"] = _near_tie_flags(edges, "current_field_key", cfg.tie_relative_fraction)
        edges["historical_primary_tie"] = _near_tie_flags(edges, "historical_field_key", cfg.tie_relative_fraction)
        edges["qualifies_strict"] = edges["strict_score"] >= cfg.strict_min_fraction
        edges["qualifies_relaxed"] = edges["relaxed_score"] >= cfg.relaxed_max_fraction

    qa = {
        "current": cur_q,
        "historical": hist_q,
        "current_usable": int(len(cur_ok)),
        "historical_usable": int(len(hist_ok)),
        "candidate_pairs": int(len(cand)),
        "positive_area_pairs": int(len(edges)),
    }
    return edges, qa


def classify_current_fields(
    current: gpd.GeoDataFrame,
    historical: gpd.GeoDataFrame,
    edges: pd.DataFrame,
    cfg: MatchingConfig,
) -> pd.DataFrame:
    """Classify geometry correspondence for each 2025 reference field.

    Relaxed edges define the bipartite topology. Strict 1:1 requires min(F_C,F_H)
    while split/merge detection deliberately uses max(F_C,F_H), allowing true A/B
    partitions to remain connected.
    """
    cfg.validate()
    cur, _ = prepare_fields(current, "current")
    _hist, _ = prepare_fields(historical, "historical")

    relaxed = edges[edges["qualifies_relaxed"]].copy() if len(edges) else edges.copy()
    c_neighbors = relaxed.groupby("current_field_key")["historical_field_key"].apply(lambda x: sorted(set(x))).to_dict() if len(relaxed) else {}
    h_neighbors = relaxed.groupby("historical_field_key")["current_field_key"].apply(lambda x: sorted(set(x))).to_dict() if len(relaxed) else {}

    # Connected components in the qualifying bipartite graph.
    component_by_current: dict[str, tuple[set[str], set[str]]] = {}
    seen_c: set[str] = set()
    for start in sorted(c_neighbors):
        if start in seen_c:
            continue
        cs: set[str] = set()
        hs: set[str] = set()
        q: list[tuple[str, str]] = [("c", start)]
        while q:
            kind, key = q.pop()
            if kind == "c":
                if key in cs:
                    continue
                cs.add(key); seen_c.add(key)
                for h in c_neighbors.get(key, []):
                    if h not in hs:
                        q.append(("h", h))
            else:
                if key in hs:
                    continue
                hs.add(key)
                for c in h_neighbors.get(key, []):
                    if c not in cs:
                        q.append(("c", c))
        for c in cs:
            component_by_current[c] = (cs, hs)

    raw_by_current = edges.groupby("current_field_key") if len(edges) else None
    results: list[dict[str, Any]] = []
    for _, crow in cur.iterrows():
        ck = crow["field_key"]
        raw = raw_by_current.get_group(ck).copy() if raw_by_current is not None and ck in raw_by_current.groups else pd.DataFrame(columns=edges.columns)
        coverage_raw = float(raw["intersection_m2"].sum() / crow["area_m2"]) if len(raw) and crow["area_m2"] > 0 else 0.0
        primary = raw[raw["is_current_primary"]].copy() if len(raw) else raw
        primary_hist = str(primary.iloc[0]["historical_field_key"]) if len(primary) else None
        primary_intersection = float(primary.iloc[0]["intersection_m2"]) if len(primary) else 0.0
        primary_fc = float(primary.iloc[0]["f_current"]) if len(primary) else 0.0
        primary_fh = float(primary.iloc[0]["f_historical"]) if len(primary) else 0.0
        primary_distance = float(primary.iloc[0]["centroid_distance_m"]) if len(primary) else None
        primary_tie = bool(primary.iloc[0]["current_primary_tie"]) if len(primary) else False

        status = "unmatched"
        reason = "NO_POSITIVE_OVERLAP" if not len(raw) else "BELOW_RELAXED_THRESHOLD"
        component_current = 0
        component_historical = 0
        qualifying_edges = int((raw["qualifies_relaxed"] == True).sum()) if len(raw) else 0

        if ck in component_by_current:
            cs, hs = component_by_current[ck]
            component_current, component_historical = len(cs), len(hs)
            qraw = raw[raw["qualifies_relaxed"]]
            if component_current == 1 and component_historical == 1:
                edge = qraw.iloc[0]
                if bool(edge["current_primary_tie"]) or bool(edge["historical_primary_tie"]):
                    status, reason = "ambiguous", "PRIMARY_OVERLAP_TIE"
                elif not bool(edge["is_mutual_primary"]):
                    status, reason = "ambiguous", "NOT_MUTUAL_PRIMARY"
                elif bool(edge["qualifies_strict"]):
                    if bool(edge["same_admin_key"]):
                        status, reason = "direct_id", "STRICT_GEOMETRY_AND_SAME_ADMIN_KEY"
                    else:
                        status, reason = "one_to_one_strict", "STRICT_GEOMETRY"
                else:
                    status, reason = "one_to_one_relaxed", "RELAXED_GEOMETRY"
            elif component_current > 1 and component_historical == 1:
                status, reason = "split", "ONE_HISTORICAL_TO_MULTIPLE_CURRENT"
            elif component_current == 1 and component_historical > 1:
                status, reason = "merge", "MULTIPLE_HISTORICAL_TO_ONE_CURRENT"
            else:
                status, reason = "ambiguous", "MANY_TO_MANY_COMPONENT"

        results.append({
            "current_field_id": ck,
            "current_block_id": str(crow["blockid"]),
            "current_skiftesbeteckning": str(crow["skiftesbeteckning"]),
            "current_area_m2": float(crow["area_m2"]),
            "match_confidence": status,
            "match_reason": reason,
            "primary_historical_field_id": primary_hist,
            "primary_intersection_m2": primary_intersection,
            "primary_f_current": primary_fc,
            "primary_f_historical": primary_fh,
            "primary_centroid_distance_m": primary_distance,
            "primary_tie": primary_tie,
            "positive_overlap_edges": int(len(raw)),
            "qualifying_relaxed_edges": qualifying_edges,
            "component_current_count": component_current,
            "component_historical_count": component_historical,
            "coverage_raw": coverage_raw,
            "coverage_display": min(max(coverage_raw, 0.0), 1.0),
            "overlap_anomaly": bool(coverage_raw > 1.000001),
        })

    out = pd.DataFrame(results).sort_values("current_field_id", kind="mergesort").reset_index(drop=True)
    return out


def map_fields(
    current: gpd.GeoDataFrame,
    historical: gpd.GeoDataFrame,
    cfg: MatchingConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    cfg = cfg or MatchingConfig()
    edges, qa = compute_pair_overlaps(current, historical, cfg)
    matches = classify_current_fields(current, historical, edges, cfg)
    qa = dict(qa)
    qa["match_counts"] = {str(k): int(v) for k, v in matches["match_confidence"].value_counts(dropna=False).sort_index().items()}
    qa["coverage_quantiles"] = {
        str(q): float(matches["coverage_raw"].quantile(q))
        for q in (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99, 1.0)
    }
    qa["overlap_anomaly_count"] = int(matches["overlap_anomaly"].sum())
    return matches, edges, qa
