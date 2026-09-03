#!/usr/bin/env python3
"""Label-free 2025 prediction helpers for the bounded Rapskartan blind benchmark.

This module deliberately contains no ground-truth reader.  It may project only
identity, municipality and geometry columns from the 2025 field GeoPackage.
"""
from __future__ import annotations

import json
import math
import subprocess
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

import joblib
import numpy as np
import pandas as pd

from rapskartan_model_core import (
    SPECTRAL_NAMES, TREND_NAMES, annual_geometry_path, fetch_complete_statistics,
    sha256_bytes, sha256_file, stable_rank, temporal_feature_columns,
)
from rapskartan_model_training import predict_probability
from rapskartan_s2_pilot_core import (
    CRS_UTM33, ApiCache, STATS_URL, artifact_records, geometry_mapping,
    parse_stat_response, request_key, stat_evalscript, write_dataframe, write_json,
)
from rapskartan_v1_discovery_core import load_official_tables, official_lookup, raw_text


BLIND_CONTRACT_REL = Path("config/rapskartan_2025_blind_v1.json")
ACCEPTED_STOPC_REL = Path("analysis/rapskartan_v1/accepted_stopC_manifest.json")
TARGET_YEAR = 2025
SAFE_GEOMETRY_COLUMNS = ("arslager", "blockid", "skiftesbeteckning", "region_kod")


def load_blind_contract(root: Path) -> dict[str, Any]:
    contract = json.loads((root / BLIND_CONTRACT_REL).read_text(encoding="utf-8"))
    if contract.get("schema_version") != "rapskartan-2025-blind-contract-v1":
        raise RuntimeError("Unexpected 2025 blind contract schema")
    if int(contract.get("target_year", 0)) != TARGET_YEAR:
        raise RuntimeError("Blind contract target year is not 2025")
    if tuple(contract["geometry"]["safe_attribute_columns"]) != SAFE_GEOMETRY_COLUMNS:
        raise RuntimeError("Blind geometry projection columns changed")
    scope = contract.get("scope", {})
    if scope.get("bounded_blind_benchmark_only") is not True or scope.get("prediction_before_label_join") is not True:
        raise RuntimeError("Blind contract does not enforce bounded prediction-before-label scope")
    forbidden_false = ["model_retuning", "threshold_retuning", "sentinel1", "full_skane_prediction", "web", "deployment", "tag", "merge"]
    if any(scope.get(key) is not False for key in forbidden_false):
        raise RuntimeError("Blind contract authorizes a forbidden later phase")
    return contract


def verify_manifest_artifacts(root: Path, manifest: dict[str, Any]) -> None:
    for record in manifest.get("artifacts", []):
        path = root / record["path"]
        if not path.is_file() or path.stat().st_size != int(record["bytes"]) or sha256_file(path) != record["sha256"]:
            raise RuntimeError(f"Frozen STOPPUNKT C artifact mismatch: {record['path']}")


def verify_stop_c(root: Path, stop_c: Path) -> dict[str, Any]:
    accepted = json.loads((root / ACCEPTED_STOPC_REL).read_text(encoding="utf-8"))
    if accepted.get("status") != "PASS" or accepted.get("authorization", {}).get("go_2025_blind_test_received") is not True:
        raise RuntimeError("Repository does not contain accepted STOPPUNKT C + GO 2025 BLIND TEST")
    dataset_path = stop_c / "development_dataset_manifest.json"
    model_path = stop_c / "model_artifacts_manifest.json"
    if not dataset_path.is_file() or not model_path.is_file():
        raise RuntimeError("Accepted STOPPUNKT C manifests are missing")
    source = accepted["source_archive"]
    if sha256_file(dataset_path) != source["development_dataset_manifest_sha256"]:
        raise RuntimeError("STOPPUNKT C dataset manifest differs from accepted return")
    if sha256_file(model_path) != source["model_artifacts_manifest_sha256"]:
        raise RuntimeError("STOPPUNKT C model manifest differs from accepted return")
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    model = json.loads(model_path.read_text(encoding="utf-8"))
    if dataset.get("status") != "PASS" or model.get("status") != "PASS":
        raise RuntimeError("STOPPUNKT C manifests are not PASS")
    if model.get("feature_head") != source["feature_head"] or model.get("feature_tree") != source["feature_tree"]:
        raise RuntimeError("STOPPUNKT C repository snapshot differs from accepted return")
    verify_manifest_artifacts(stop_c, dataset)
    verify_manifest_artifacts(stop_c, model)
    frozen_contract = json.loads((stop_c / "rapskartan_model_contract_v1.json").read_text(encoding="utf-8"))
    if frozen_contract.get("blind_year_used") is not False or frozen_contract.get("status") != "PRE_BLIND_FROZEN_CANDIDATE":
        raise RuntimeError("Frozen model contract is not pre-blind")
    if frozen_contract.get("feature_head") != source["feature_head"] or frozen_contract.get("feature_tree") != source["feature_tree"]:
        raise RuntimeError("Frozen model contract repository snapshot mismatch")
    for record in frozen_contract.get("code_hashes", []):
        path = root / record["path"]
        if not path.is_file() or sha256_file(path) != record["sha256"]:
            raise RuntimeError(f"Frozen pre-blind code changed: {record['path']}")
    tree = subprocess.run(
        ["git", "show", "-s", "--format=%T", source["feature_head"]], cwd=root,
        text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if tree.returncode or tree.stdout.strip() != source["feature_tree"]:
        raise RuntimeError("Accepted pre-blind commit/tree is absent from repository history")
    return {"accepted": accepted, "dataset_manifest": dataset, "model_manifest": model, "model_contract": frozen_contract}


def current_field_id(block: Any, field: Any) -> str:
    return f"{raw_text(block)}|{raw_text(field)}"


def validate_safe_projection_columns(columns: Iterable[str]) -> None:
    allowed = set(SAFE_GEOMETRY_COLUMNS) | {"geometry"}
    unexpected = sorted(set(columns) - allowed)
    if unexpected:
        raise RuntimeError(f"BLIND_LABEL_GATE: unsafe 2025 columns were projected: {unexpected}")
    missing = sorted(allowed - set(columns))
    if missing:
        raise RuntimeError(f"2025 safe geometry is incomplete: columns={missing}")


def prepare_safe_candidates(frame: Any, contract: dict[str, Any]) -> Any:
    import geopandas as gpd

    validate_safe_projection_columns(frame.columns)
    if frame.crs is None:
        raise RuntimeError("2025 safe geometry CRS is missing")
    if set(pd.to_numeric(frame["arslager"], errors="raise").astype(int)) != {TARGET_YEAR}:
        raise RuntimeError("2025 safe geometry contains another target year")
    out = frame.to_crs(int(contract["geometry"]["crs_epsg"])).copy()
    valid = out.geometry.notna() & ~out.geometry.is_empty & out.geometry.is_valid
    out = out.loc[valid].copy()
    out["area_ha"] = out.geometry.area / 10_000.0
    out = out[out["area_ha"].between(
        float(contract["selection"]["minimum_area_ha"]),
        float(contract["selection"]["maximum_area_ha"]), inclusive="both",
    )].copy()
    out["municipality_code"] = out["region_kod"].astype(str).str[:4]
    expected_codes = {
        str(item["code"])
        for item in json.loads((Path(__file__).resolve().parents[1] / "config/akerminne_skane_municipalities.json").read_text(encoding="utf-8"))["municipalities"]
    }
    if set(out["municipality_code"]) != expected_codes:
        raise RuntimeError("Safe 2025 geometry does not cover exactly 33 Skåne municipalities")
    out["current_field_id"] = [current_field_id(a, b) for a, b in zip(out["blockid"], out["skiftesbeteckning"])]
    if out["current_field_id"].duplicated().any():
        raise RuntimeError("2025 geometry contains duplicate field identities")
    out["target_year"] = TARGET_YEAR
    out["development_field_id"] = [
        f"2025-{code}-{raw_text(block)}-{raw_text(field)}"
        for code, block, field in zip(out["municipality_code"], out["blockid"], out["skiftesbeteckning"])
    ]
    out["geographic_fold"] = [int(stable_rank("geo", code)[:8], 16) % 5 for code in out["municipality_code"]]
    return gpd.GeoDataFrame(out, geometry="geometry", crs=out.crs)


def read_safe_2025_geometry(path: Path, contract: dict[str, Any]) -> Any:
    import geopandas as gpd

    if not path.is_file() or sha256_file(path) != contract["geometry"]["expected_sha256"]:
        raise RuntimeError("Frozen 2025 geometry file/hash mismatch")
    frame = gpd.read_file(path, columns=list(SAFE_GEOMETRY_COLUMNS))
    if len(frame) != int(contract["geometry"]["expected_total_fields"]):
        raise RuntimeError(f"2025 geometry rows {len(frame)}, expected {contract['geometry']['expected_total_fields']}")
    return prepare_safe_candidates(frame, contract)


def select_blind_fields(candidates: Any, contract: dict[str, Any]) -> Any:
    pieces = []
    strata = int(contract["selection"]["area_strata"])
    maximum = int(contract["selection"]["maximum_fields_per_municipality"])
    per_stratum = int(math.ceil(maximum / strata))
    for code, part in candidates.groupby("municipality_code", sort=True):
        ordered = part.sort_values(["area_ha", "current_field_id"], kind="mergesort").copy()
        ordered["area_stratum"] = np.minimum(strata - 1, np.floor(np.arange(len(ordered)) * strata / len(ordered)).astype(int))
        for stratum, pool in ordered.groupby("area_stratum", sort=True):
            pool = pool.copy()
            pool["selection_rank"] = [stable_rank("blind-2025-v1", code, int(stratum), value) for value in pool["current_field_id"]]
            pool = pool.sort_values(["selection_rank", "current_field_id"], kind="mergesort")
            chosen = pool.head(min(per_stratum, len(pool))).copy()
            chosen["eligible_stratum_fields"] = len(pool)
            chosen["selected_stratum_fields"] = len(chosen)
            chosen["population_weight"] = float(len(pool)) / float(len(chosen))
            pieces.append(chosen)
    selected = pd.concat(pieces, ignore_index=True)
    if "geometry" in selected.columns and hasattr(candidates, "crs"):
        import geopandas as gpd
        selected = gpd.GeoDataFrame(selected, geometry="geometry", crs=candidates.crs)
    selected = selected.sort_values(["municipality_code", "area_stratum", "current_field_id"], kind="mergesort").reset_index(drop=True)
    low = int(contract["selection"]["minimum_selected_fields"])
    high = int(contract["selection"]["maximum_selected_fields"])
    if not low <= len(selected) <= high:
        raise RuntimeError(f"Blind sample size {len(selected)} outside [{low}, {high}]")
    if selected["current_field_id"].duplicated().any() or selected["municipality_code"].nunique() != 33:
        raise RuntimeError("Blind sample identities or municipality coverage are invalid")
    return selected


def selection_table(selected: Any, geometry_source: Path) -> pd.DataFrame:
    out = selected[[
        "development_field_id", "current_field_id", "target_year", "municipality_code",
        "area_ha", "area_stratum", "eligible_stratum_fields", "selected_stratum_fields",
        "population_weight", "geographic_fold",
    ]].copy()
    out["geometry_source"] = str(geometry_source.resolve())
    return out.sort_values("development_field_id", kind="mergesort").reset_index(drop=True)


def geometry_wkb_table(selected: Any) -> pd.DataFrame:
    out = selected[["development_field_id", "current_field_id", "municipality_code", "geometry"]].copy()
    out["geometry_wkb_hex"] = out.geometry.map(lambda geom: geom.wkb_hex)
    return pd.DataFrame(out.drop(columns="geometry")).sort_values("development_field_id", kind="mergesort").reset_index(drop=True)


def blind_target_period(contract: dict[str, Any]) -> tuple[str, str]:
    temporal = contract["frozen_feature_contract"]["temporal"]
    return f"2025-{temporal['start_month_day']}T00:00:00Z", f"2025-{temporal['end_exclusive_month_day']}T00:00:00Z"


def blind_cutoff_dates(contract: dict[str, Any]) -> list[date]:
    values = [date.fromisoformat(f"2025-{value}") for value in contract["frozen_feature_contract"]["temporal"]["cutoff_month_days"]]
    if values != sorted(values) or len(values) != len(set(values)):
        raise RuntimeError("Frozen blind cutoff grid is invalid")
    return values


def build_blind_stat_request(geometry: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    frozen = contract["frozen_feature_contract"]
    start, end = blind_target_period(contract)
    return {
        "input": {"bounds": {"geometry": geometry, "properties": {"crs": CRS_UTM33}}, "data": [{
            "type": frozen["sentinel2"]["collection"],
            "dataFilter": {"timeRange": {"from": start, "to": end}, "mosaickingOrder": frozen["sentinel2"]["mosaicking_order"], "maxCloudCoverage": int(frozen["sentinel2"]["max_scene_cloud_coverage_percent"])},
            "processing": {"upsampling": "BILINEAR", "downsampling": "BILINEAR", "harmonizeValues": bool(frozen["sentinel2"]["harmonize_values"])},
        }]},
        "aggregation": {"timeRange": {"from": start, "to": end}, "aggregationInterval": {"of": frozen["temporal"]["daily_aggregation_interval"], "lastIntervalBehavior": "SKIP"}, "resx": int(frozen["sentinel2"]["resolution_m"]), "resy": int(frozen["sentinel2"]["resolution_m"]), "evalscript": stat_evalscript(frozen)},
        "calculations": {"default": {"statistics": {"default": {"percentiles": {"k": frozen["statistics"]["percentiles"]}}}}},
    }


def collect_blind_statistics(selected: Any, contract: dict[str, Any], cache: ApiCache) -> tuple[pd.DataFrame, pd.DataFrame]:
    frozen = contract["frozen_feature_contract"]
    projected = selected.to_crs(32633).sort_values("development_field_id", kind="mergesort")
    rows, requests = [], []
    for number, row in enumerate(projected.itertuples(index=False), start=1):
        meta = {"development_field_id": str(row.development_field_id), "target_year": TARGET_YEAR, "municipality_code": str(row.municipality_code), "area_ha": round(float(row.area_ha), 6)}
        payload = build_blind_stat_request(geometry_mapping(row.geometry), contract)
        result = fetch_complete_statistics(cache, payload, field_id=meta["development_field_id"])
        parsed = parse_stat_response(result.body, frozen, field_meta=meta, edge_rule="ORIGINAL")
        rows.extend(parsed)
        requests.append({
            "development_field_id": meta["development_field_id"], "target_year": TARGET_YEAR,
            "endpoint": result.metadata["endpoint"], "cache_key": result.metadata["cache_key"],
            "request_sha256": result.metadata["request_sha256"], "response_sha256": result.metadata["response_sha256"],
            "response_bytes": int(result.metadata["response_bytes"]), "cache_hit": bool(result.metadata["cache_hit"]),
            "processing_units_spent": result.metadata.get("processing_units_spent"),
        })
        if number % 50 == 0 or number == len(projected):
            print(f"[BLIND-PREDICT] Sentinel-2 fields {number}/{len(projected)} · network {cache.authenticated_requests} · cache {cache.cache_hits}", flush=True)
    metrics = pd.DataFrame(rows).sort_values(["development_field_id", "acquisition_date", "interval_from"], kind="mergesort").reset_index(drop=True)
    inventory = pd.DataFrame(requests).sort_values("development_field_id", kind="mergesort").reset_index(drop=True)
    return metrics, inventory


def build_blind_temporal_features(timeseries: pd.DataFrame, selection: pd.DataFrame, contract: dict[str, Any]) -> pd.DataFrame:
    frozen = contract["frozen_feature_contract"]
    required_ts = {"development_field_id", "target_year", "acquisition_date", "data_quality_status", "valid_pixel_fraction"}
    required_sel = {"development_field_id", "target_year", "municipality_code", "geographic_fold"}
    if required_ts - set(timeseries.columns) or required_sel - set(selection.columns):
        raise RuntimeError("Blind temporal feature inputs lack required columns")
    ts = timeseries.copy()
    ts["target_year"] = pd.to_numeric(ts["target_year"], errors="raise").astype(int)
    if set(ts["target_year"]) != {TARGET_YEAR} or set(pd.to_numeric(selection["target_year"], errors="raise").astype(int)) != {TARGET_YEAR}:
        raise RuntimeError("Blind temporal feature input is not exactly target year 2025")
    ts["acquisition_date"] = pd.to_datetime(ts["acquisition_date"], errors="raise").dt.date
    for name in SPECTRAL_NAMES:
        for percentile in (10, 50, 90):
            column = f"{name}_p{percentile}"
            if column not in ts:
                raise RuntimeError(f"Blind timeseries lacks required metric {column}")
            ts[column] = pd.to_numeric(ts[column], errors="coerce")
    metric_columns = [f"{name}_p{p}" for name in SPECTRAL_NAMES for p in (10, 50, 90)]
    declared_usable = ts["data_quality_status"].isin(["VALID", "LOW_COVERAGE"])
    if ts.loc[declared_usable, metric_columns].isna().to_numpy().any():
        raise RuntimeError("Blind Sentinel-2 rows declared usable contain missing measurements")
    ts["valid_pixel_fraction"] = pd.to_numeric(ts["valid_pixel_fraction"], errors="coerce")
    selection_index = selection.set_index("development_field_id", drop=False)
    minimum = int(frozen["temporal"]["minimum_usable_observations"])
    window = int(frozen["temporal"]["trend_window_days"])
    feature_columns = temporal_feature_columns(frozen)
    rows = []
    for field_id, all_obs in ts.groupby("development_field_id", sort=True):
        meta = selection_index.loc[str(field_id)]
        for cutoff in blind_cutoff_dates(contract):
            eligible = all_obs[all_obs["acquisition_date"] <= cutoff].copy()
            usable = eligible[eligible["data_quality_status"].isin(["VALID", "LOW_COVERAGE"])].sort_values("acquisition_date")
            row = {"development_field_id": str(field_id), "target_year": TARGET_YEAR, "municipality_code": str(meta.municipality_code), "geographic_fold": int(meta.geographic_fold), "cutoff_date": cutoff.isoformat(), "latest_used_acquisition": None, "data_quality_status": "NO_DATA", "source_observation_rows": len(eligible)}
            if len(usable) < minimum:
                row.update({column: np.nan for column in feature_columns})
                rows.append(row)
                continue
            last_date = usable.iloc[-1]["acquisition_date"]
            row.update({"latest_used_acquisition": last_date.isoformat(), "data_quality_status": "USABLE", "valid_obs_count": int(len(usable)), "days_since_last_obs": int((cutoff - last_date).days), "mean_valid_pixel_fraction": float(usable["valid_pixel_fraction"].mean()), "last_valid_pixel_fraction": float(usable.iloc[-1]["valid_pixel_fraction"])})
            for name in SPECTRAL_NAMES:
                values = usable[f"{name}_p50"].to_numpy(dtype=float)
                row.update({f"{name}_last": float(values[-1]), f"{name}_median_so_far": float(np.nanmedian(values)), f"{name}_min_so_far": float(np.nanmin(values)), f"{name}_max_so_far": float(np.nanmax(values))})
            start = cutoff - timedelta(days=window)
            trend = usable[usable["acquisition_date"] >= start]
            trend_days = np.array([(value - start).days for value in trend["acquisition_date"]], dtype=float)
            for name in TREND_NAMES:
                values = trend[f"{name}_p50"].to_numpy(dtype=float)
                valid = np.isfinite(trend_days) & np.isfinite(values)
                slope = float(np.polyfit(trend_days[valid], values[valid], 1)[0]) if int(valid.sum()) >= 2 and np.ptp(trend_days[valid]) > 0 else 0.0
                latest = usable.iloc[-1]
                maximum_index = usable[f"{name}_p50"].astype(float).idxmax()
                row.update({f"{name}_slope_{window}d": slope, f"{name}_last_iqr": float(latest[f"{name}_p90"] - latest[f"{name}_p10"]), f"{name}_max_doy": int(usable.loc[maximum_index, "acquisition_date"].timetuple().tm_yday)})
            if date.fromisoformat(row["latest_used_acquisition"]) > cutoff:
                raise RuntimeError("CAUSALITY_FAILURE: blind feature used a future acquisition")
            rows.append(row)
    result = pd.DataFrame(rows).sort_values(["cutoff_date", "development_field_id"], kind="mergesort").reset_index(drop=True)
    expected = len(selection) * len(frozen["temporal"]["cutoff_month_days"])
    if len(result) != expected:
        raise RuntimeError(f"Blind temporal rows {len(result)}, expected {expected}")
    return result


def blind_prior_from_overlap_records(records: Iterable[dict[str, Any]], history_lags: int = 4) -> dict[str, Any]:
    best: dict[int, dict[str, Any]] = {}
    for record in records:
        year = int(record["history_year"])
        if year >= TARGET_YEAR:
            raise RuntimeError("BLIND_LABEL_GATE: prior contains same-year or future crop information")
        if year < TARGET_YEAR - int(history_lags):
            continue
        if float(record.get("overlap_fraction") or 0) <= float(best.get(year, {}).get("overlap_fraction") or -1):
            continue
        best[year] = dict(record)
    values, known, rape_count, last_rape_lag = {}, 0, 0, None
    for lag in range(1, int(history_lags) + 1):
        record = best.get(TARGET_YEAR - lag)
        is_known = bool(record and record.get("official_crop_name"))
        is_rape = bool(is_known and record.get("official_crop_name") == "Raps (höst)")
        values[f"prior_known_lag{lag}"] = int(is_known)
        values[f"prior_raps_lag{lag}"] = int(is_rape) if is_known else np.nan
        known += int(is_known)
        rape_count += int(is_rape)
        if is_rape and last_rape_lag is None:
            last_rape_lag = lag
    values["known_history_years"] = known
    values["raps_frequency"] = float(rape_count / known) if known else 0.0
    values["years_since_raps"] = int(last_rape_lag if last_rape_lag is not None else history_lags + 1)
    return values


def build_blind_priors(selected: Any, raw_root: Path, contract: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    import geopandas as gpd

    root = Path(__file__).resolve().parents[1]
    official, _ = load_official_tables(root)
    municipalities = {str(item["code"]): str(item["name"]) for item in json.loads((root / "config/akerminne_skane_municipalities.json").read_text(encoding="utf-8"))["municipalities"]}
    lags = 4
    minimum_overlap = 0.5
    rows, sources = [], []
    for code, targets in selected.groupby("municipality_code", sort=True):
        histories = {}
        for year in range(TARGET_YEAR - lags, TARGET_YEAR):
            path = annual_geometry_path(raw_root, year, municipalities[str(code)])
            if not path.is_file():
                raise FileNotFoundError(path)
            sources.append({"source_role": "PRIOR_HISTORY_GEOMETRY_AND_CROP", "history_year": year, "municipality_code": str(code), "path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
            history = gpd.read_file(path)
            missing = sorted({"grdkod_mar", "grdkod_und", "geometry"} - set(history.columns))
            if missing or history.crs is None:
                raise RuntimeError(f"{path.name}: invalid prior history layer; missing={missing}")
            history = history.to_crs(3006)
            history = history[history.geometry.notna() & ~history.geometry.is_empty & history.geometry.is_valid].copy()
            names = []
            for item in history.itertuples(index=False):
                found = official_lookup(official, year, item.grdkod_mar, item.grdkod_und)
                names.append(found[0] if found else None)
            history["official_crop_name"] = names
            histories[year] = history[["official_crop_name", "geometry"]]
        for target in targets.itertuples(index=False):
            records = []
            for year, history in histories.items():
                indexes = list(history.sindex.query(target.geometry, predicate="intersects"))
                if not indexes:
                    continue
                candidates = history.iloc[indexes].copy()
                candidates["_overlap"] = candidates.geometry.intersection(target.geometry).area
                best = candidates.sort_values(["_overlap", "official_crop_name"], ascending=[False, True], kind="mergesort").iloc[0]
                fraction = float(best["_overlap"]) / float(target.geometry.area)
                records.append({"history_year": year, "official_crop_name": best["official_crop_name"] if fraction >= minimum_overlap else None, "overlap_fraction": fraction})
            rows.append({"development_field_id": str(target.development_field_id), "current_field_id": str(target.current_field_id), "target_year": TARGET_YEAR, "municipality_code": str(code), **blind_prior_from_overlap_records(records, lags)})
    prior = pd.DataFrame(rows).sort_values("development_field_id", kind="mergesort").reset_index(drop=True)
    if len(prior) != len(selected) or prior["development_field_id"].duplicated().any():
        raise RuntimeError("Blind prior feature coverage is incomplete")
    source = pd.DataFrame(sources).drop_duplicates("path").sort_values(["history_year", "municipality_code"], kind="mergesort").reset_index(drop=True)
    return prior, source


def frozen_runtime_contract(stop_c: Path, base_contract: dict[str, Any]) -> dict[str, Any]:
    feature = json.loads((stop_c / "feature_contract_v1.json").read_text(encoding="utf-8"))
    model_development = json.loads((stop_c / "model_development_contract.json").read_text(encoding="utf-8"))
    if feature.get("target_label_excluded_from_features") is not True or feature.get("forbidden_target_year") != TARGET_YEAR:
        raise RuntimeError("Frozen feature contract does not preserve the blind label gate")
    base_contract = dict(base_contract)
    base_contract["frozen_feature_contract"] = {
        "temporal": model_development["temporal"], "sentinel2": feature["sentinel2"],
        "cloud_mask": feature["cloud_mask"], "statistics": model_development["statistics"],
        "prior_features": feature["prior_features"], "satellite_features": feature["satellite_features"],
        "model_arms": model_development["model"]["arms"],
    }
    return base_contract


def make_predictions(selection: pd.DataFrame, prior: pd.DataFrame, temporal: pd.DataFrame, stop_c: Path, contract: dict[str, Any]) -> pd.DataFrame:
    feature = contract["frozen_feature_contract"]
    thresholds = json.loads((stop_c / "threshold_contract_v1.json").read_text(encoding="utf-8"))
    threshold_lookup = {(row["model_arm"], row["cutoff_month_day"]): row for row in thresholds["records"]}
    base = selection.merge(prior, on=["development_field_id", "current_field_id", "target_year", "municipality_code"], validate="one_to_one")
    rows = []
    for cutoff in feature["temporal"]["cutoff_month_days"]:
        satellite = temporal[temporal["cutoff_date"].astype(str).str[5:] == cutoff].copy()
        for arm in feature["model_arms"]:
            bundle_path = stop_c / "models" / f"{arm.lower()}_{cutoff.replace('-', '')}.joblib"
            bundle = joblib.load(bundle_path)
            expected_features = feature["prior_features"] if arm == "PRIOR_ONLY" else feature["satellite_features"] if arm == "SATELLITE_ONLY" else feature["prior_features"] + feature["satellite_features"]
            if bundle.get("model_arm") != arm or bundle.get("cutoff_month_day") != cutoff or bundle.get("feature_columns") != expected_features or TARGET_YEAR in bundle.get("training_years", []):
                raise RuntimeError(f"Frozen bundle contract mismatch: {bundle_path.name}")
            frame = base.copy()
            if arm == "PRIOR_ONLY":
                frame["cutoff_date"] = f"2025-{cutoff}"
                frame["latest_used_acquisition"] = None
                frame["data_quality_status"] = "PRIOR_AVAILABLE"
                frame["valid_obs_count"] = np.nan
                frame["days_since_last_obs"] = np.nan
                frame["mean_valid_pixel_fraction"] = np.nan
            else:
                frame = frame.merge(satellite, on=["development_field_id", "target_year", "municipality_code", "geographic_fold"], validate="one_to_one", suffixes=("", "_sat"))
            probability = np.full(len(frame), np.nan, dtype=float)
            raw_probability = np.full(len(frame), np.nan, dtype=float)
            usable = np.ones(len(frame), dtype=bool) if arm == "PRIOR_ONLY" else frame["data_quality_status"].eq("USABLE").to_numpy()
            if usable.any():
                raw_probability[usable] = predict_probability(bundle["estimator"], frame.loc[usable, expected_features])
                probability[usable] = bundle["calibrator"].predict(raw_probability[usable])
            threshold = threshold_lookup[(arm, cutoff)]
            output = frame[["development_field_id", "current_field_id", "target_year", "municipality_code", "area_ha", "area_stratum", "population_weight", "cutoff_date", "latest_used_acquisition", "data_quality_status", "valid_obs_count", "days_since_last_obs", "mean_valid_pixel_fraction"]].copy()
            output["model_arm"] = arm
            output["model_family"] = bundle["model_family"]
            output["calibration"] = bundle["calibration_method"]
            output["raw_probability"] = raw_probability
            output["calibrated_probability"] = probability
            for label, key in (("p95", "precision_95"), ("p90", "precision_90")):
                spec = threshold[key]
                output[f"frozen_{label}_available"] = bool(spec["available"])
                output[f"frozen_{label}_threshold"] = float(spec["threshold"])
                output[f"predicted_at_frozen_{label}"] = usable & bool(spec["available"]) & (probability >= float(spec["threshold"]))
            for value in (0.5, 0.8, 0.9, 0.95):
                output[f"predicted_at_{str(value).replace('.', '_')}"] = usable & (probability >= value)
            rows.append(output)
    result = pd.concat(rows, ignore_index=True).sort_values(["cutoff_date", "model_arm", "development_field_id"], kind="mergesort").reset_index(drop=True)
    expected = len(selection) * len(feature["temporal"]["cutoff_month_days"]) * len(feature["model_arms"])
    if len(result) != expected:
        raise RuntimeError(f"Blind prediction rows {len(result)}, expected {expected}")
    forbidden = {"is_winter_rapeseed", "crop_group", "official_crop_name", "crop_code_raw", "crop_subcategory_raw", "dominant_crop_name", "grdkod_mar", "grdkod_und"}
    if forbidden & set(result.columns):
        raise RuntimeError("BLIND_LABEL_GATE: prediction output contains label columns")
    return result


def lock_artifacts(root: Path, relatives: Iterable[str]) -> list[dict[str, Any]]:
    return artifact_records(root, relatives)
