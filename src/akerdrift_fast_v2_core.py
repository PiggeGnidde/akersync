#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Frozen, lightweight evaluator for route-calibrated ÅkerDrift Fast V2.

The fitted model is an additive piecewise-linear (hinge) ridge model.  Model
fitting happens in ``46_calibrate_akerdrift_fast_v2.py``; production scoring
only needs NumPy and the exported JSON config.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np


MODEL_VERSION = "akerdrift-fast-v2-routecal-rc0"


def load_model_config(path: str | Path) -> dict[str, Any]:
    config = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    validate_model_config(config)
    return config


def validate_model_config(config: Mapping[str, Any]) -> None:
    if config.get("model_version") != MODEL_VERSION:
        raise ValueError(f"Okänd ÅkerDrift Fast V2-version: {config.get('model_version')!r}")
    model = config.get("geometry_model") or {}
    features = model.get("continuous_features") or []
    if not features or not model.get("binary_features"):
        raise ValueError("Fast V2-config saknar modellfeatures")
    knots = model.get("knots") or {}
    ranges = model.get("clip_ranges") or {}
    expected_basis = 0
    for feature in features:
        values = knots.get(feature)
        limits = ranges.get(feature)
        if not isinstance(values, list) or not values:
            raise ValueError(f"Fast V2-config saknar knutar för {feature}")
        if not isinstance(limits, list) or len(limits) != 2 or limits[0] >= limits[1]:
            raise ValueError(f"Fast V2-config har ogiltigt intervall för {feature}")
        expected_basis += 1 + len(values)
    expected_basis += len(model["binary_features"])
    for name in ("basis_mean", "basis_scale", "coefficients"):
        values = model.get(name)
        if not isinstance(values, list) or len(values) != expected_basis:
            raise ValueError(f"Fast V2-config har fel längd på {name}")
    if any(float(value) <= 0 for value in model["basis_scale"]):
        raise ValueError("Fast V2-config kräver positiva basis_scale")
    if not math.isfinite(float(model.get("intercept", math.nan))):
        raise ValueError("Fast V2-config saknar ändlig intercept")


def feature_values(
    *,
    fast_geometry_score: float,
    area_ha: float,
    rectangularity: float,
    compactness: float,
    erl_m: float,
    hole_count: int | float,
) -> dict[str, float]:
    raw = {
        "fast_geometry_score": float(fast_geometry_score),
        "log_area_ha": math.log(float(area_ha)),
        "rectangularity": float(rectangularity),
        "compactness": float(compactness),
        "log_erl_m": math.log(float(erl_m)),
        "has_holes": float(float(hole_count) > 0),
        "holes_capped_5": min(5.0, max(0.0, float(hole_count))),
    }
    if not all(math.isfinite(value) for value in raw.values()):
        raise ValueError("Fast V2-features måste vara ändliga")
    if float(area_ha) <= 0 or float(erl_m) <= 0:
        raise ValueError("area_ha och erl_m måste vara positiva")
    return raw


def geometry_score(features: Mapping[str, float], config: Mapping[str, Any]) -> float:
    """Evaluate the frozen hinge basis and return a bounded geometry score."""
    validate_model_config(config)
    model = config["geometry_model"]
    basis: list[float] = []
    for name in model["continuous_features"]:
        value = float(features[name])
        low, high = (float(item) for item in model["clip_ranges"][name])
        value = min(high, max(low, value))
        basis.append(value)
        basis.extend(max(0.0, value - float(knot)) for knot in model["knots"][name])
    basis.extend(float(features[name]) for name in model["binary_features"])
    vector = np.asarray(basis, dtype=np.float64)
    mean = np.asarray(model["basis_mean"], dtype=np.float64)
    scale = np.asarray(model["basis_scale"], dtype=np.float64)
    coefficients = np.asarray(model["coefficients"], dtype=np.float64)
    prediction = float(model["intercept"]) + float(np.dot((vector - mean) / scale, coefficients))
    return min(100.0, max(0.0, prediction))


def score_from_metrics(
    *,
    fast_geometry_score: float,
    terrain_factor: float,
    area_ha: float,
    rectangularity: float,
    compactness: float,
    erl_m: float,
    hole_count: int | float,
    config: Mapping[str, Any],
) -> dict[str, float | str]:
    features = feature_values(
        fast_geometry_score=fast_geometry_score,
        area_ha=area_ha,
        rectangularity=rectangularity,
        compactness=compactness,
        erl_m=erl_m,
        hole_count=hole_count,
    )
    geometry = geometry_score(features, config)
    terrain = min(1.0, max(0.0, float(terrain_factor)))
    return {
        "geometry_score": geometry,
        "akerdrift_score": min(100.0, max(0.0, geometry * terrain)),
        "drift_model_version": str(config["model_version"]),
    }
