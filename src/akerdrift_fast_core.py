#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pure, fast ÅkerDrift V1 score functions.

This module deliberately has no GIS or parquet dependencies. Keeping the frozen
formula separate makes unit tests cheap and prevents the route/Fields2Cover
engine from entering the Fast V1 scoring path.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np


MODEL_VERSION = "akerdrift-fast-v1-rc0"


def load_model_config(path: str | Path) -> dict[str, Any]:
    config = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    validate_model_config(config)
    return config


def validate_model_config(config: dict[str, Any]) -> None:
    if config.get("model_version") != MODEL_VERSION:
        raise ValueError(f"Okänd ÅkerDrift-version: {config.get('model_version')!r}")
    geometry = config.get("geometry") or {}
    terrain = config.get("terrain") or {}
    coverage = config.get("coverage") or {}
    hydrology = config.get("hydrology") or {}
    if geometry.get("pa_units") != "m_per_m2":
        raise ValueError("P/A måste uttryckas i meter per m²")
    if not float(terrain.get("max_deg", 0)) > float(terrain.get("flat_deg", 0)):
        raise ValueError("terrain.max_deg måste vara större än terrain.flat_deg")
    if not 0 <= float(terrain.get("slope_penalty_max", -1)) <= 1:
        raise ValueError("terrain.slope_penalty_max måste ligga i [0,1]")
    slope_calc = float(coverage.get("slope_calculable_min", -1))
    slope_ok = float(coverage.get("slope_ok_min", -1))
    if not 0 <= slope_calc <= slope_ok <= 1:
        raise ValueError("Ogiltiga slope coverage-trösklar")
    if hydrology.get("include_in_score") is not False:
        raise ValueError("TWI får inte ingå i ÅkerDrift Fast V1-score")


def config_hash(config: dict[str, Any]) -> str:
    """Stable SHA-256 of the complete frozen model config."""
    validate_model_config(config)
    payload = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _finite(values: Iterable[float] | np.ndarray | None) -> np.ndarray:
    if values is None:
        return np.asarray([], dtype=np.float64)
    array = np.asarray(values, dtype=np.float64).reshape(-1)
    return array[np.isfinite(array)]


def geometry_metrics(area_m2: float, perimeter_m: float, config: dict[str, Any]) -> dict[str, float]:
    """Apply the frozen Griffel relation using SI units only."""
    area = float(area_m2)
    perimeter = float(perimeter_m)
    if not math.isfinite(area) or not math.isfinite(perimeter) or area <= 0 or perimeter <= 0:
        raise ValueError("A och P måste vara ändliga positiva tal i m² respektive meter")
    g = config["geometry"]
    pa_ratio = perimeter / area
    fe_raw = float(g["beta0"]) + float(g["beta1"]) * math.log(pa_ratio)
    fe = min(1.0, max(0.0, fe_raw))
    return {
        "area_m2": area,
        "perimeter_m": perimeter,
        "pa_ratio": pa_ratio,
        "fe_geom_raw": fe_raw,
        "fe_geom": fe,
        "geometry_score": 100.0 * fe,
    }


def slope_metrics(values_deg: Iterable[float] | np.ndarray | None, config: dict[str, Any]) -> dict[str, float | None]:
    values = _finite(values_deg)
    if values.size == 0:
        return {
            "drift_slope_difficulty": None,
            "drift_terrain_factor": None,
            "drift_slope_mean_deg": None,
            "drift_slope_p90_deg": None,
            "drift_slope_p95_deg": None,
            "drift_slope_gt5_share": None,
            "drift_slope_gt10_share": None,
            "drift_slope_gt16_7_share": None,
        }
    terrain = config["terrain"]
    flat = float(terrain["flat_deg"])
    maximum = float(terrain["max_deg"])
    difficulty = np.clip((values - flat) / (maximum - flat), 0.0, 1.0)
    d_slope = float(np.mean(difficulty))
    terrain_factor = 1.0 - float(terrain["slope_penalty_max"]) * d_slope
    return {
        "drift_slope_difficulty": d_slope,
        "drift_terrain_factor": terrain_factor,
        "drift_slope_mean_deg": float(np.mean(values)),
        "drift_slope_p90_deg": float(np.percentile(values, 90)),
        "drift_slope_p95_deg": float(np.percentile(values, 95)),
        "drift_slope_gt5_share": float(np.mean(values > 5.0)),
        "drift_slope_gt10_share": float(np.mean(values > 10.0)),
        "drift_slope_gt16_7_share": float(np.mean(values > 16.7)),
    }


def twi_metrics(
    values: Iterable[float] | np.ndarray | None,
    coverage: float,
    config: dict[str, Any],
) -> dict[str, float | str | None]:
    twi = _finite(values)
    cov = min(1.0, max(0.0, float(coverage))) if math.isfinite(float(coverage)) else 0.0
    if twi.size == 0 or cov <= 0:
        return {
            "drift_twi_mean": None,
            "drift_twi_p90_share": None,
            "drift_twi_p95_share": None,
            "drift_twi_coverage": cov,
            "drift_twi_status": "MISSING",
        }
    hydro = config["hydrology"]
    status = "OK" if cov >= float(config["coverage"].get("twi_ok_min", 0.95)) else "LIMITED"
    return {
        "drift_twi_mean": float(np.mean(twi)),
        "drift_twi_p90_share": float(np.mean(twi >= float(hydro["twi_p90"]))),
        "drift_twi_p95_share": float(np.mean(twi >= float(hydro["twi_p95"]))),
        "drift_twi_coverage": cov,
        "drift_twi_status": status,
    }


def score_field(
    *,
    area_m2: float,
    perimeter_m: float,
    slope_values_deg: Iterable[float] | np.ndarray | None,
    slope_coverage: float,
    twi_values: Iterable[float] | np.ndarray | None,
    twi_coverage: float,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Calculate one Fast V1 row; TWI is intentionally diagnostic only."""
    result: dict[str, Any] = geometry_metrics(area_m2, perimeter_m, config)
    slope = slope_metrics(slope_values_deg, config)
    twi = twi_metrics(twi_values, twi_coverage, config)
    coverage = min(1.0, max(0.0, float(slope_coverage)))
    result.update(slope)
    result.update(twi)
    result["drift_slope_coverage"] = coverage
    calculable = float(config["coverage"]["slope_calculable_min"])
    ok_min = float(config["coverage"]["slope_ok_min"])
    if coverage < calculable or slope["drift_terrain_factor"] is None:
        result["akerdrift_score"] = None
        result["drift_status"] = "INSUFFICIENT_SLOPE_COVERAGE"
    else:
        raw = 100.0 * float(result["fe_geom"]) * float(slope["drift_terrain_factor"])
        result["akerdrift_score"] = min(100.0, max(0.0, raw))
        result["drift_status"] = "OK" if coverage >= ok_min else "LIMITED_SLOPE_COVERAGE"
    result["drift_model_version"] = str(config["model_version"])
    return result
