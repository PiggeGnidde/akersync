#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from akerminne_mapping_core import MatchingConfig, map_fields

SCHEMA_VERSION = "akerminne-analysis-v1a"


def raw_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    s = str(value).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s or None


def unknown_crop_label(code: str | None, year: int) -> str:
    return f"Okänd grödkod {code if code is not None else 'saknas'} ({year})"


@dataclass(frozen=True)
class CropRecord:
    crop_name: str
    crop_group: str | None = None
    source_url: str | None = None
    source_date: str | None = None


class CropRegistry:
    """Year-specific crop lookup. Never falls back across years."""

    def __init__(self, by_year: dict[int, dict[tuple[str | None, str | None], CropRecord]] | None = None):
        self.by_year = by_year or {}

    @staticmethod
    def _candidate_keys(code: str | None, sub: str | None) -> list[tuple[str | None, str | None]]:
        keys = [(code, sub)]
        if sub is not None:
            keys.append((code, None))
        return keys

    def lookup(self, year: int, code: Any, subcategory: Any) -> CropRecord | None:
        c = raw_text(code)
        s = raw_text(subcategory)
        table = self.by_year.get(int(year), {})
        for key in self._candidate_keys(c, s):
            if key in table:
                return table[key]
        return None

    @classmethod
    def from_directory(cls, directory: Path) -> tuple["CropRegistry", dict[str, Any]]:
        by_year: dict[int, dict[tuple[str | None, str | None], CropRecord]] = {}
        loaded: dict[str, Any] = {}
        if not directory.exists():
            return cls(), {"directory": str(directory), "loaded_years": [], "missing_directory": True}
        for path in sorted(directory.glob("*.csv")):
            year_digits = "".join(ch for ch in path.stem if ch.isdigit())
            year = None
            for i in range(max(0, len(year_digits) - 3)):
                candidate = year_digits[i:i + 4]
                if candidate.isdigit() and 2015 <= int(candidate) <= 2025:
                    year = int(candidate)
                    break
            if year is None:
                continue
            frame = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
            aliases = {
                "crop_code_raw": ["crop_code_raw", "crop_code", "grdkod_mar"],
                "crop_subcategory_raw": ["crop_subcategory_raw", "crop_subcategory", "grdkod_und"],
                "crop_name": ["crop_name", "crop_name_official", "name"],
                "crop_group": ["crop_group", "group"],
                "source_url": ["source_url"],
                "source_date": ["source_date"],
            }
            resolved: dict[str, str | None] = {}
            for target, names in aliases.items():
                resolved[target] = next((n for n in names if n in frame.columns), None)
            if resolved["crop_code_raw"] is None or resolved["crop_name"] is None:
                raise ValueError(f"{path}: kräver crop_code_raw/crop_code och crop_name")
            table: dict[tuple[str | None, str | None], CropRecord] = {}
            for _, row in frame.iterrows():
                code = raw_text(row[resolved["crop_code_raw"]])
                sub = raw_text(row[resolved["crop_subcategory_raw"]]) if resolved["crop_subcategory_raw"] else None
                name = raw_text(row[resolved["crop_name"]])
                if code is None or name is None:
                    continue
                key = (code, sub)
                if key in table and table[key].crop_name != name:
                    raise ValueError(f"{path}: motstridig mappning för {key}")
                table[key] = CropRecord(
                    crop_name=name,
                    crop_group=raw_text(row[resolved["crop_group"]]) if resolved["crop_group"] else None,
                    source_url=raw_text(row[resolved["source_url"]]) if resolved["source_url"] else None,
                    source_date=raw_text(row[resolved["source_date"]]) if resolved["source_date"] else None,
                )
            by_year[year] = table
            loaded[str(year)] = {"path": str(path), "rows": len(table)}
        return cls(by_year), {"directory": str(directory), "loaded_years": sorted(by_year), "files": loaded}


def _history_metadata(historical: gpd.GeoDataFrame) -> pd.DataFrame:
    h = historical.copy().reset_index(drop=True)
    required = ["blockid", "skiftesbeteckning", "grdkod_mar"]
    missing = [c for c in required if c not in h.columns]
    if missing:
        raise ValueError(f"historical: missing required columns {missing}")
    if "grdkod_und" not in h.columns:
        h["grdkod_und"] = None
    h["historical_idx"] = h.index.astype(int)
    h["historical_field_id"] = h["blockid"].astype(str) + "|" + h["skiftesbeteckning"].astype(str)
    return h[["historical_idx", "historical_field_id", "blockid", "skiftesbeteckning", "grdkod_mar", "grdkod_und"]]


def components_from_edges(
    edges: pd.DataFrame,
    historical: gpd.GeoDataFrame,
    history_year: int,
    municipality: str,
    reference_year: int = 2025,
    registry: CropRegistry | None = None,
) -> pd.DataFrame:
    registry = registry or CropRegistry()
    cols = [
        "schema_version", "municipality", "reference_year", "history_year",
        "current_field_id", "current_block_id", "current_skiftesbeteckning",
        "historical_field_id", "historical_block_id", "historical_skiftesbeteckning",
        "crop_code_raw", "crop_subcategory_raw", "crop_name", "crop_group", "crop_known",
        "intersection_m2", "share_current", "share_historical", "strict_score", "relaxed_score",
        "same_admin_key", "is_current_primary", "is_historical_primary", "is_mutual_primary",
    ]
    if edges.empty:
        return pd.DataFrame(columns=cols)
    meta = _history_metadata(historical).rename(columns={
        "blockid": "meta_blockid", "skiftesbeteckning": "meta_skifte",
    })
    merged = edges.merge(meta, on="historical_idx", how="left", validate="many_to_one")
    if merged["historical_field_id"].isna().any():
        raise RuntimeError("Historisk metadata kunde inte kopplas till alla overlap-edges")
    rows: list[dict[str, Any]] = []
    for row in merged.itertuples(index=False):
        code = raw_text(row.grdkod_mar)
        sub = raw_text(row.grdkod_und)
        rec = registry.lookup(history_year, code, sub)
        rows.append({
            "schema_version": SCHEMA_VERSION,
            "municipality": municipality,
            "reference_year": int(reference_year),
            "history_year": int(history_year),
            "current_field_id": str(row.current_field_key),
            "current_block_id": str(row.current_blockid),
            "current_skiftesbeteckning": str(row.current_skiftesbeteckning),
            "historical_field_id": str(row.historical_field_id),
            "historical_block_id": str(row.historical_blockid),
            "historical_skiftesbeteckning": str(row.historical_skiftesbeteckning),
            "crop_code_raw": code,
            "crop_subcategory_raw": sub,
            "crop_name": rec.crop_name if rec else unknown_crop_label(code, history_year),
            "crop_group": rec.crop_group if rec else "UNKNOWN",
            "crop_known": bool(rec),
            "intersection_m2": float(row.intersection_m2),
            "share_current": float(row.f_current),
            "share_historical": float(row.f_historical),
            "strict_score": float(row.strict_score),
            "relaxed_score": float(row.relaxed_score),
            "same_admin_key": bool(row.same_admin_key),
            "is_current_primary": bool(row.is_current_primary),
            "is_historical_primary": bool(row.is_historical_primary),
            "is_mutual_primary": bool(row.is_mutual_primary),
        })
    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values(["current_field_id", "intersection_m2", "historical_field_id"], ascending=[True, False, True], kind="mergesort").reset_index(drop=True)


def summarize_history_year(
    matches: pd.DataFrame,
    components: pd.DataFrame,
    history_year: int,
    municipality: str,
    reference_year: int = 2025,
) -> pd.DataFrame:
    by_current = {k: v.copy() for k, v in components.groupby("current_field_id", sort=False)} if len(components) else {}
    rows: list[dict[str, Any]] = []
    for m in matches.itertuples(index=False):
        fid = str(m.current_field_id)
        c = by_current.get(fid, pd.DataFrame(columns=components.columns))
        covered_area = float(c["intersection_m2"].sum()) if len(c) else 0.0
        current_area = float(m.current_area_m2)
        coverage_raw = covered_area / current_area if current_area > 0 else 0.0
        dominant_code = None
        dominant_sub = None
        dominant_name = None
        dominant_group = None
        dominant_area = 0.0
        dominant_known = False
        crop_count_raw = 0
        if len(c):
            x = c.copy()
            x["_code"] = x["crop_code_raw"].fillna("<NULL>")
            x["_sub"] = x["crop_subcategory_raw"].fillna("<NULL>")
            crop_groups = (
                x.groupby(["_code", "_sub", "crop_name", "crop_group", "crop_known"], dropna=False, as_index=False)["intersection_m2"]
                .sum()
                .sort_values(["intersection_m2", "_code", "_sub"], ascending=[False, True, True], kind="mergesort")
            )
            crop_count_raw = int(len(crop_groups))
            d = crop_groups.iloc[0]
            dominant_code = None if d["_code"] == "<NULL>" else str(d["_code"])
            dominant_sub = None if d["_sub"] == "<NULL>" else str(d["_sub"])
            dominant_name = str(d["crop_name"])
            dominant_group = str(d["crop_group"])
            dominant_area = float(d["intersection_m2"])
            dominant_known = bool(d["crop_known"])
        dominant_share = dominant_area / current_area if current_area > 0 else 0.0
        flags: list[str] = []
        if getattr(m, "match_confidence", None) == "split":
            flags.append("HISTORICAL_SPLIT")
        elif getattr(m, "match_confidence", None) == "merge":
            flags.append("HISTORICAL_MERGE_PATTERN")
        elif getattr(m, "match_confidence", None) in ("ambiguous", "one_to_one_relaxed"):
            flags.append("BOUNDARY_CHANGED")
        if coverage_raw > 1.000001:
            flags.append("DUPLICATE_OVERLAP")
        if len(c) and not c["crop_known"].all():
            flags.append("UNKNOWN_CODE")
        status = "NO_PUBLIC_MATCH" if len(c) == 0 else ("OVERLAP_ANOMALY" if coverage_raw > 1.000001 else "RAW_PENDING_THRESHOLDS")
        rows.append({
            "schema_version": SCHEMA_VERSION,
            "municipality": municipality,
            "reference_year": int(reference_year),
            "history_year": int(history_year),
            "current_field_id": fid,
            "current_block_id": str(m.current_block_id),
            "current_skiftesbeteckning": str(m.current_skiftesbeteckning),
            "current_area_m2": current_area,
            "covered_area_m2": covered_area,
            "coverage_raw": coverage_raw,
            "coverage_display": min(max(coverage_raw, 0.0), 1.0),
            "dominant_crop_code_raw": dominant_code,
            "dominant_crop_subcategory_raw": dominant_sub,
            "dominant_crop_name": dominant_name,
            "dominant_crop_group": dominant_group,
            "dominant_crop_known": dominant_known,
            "dominant_crop_share": dominant_share,
            "component_count": int(len(c)),
            "crop_count_raw": crop_count_raw,
            "status": status,
            "reason_flags": ";".join(flags),
            "identity_match_confidence": str(getattr(m, "match_confidence", "")),
            "identity_match_reason": str(getattr(m, "match_reason", "")),
            "primary_historical_field_id": getattr(m, "primary_historical_field_id", None),
            "primary_f_current": float(getattr(m, "primary_f_current", 0.0) or 0.0),
            "primary_f_historical": float(getattr(m, "primary_f_historical", 0.0) or 0.0),
            "overlap_anomaly": bool(coverage_raw > 1.000001),
        })
    return pd.DataFrame(rows).sort_values("current_field_id", kind="mergesort").reset_index(drop=True)


def build_history_year(
    current: gpd.GeoDataFrame,
    historical: gpd.GeoDataFrame,
    history_year: int,
    municipality: str,
    matching_cfg: MatchingConfig | None = None,
    registry: CropRegistry | None = None,
    reference_year: int = 2025,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    matches, edges, qa = map_fields(current, historical, matching_cfg or MatchingConfig())
    comps = components_from_edges(edges, historical, history_year, municipality, reference_year, registry)
    summary = summarize_history_year(matches, comps, history_year, municipality, reference_year)
    qa = dict(qa)
    qa["unknown_component_rows"] = int((~comps["crop_known"]).sum()) if len(comps) else 0
    qa["unknown_current_fields"] = int(summary["reason_flags"].str.contains("UNKNOWN_CODE", regex=False).sum()) if len(summary) else 0
    return summary, comps, edges, qa


def build_reference_year(
    current: gpd.GeoDataFrame,
    municipality: str,
    registry: CropRegistry | None = None,
    reference_year: int = 2025,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    registry = registry or CropRegistry()
    g = current.copy().reset_index(drop=True)
    required = ["blockid", "skiftesbeteckning", "grdkod_mar", "geometry"]
    missing = [c for c in required if c not in g.columns]
    if missing:
        raise ValueError(f"current: missing required columns {missing}")
    if "grdkod_und" not in g.columns:
        g["grdkod_und"] = None
    rows_s: list[dict[str, Any]] = []
    rows_c: list[dict[str, Any]] = []
    for _, row in g.iterrows():
        fid = f"{raw_text(row['blockid'])}|{raw_text(row['skiftesbeteckning'])}"
        area = float(row.geometry.area)
        code = raw_text(row["grdkod_mar"])
        sub = raw_text(row["grdkod_und"])
        rec = registry.lookup(reference_year, code, sub)
        name = rec.crop_name if rec else unknown_crop_label(code, reference_year)
        group = rec.crop_group if rec else "UNKNOWN"
        rows_c.append({
            "schema_version": SCHEMA_VERSION, "municipality": municipality,
            "reference_year": reference_year, "history_year": reference_year,
            "current_field_id": fid, "current_block_id": raw_text(row["blockid"]),
            "current_skiftesbeteckning": raw_text(row["skiftesbeteckning"]),
            "historical_field_id": fid, "historical_block_id": raw_text(row["blockid"]),
            "historical_skiftesbeteckning": raw_text(row["skiftesbeteckning"]),
            "crop_code_raw": code, "crop_subcategory_raw": sub, "crop_name": name,
            "crop_group": group, "crop_known": bool(rec), "intersection_m2": area,
            "share_current": 1.0, "share_historical": 1.0, "strict_score": 1.0,
            "relaxed_score": 1.0, "same_admin_key": True, "is_current_primary": True,
            "is_historical_primary": True, "is_mutual_primary": True,
        })
        flags = [] if rec else ["UNKNOWN_CODE"]
        rows_s.append({
            "schema_version": SCHEMA_VERSION, "municipality": municipality,
            "reference_year": reference_year, "history_year": reference_year,
            "current_field_id": fid, "current_block_id": raw_text(row["blockid"]),
            "current_skiftesbeteckning": raw_text(row["skiftesbeteckning"]),
            "current_area_m2": area, "covered_area_m2": area, "coverage_raw": 1.0,
            "coverage_display": 1.0, "dominant_crop_code_raw": code,
            "dominant_crop_subcategory_raw": sub, "dominant_crop_name": name,
            "dominant_crop_group": group, "dominant_crop_known": bool(rec),
            "dominant_crop_share": 1.0, "component_count": 1, "crop_count_raw": 1,
            "status": "RAW_PENDING_THRESHOLDS", "reason_flags": ";".join(flags),
            "identity_match_confidence": "reference_year", "identity_match_reason": "REFERENCE_YEAR_SELF",
            "primary_historical_field_id": fid, "primary_f_current": 1.0,
            "primary_f_historical": 1.0, "overlap_anomaly": False,
        })
    return (
        pd.DataFrame(rows_s).sort_values("current_field_id").reset_index(drop=True),
        pd.DataFrame(rows_c).sort_values("current_field_id").reset_index(drop=True),
        {"current_fields": len(g), "unknown_current_fields": sum("UNKNOWN_CODE" in r["reason_flags"] for r in rows_s)},
    )


def component_share_distribution(components: pd.DataFrame) -> dict[str, Any]:
    if components.empty:
        return {"rows": 0}
    s = components["share_current"].astype(float)
    return {
        "rows": int(len(s)),
        "p01": float(s.quantile(.01)), "p05": float(s.quantile(.05)),
        "p10": float(s.quantile(.10)), "p50": float(s.quantile(.50)),
        "below_0_1pct": int((s < .001).sum()), "below_0_5pct": int((s < .005).sum()),
        "below_1pct": int((s < .01).sum()), "below_2pct": int((s < .02).sum()),
        "below_5pct": int((s < .05).sum()),
    }
