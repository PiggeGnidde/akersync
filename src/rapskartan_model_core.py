#!/usr/bin/env python3
"""Leakage-safe helpers for Rapskartan pre-2025 model development.

The module refuses target year 2025 and contains no blind-label reader,
Sentinel-1 integration, full-Skane exporter, web code or deployment code.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from rapskartan_s2_pilot_core import (
    CRS_UTM33, ApiCache, STATS_URL, artifact_records, geometry_mapping,
    parse_stat_response, raw_text, sha256_bytes, sha256_file, stable_json,
    stat_evalscript, write_dataframe, write_json,
)
from rapskartan_v1_discovery_core import load_official_tables, official_lookup


CONTRACT_REL = Path("config/rapskartan_model_development_v1.json")
FORBIDDEN_YEAR = 2025
REQUIRED_DEVELOPMENT_YEARS = list(range(2018, 2025))
SPECTRAL_NAMES = [
    "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12",
    "NDVI", "NDRE", "EVI2", "GNDVI", "LSWI", "NIRV", "YELLOWNESS",
]
TREND_NAMES = ["B03", "B04", "B08", "NDVI", "NDRE", "EVI2", "GNDVI", "LSWI", "NIRV", "YELLOWNESS"]


def load_model_contract(root: Path) -> dict[str, Any]:
    contract = json.loads((root / CONTRACT_REL).read_text(encoding="utf-8"))
    validate_model_contract(contract)
    return contract


def validate_model_contract(contract: dict[str, Any]) -> None:
    if contract.get("schema_version") != "rapskartan-model-development-contract-v1":
        raise RuntimeError("Unexpected model-development contract schema")
    years = [int(value) for value in contract.get("development_years", [])]
    if years != REQUIRED_DEVELOPMENT_YEARS or any(year >= FORBIDDEN_YEAR for year in years):
        raise RuntimeError("Development years must be exactly 2018-2024")
    if int(contract["blind_guard"]["forbidden_target_year"]) != FORBIDDEN_YEAR:
        raise RuntimeError("Blind-year guard must remain 2025")
    if not all(bool(value) for value in contract.get("forbidden_scope", {}).values()):
        raise RuntimeError("Every later-phase scope must remain forbidden")
    if contract["sentinel2"]["edge_rule"] != "ORIGINAL" or float(contract["sentinel2"]["negative_buffer_m"]) != 0:
        raise RuntimeError("Model V1 freezes the original field geometry selected at STOPPUNKT B")
    expected = len(years) * len(contract["selection"]["groups"]) * int(contract["selection"]["per_year_per_group"])
    if expected != int(contract["resource_guards"]["expected_selected_field_years"]):
        raise RuntimeError("Development selection count does not match the resource contract")
    if expected > int(contract["resource_guards"]["maximum_selected_field_years"]):
        raise RuntimeError("Development selection exceeds resource guard")


def model_contract_sha256(root: Path) -> str:
    return sha256_file(root / CONTRACT_REL)


def target_period(year: int, contract: dict[str, Any]) -> tuple[str, str]:
    allowed = {int(value) for value in contract["development_years"]}
    if int(year) not in allowed or int(year) >= FORBIDDEN_YEAR:
        raise RuntimeError(f"BLIND_GUARD: target year {year} is outside pre-2025 development")
    start = f"{year}-{contract['temporal']['start_month_day']}T00:00:00Z"
    end = f"{year}-{contract['temporal']['end_exclusive_month_day']}T00:00:00Z"
    return start, end


def cutoff_dates(year: int, contract: dict[str, Any]) -> list[date]:
    target_period(year, contract)
    result = [date.fromisoformat(f"{year}-{month_day}") for month_day in contract["temporal"]["cutoff_month_days"]]
    if result != sorted(result) or len(result) != len(set(result)):
        raise RuntimeError("Cutoff grid must be ordered and unique")
    return result


def build_development_stat_request(geometry: dict[str, Any], year: int, contract: dict[str, Any]) -> dict[str, Any]:
    start, end = target_period(year, contract)
    return {
        "input": {
            "bounds": {"geometry": geometry, "properties": {"crs": CRS_UTM33}},
            "data": [{
                "type": contract["sentinel2"]["collection"],
                "dataFilter": {
                    "timeRange": {"from": start, "to": end},
                    "mosaickingOrder": contract["sentinel2"]["mosaicking_order"],
                    "maxCloudCoverage": int(contract["sentinel2"]["max_scene_cloud_coverage_percent"]),
                },
                "processing": {
                    "upsampling": "BILINEAR", "downsampling": "BILINEAR",
                    "harmonizeValues": bool(contract["sentinel2"]["harmonize_values"]),
                },
            }],
        },
        "aggregation": {
            "timeRange": {"from": start, "to": end},
            "aggregationInterval": {"of": contract["temporal"]["daily_aggregation_interval"], "lastIntervalBehavior": "SKIP"},
            "resx": int(contract["sentinel2"]["resolution_m"]),
            "resy": int(contract["sentinel2"]["resolution_m"]),
            "evalscript": stat_evalscript(contract),
        },
        "calculations": {"default": {"statistics": {"default": {"percentiles": {"k": contract["statistics"]["percentiles"]}}}}},
    }


def safe_name(value: str) -> str:
    return value.lower().replace(" ", "_")


def annual_geometry_path(raw_root: Path, year: int, municipality_name: str) -> Path:
    if int(year) >= FORBIDDEN_YEAR:
        raise RuntimeError("BLIND_GUARD: model development cannot open 2025 annual geometry/labels")
    return raw_root / "akerminne_v1a" / str(year) / f"arslager_skifte_{safe_name(municipality_name)}_{year}.gpkg"


def classify_crop(name: str | None, contract: dict[str, Any]) -> str | None:
    if not name:
        return None
    selection = contract["selection"]
    if name == selection["positive_crop"]:
        return "WINTER_RAPESEED"
    if name in selection["winter_crop_controls"]:
        return "WINTER_CROP_CONTROL"
    if name in selection["spring_crop_controls"]:
        return "SPRING_CROP_CONTROL"
    return "OTHER_CROP_CONTROL"


def stable_rank(*values: Any) -> str:
    return hashlib.sha256("|".join(str(value) for value in values).encode("utf-8")).hexdigest()


def _municipality_balanced_sample(frame: pd.DataFrame, wanted: int, *, year: int, group: str) -> pd.DataFrame:
    if len(frame) < wanted:
        raise RuntimeError(f"{year} {group}: only {len(frame)} eligible fields, needs {wanted}")
    pools: dict[str, pd.DataFrame] = {}
    for code, part in frame.groupby("municipality_code", sort=True):
        ordered = part.sort_values(["area_ha", "stable_rank"], kind="mergesort").reset_index(drop=True)
        pools[str(code)] = ordered
    selected_indices: list[tuple[str, int]] = []
    round_number = 0
    codes = sorted(pools, key=lambda code: stable_rank(year, group, code))
    while len(selected_indices) < wanted:
        progressed = False
        for code in codes:
            pool = pools[code]
            if round_number >= len(pool):
                continue
            if len(selected_indices) >= wanted:
                break
            position = round(round_number * (len(pool) - 1) / max(1, wanted // max(1, len(codes))))
            position = min(len(pool) - 1, max(round_number, position))
            used = {index for chosen_code, index in selected_indices if chosen_code == code}
            while position in used and position + 1 < len(pool):
                position += 1
            if position in used:
                continue
            selected_indices.append((code, position))
            progressed = True
        if not progressed:
            break
        round_number += 1
    if len(selected_indices) != wanted:
        ordered = frame.sort_values(["area_ha", "stable_rank"], kind="mergesort")
        chosen_ids = {str(pools[code].iloc[index].development_field_id) for code, index in selected_indices}
        for row in ordered.itertuples(index=False):
            if str(row.development_field_id) in chosen_ids:
                continue
            selected_indices.append((str(row.municipality_code), int(pools[str(row.municipality_code)].index[pools[str(row.municipality_code)]["development_field_id"] == row.development_field_id][0])))
            chosen_ids.add(str(row.development_field_id))
            if len(selected_indices) == wanted:
                break
    pieces = [pools[code].iloc[[index]] for code, index in selected_indices]
    return pd.concat(pieces, ignore_index=True)


def select_development_rows(candidates: pd.DataFrame, contract: dict[str, Any]) -> pd.DataFrame:
    required = {"development_field_id", "target_year", "municipality_code", "crop_group", "area_ha", "stable_rank"}
    missing = sorted(required - set(candidates.columns))
    if missing:
        raise RuntimeError(f"Development candidates lack columns: {missing}")
    rows = []
    wanted = int(contract["selection"]["per_year_per_group"])
    groups = list(contract["selection"]["groups"])
    for year in contract["development_years"]:
        for group in groups:
            population = candidates[(candidates["target_year"].astype(int) == int(year)) & (candidates["crop_group"] == group)]
            chosen = _municipality_balanced_sample(population, wanted, year=int(year), group=str(group)).copy()
            chosen["eligible_population"] = len(population)
            chosen["selected_population"] = len(chosen)
            chosen["population_weight"] = float(len(population)) / float(len(chosen))
            rows.append(chosen)
    result = pd.concat(rows, ignore_index=True).sort_values(
        ["target_year", "crop_group", "municipality_code", "area_ha", "development_field_id"], kind="mergesort",
    ).reset_index(drop=True)
    expected = int(contract["resource_guards"]["expected_selected_field_years"])
    if len(result) != expected or result["development_field_id"].duplicated().any():
        raise RuntimeError(f"Development selection is not the contracted unique {expected} rows")
    if (result["target_year"].astype(int) >= FORBIDDEN_YEAR).any():
        raise RuntimeError("BLIND_GUARD: selected development rows contain 2025")
    return result


def select_development_year(candidates: pd.DataFrame, year: int, contract: dict[str, Any]) -> pd.DataFrame:
    if int(year) not in {int(value) for value in contract["development_years"]}:
        raise RuntimeError(f"Year {year} is not in the development contract")
    if set(pd.to_numeric(candidates["target_year"], errors="raise").astype(int)) != {int(year)}:
        raise RuntimeError("Year sampler received mixed target years")
    rows = []
    wanted = int(contract["selection"]["per_year_per_group"])
    for group in contract["selection"]["groups"]:
        population = candidates[candidates["crop_group"] == group]
        chosen = _municipality_balanced_sample(population, wanted, year=int(year), group=str(group)).copy()
        chosen["eligible_population"] = len(population)
        chosen["selected_population"] = len(chosen)
        chosen["population_weight"] = float(len(population)) / float(len(chosen))
        rows.append(chosen)
    return pd.concat(rows, ignore_index=True).sort_values(
        ["crop_group", "municipality_code", "area_ha", "development_field_id"], kind="mergesort",
    ).reset_index(drop=True)


def prior_from_overlap_records(target_year: int, records: Iterable[dict[str, Any]], history_lags: int = 4) -> dict[str, Any]:
    if int(target_year) >= FORBIDDEN_YEAR:
        raise RuntimeError("BLIND_GUARD: prior target year cannot be 2025 in development")
    best: dict[int, dict[str, Any]] = {}
    for record in records:
        year = int(record["history_year"])
        if year >= int(target_year):
            raise RuntimeError("Prior overlap contains same-year or future crop information")
        if year < int(target_year) - int(history_lags):
            continue
        if float(record.get("overlap_fraction") or 0) <= float(best.get(year, {}).get("overlap_fraction") or -1):
            continue
        best[year] = dict(record)
    values: dict[str, Any] = {}
    known = 0
    rape_count = 0
    last_rape_lag: int | None = None
    for lag in range(1, int(history_lags) + 1):
        rec = best.get(int(target_year) - lag)
        is_known = bool(rec and rec.get("official_crop_name"))
        is_rape = bool(is_known and rec.get("official_crop_name") == "Raps (höst)")
        values[f"prior_known_lag{lag}"] = int(is_known)
        values[f"prior_raps_lag{lag}"] = int(is_rape) if is_known else np.nan
        if is_known:
            known += 1
            rape_count += int(is_rape)
        if is_rape and last_rape_lag is None:
            last_rape_lag = lag
    values["known_history_years"] = known
    values["raps_frequency"] = float(rape_count / known) if known else 0.0
    values["years_since_raps"] = int(last_rape_lag if last_rape_lag is not None else history_lags + 1)
    return values


def _slope(days: np.ndarray, values: np.ndarray) -> float:
    valid = np.isfinite(days) & np.isfinite(values)
    if int(valid.sum()) < 2 or np.ptp(days[valid]) <= 0:
        return 0.0
    return float(np.polyfit(days[valid], values[valid], 1)[0])


def temporal_feature_columns(contract: dict[str, Any]) -> list[str]:
    columns = [
        "valid_obs_count", "days_since_last_obs", "mean_valid_pixel_fraction", "last_valid_pixel_fraction",
    ]
    for name in SPECTRAL_NAMES:
        columns.extend([f"{name}_last", f"{name}_median_so_far", f"{name}_min_so_far", f"{name}_max_so_far"])
    for name in TREND_NAMES:
        columns.extend([f"{name}_slope_{int(contract['temporal']['trend_window_days'])}d", f"{name}_last_iqr", f"{name}_max_doy"])
    return columns


def build_temporal_features(timeseries: pd.DataFrame, selection: pd.DataFrame, contract: dict[str, Any]) -> pd.DataFrame:
    required_ts = {"development_field_id", "target_year", "acquisition_date", "data_quality_status", "valid_pixel_fraction"}
    required_sel = {"development_field_id", "target_year", "municipality_code", "geographic_fold"}
    if required_ts - set(timeseries.columns) or required_sel - set(selection.columns):
        raise RuntimeError("Temporal feature inputs lack required columns")
    ts = timeseries.copy()
    ts["target_year"] = pd.to_numeric(ts["target_year"], errors="raise").astype(int)
    if (ts["target_year"] >= FORBIDDEN_YEAR).any() or (pd.to_numeric(selection["target_year"]) >= FORBIDDEN_YEAR).any():
        raise RuntimeError("BLIND_GUARD: temporal feature input contains 2025")
    ts["acquisition_date"] = pd.to_datetime(ts["acquisition_date"], errors="raise").dt.date
    for name in SPECTRAL_NAMES:
        for percentile in (10, 50, 90):
            column = f"{name}_p{percentile}"
            if column not in ts:
                raise RuntimeError(f"Timeseries lacks required metric {column}")
            ts[column] = pd.to_numeric(ts[column], errors="coerce")
    ts["valid_pixel_fraction"] = pd.to_numeric(ts["valid_pixel_fraction"], errors="coerce")
    selection_index = selection.set_index("development_field_id", drop=False)
    rows: list[dict[str, Any]] = []
    minimum = int(contract["temporal"]["minimum_usable_observations"])
    window = int(contract["temporal"]["trend_window_days"])
    for field_id, all_obs in ts.groupby("development_field_id", sort=True):
        meta = selection_index.loc[str(field_id)]
        year = int(meta.target_year)
        if set(all_obs["target_year"].astype(int)) != {year}:
            raise RuntimeError(f"Field {field_id} mixes target years")
        for cutoff in cutoff_dates(year, contract):
            eligible = all_obs[all_obs["acquisition_date"] <= cutoff].copy()
            usable = eligible[eligible["data_quality_status"].isin(["VALID", "LOW_COVERAGE"])].sort_values("acquisition_date")
            row: dict[str, Any] = {
                "development_field_id": str(field_id), "target_year": year,
                "municipality_code": str(meta.municipality_code), "geographic_fold": int(meta.geographic_fold),
                "cutoff_date": cutoff.isoformat(), "latest_used_acquisition": None,
                "data_quality_status": "NO_DATA", "source_observation_rows": len(eligible),
            }
            if len(usable) < minimum:
                for column in temporal_feature_columns(contract):
                    row[column] = np.nan
                rows.append(row)
                continue
            last_date = usable.iloc[-1]["acquisition_date"]
            row.update({
                "latest_used_acquisition": last_date.isoformat(), "data_quality_status": "USABLE",
                "valid_obs_count": int(len(usable)), "days_since_last_obs": int((cutoff - last_date).days),
                "mean_valid_pixel_fraction": float(usable["valid_pixel_fraction"].mean()),
                "last_valid_pixel_fraction": float(usable.iloc[-1]["valid_pixel_fraction"]),
            })
            for name in SPECTRAL_NAMES:
                values = usable[f"{name}_p50"].to_numpy(dtype=float)
                row[f"{name}_last"] = float(values[-1])
                row[f"{name}_median_so_far"] = float(np.nanmedian(values))
                row[f"{name}_min_so_far"] = float(np.nanmin(values))
                row[f"{name}_max_so_far"] = float(np.nanmax(values))
            start = cutoff - timedelta(days=window)
            trend = usable[usable["acquisition_date"] >= start]
            trend_days = np.array([(value - start).days for value in trend["acquisition_date"]], dtype=float)
            for name in TREND_NAMES:
                trend_values = trend[f"{name}_p50"].to_numpy(dtype=float)
                row[f"{name}_slope_{window}d"] = _slope(trend_days, trend_values)
                latest = usable.iloc[-1]
                row[f"{name}_last_iqr"] = float(latest[f"{name}_p90"] - latest[f"{name}_p10"])
                maximum_index = usable[f"{name}_p50"].astype(float).idxmax()
                row[f"{name}_max_doy"] = int(usable.loc[maximum_index, "acquisition_date"].timetuple().tm_yday)
            if date.fromisoformat(str(row["latest_used_acquisition"])) > cutoff:
                raise RuntimeError("CAUSALITY_FAILURE: feature row used a future acquisition")
            rows.append(row)
    result = pd.DataFrame(rows).sort_values(["cutoff_date", "target_year", "development_field_id"], kind="mergesort").reset_index(drop=True)
    expected = len(selection) * len(contract["temporal"]["cutoff_month_days"])
    if len(result) != expected:
        raise RuntimeError(f"Temporal feature rows {len(result)}, expected {expected}")
    return result


def development_field_meta(row: Any) -> dict[str, Any]:
    return {
        "development_field_id": str(row.development_field_id),
        "target_year": int(row.target_year),
        "municipality_code": str(row.municipality_code),
        "area_ha": round(float(row.area_ha), 6),
    }


def collect_development_statistics(selected: Any, contract: dict[str, Any], cache: ApiCache) -> tuple[pd.DataFrame, pd.DataFrame]:
    projected = selected.to_crs(32633).sort_values("development_field_id", kind="mergesort")
    rows: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []
    for number, row in enumerate(projected.itertuples(index=False), start=1):
        meta = development_field_meta(row)
        payload = build_development_stat_request(geometry_mapping(row.geometry), int(row.target_year), contract)
        result = cache.fetch(STATS_URL, payload, response_suffix=".json", accept="application/json")
        parsed = parse_stat_response(result.body, contract, field_meta=meta, edge_rule="ORIGINAL")
        for item in parsed:
            item["development_field_id"] = item.pop("development_field_id")
        rows.extend(parsed)
        requests.append({
            "development_field_id": meta["development_field_id"], "target_year": meta["target_year"],
            "endpoint": result.metadata["endpoint"], "cache_key": result.metadata["cache_key"],
            "request_sha256": result.metadata["request_sha256"], "response_sha256": result.metadata["response_sha256"],
            "response_bytes": int(result.metadata["response_bytes"]), "cache_hit": bool(result.metadata["cache_hit"]),
            "processing_units_spent": result.metadata.get("processing_units_spent"),
        })
        if number % 50 == 0 or number == len(projected):
            print(f"[DATASET] Sentinel-2 fields {number}/{len(projected)} · network {cache.authenticated_requests} · cache {cache.cache_hits}", flush=True)
    metrics = pd.DataFrame(rows).sort_values(
        ["development_field_id", "acquisition_date", "interval_from"], kind="mergesort",
    ).reset_index(drop=True)
    inventory = pd.DataFrame(requests).sort_values("development_field_id", kind="mergesort").reset_index(drop=True)
    return metrics, inventory


def dataset_artifact_manifest(root: Path, relative_paths: Iterable[str]) -> list[dict[str, Any]]:
    return artifact_records(root, relative_paths)
