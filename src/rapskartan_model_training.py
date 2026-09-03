#!/usr/bin/env python3
"""Deterministic model and calibration helpers for Rapskartan STOPPUNKT C."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score, precision_recall_curve, precision_score, recall_score,
    f1_score, roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


EPS = 1e-6


class PriorFrequencyEstimator(BaseEstimator, ClassifierMixin):
    """Smoothed field-history frequency using prevalence learned from training rows."""

    def __init__(self, prior_strength: float = 2.0):
        self.prior_strength = float(prior_strength)

    def fit(self, X: pd.DataFrame, y: Iterable[int], sample_weight: Iterable[float] | None = None):
        labels = np.asarray(list(y), dtype=float)
        weights = np.ones(len(labels), dtype=float) if sample_weight is None else np.asarray(list(sample_weight), dtype=float)
        self.prevalence_ = float(np.average(labels, weights=weights))
        self.classes_ = np.array([0, 1])
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        known = pd.to_numeric(X["known_history_years"], errors="coerce").fillna(0).to_numpy(dtype=float)
        frequency = pd.to_numeric(X["raps_frequency"], errors="coerce").fillna(0).to_numpy(dtype=float)
        probability = (frequency * known + self.prevalence_ * self.prior_strength) / (known + self.prior_strength)
        probability = np.clip(probability, EPS, 1 - EPS)
        return np.column_stack([1 - probability, probability])


@dataclass
class PlattCalibrator:
    model: LogisticRegression

    def predict(self, probability: np.ndarray) -> np.ndarray:
        values = np.asarray(probability, dtype=float)
        logits = np.log(np.clip(values, EPS, 1 - EPS) / np.clip(1 - values, EPS, 1 - EPS))
        return np.clip(self.model.predict_proba(logits.reshape(-1, 1))[:, 1], 0, 1)


@dataclass
class IsotonicCalibrator:
    model: IsotonicRegression

    def predict(self, probability: np.ndarray) -> np.ndarray:
        return np.clip(self.model.predict(np.asarray(probability, dtype=float)), 0, 1)


def fit_calibrator(method: str, probability: np.ndarray, y: np.ndarray, weight: np.ndarray, seed: int) -> Any:
    p = np.clip(np.asarray(probability, dtype=float), EPS, 1 - EPS)
    labels = np.asarray(y, dtype=int)
    weights = np.asarray(weight, dtype=float)
    if len(np.unique(labels)) != 2:
        raise RuntimeError("Calibration requires both classes")
    if method == "PLATT":
        logits = np.log(p / (1 - p)).reshape(-1, 1)
        model = LogisticRegression(random_state=int(seed), solver="lbfgs", max_iter=1000)
        model.fit(logits, labels, sample_weight=weights)
        return PlattCalibrator(model)
    if method == "ISOTONIC":
        model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        model.fit(p, labels, sample_weight=weights)
        return IsotonicCalibrator(model)
    raise RuntimeError(f"Unknown calibration method: {method}")


def make_estimator(family: str, contract: dict[str, Any], seed_offset: int = 0) -> Any:
    seed = int(contract["model"]["random_seed"]) + int(seed_offset)
    if family == "PRIOR_FREQUENCY_BASELINE":
        return PriorFrequencyEstimator()
    if family == "LOGISTIC_REGRESSION":
        return Pipeline([
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("scale", StandardScaler()),
            ("classifier", LogisticRegression(
                random_state=seed, solver="liblinear", C=1.0, max_iter=2000,
            )),
        ])
    if family == "RANDOM_FOREST":
        settings = contract["model"]["random_forest"]
        return Pipeline([
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("classifier", RandomForestClassifier(
                n_estimators=int(settings["n_estimators"]), max_depth=int(settings["max_depth"]),
                min_samples_leaf=int(settings["min_samples_leaf"]), max_features=settings["max_features"],
                n_jobs=int(settings["n_jobs"]), random_state=seed,
            )),
        ])
    raise RuntimeError(f"Unknown model family: {family}")


def fit_estimator(estimator: Any, family: str, X: pd.DataFrame, y: np.ndarray, weight: np.ndarray) -> Any:
    if family == "PRIOR_FREQUENCY_BASELINE":
        estimator.fit(X, y, sample_weight=weight)
    else:
        estimator.fit(X, y, classifier__sample_weight=weight)
    return estimator


def predict_probability(estimator: Any, X: pd.DataFrame) -> np.ndarray:
    probability = np.asarray(estimator.predict_proba(X)[:, 1], dtype=float)
    if not np.isfinite(probability).all() or ((probability < 0) | (probability > 1)).any():
        raise RuntimeError("Model emitted invalid probabilities")
    return probability


def year_oof_predictions(
    frame: pd.DataFrame, feature_columns: list[str], family: str, contract: dict[str, Any],
) -> np.ndarray:
    years = sorted(pd.to_numeric(frame["target_year"], errors="raise").astype(int).unique().tolist())
    if len(years) < 3 or any(year >= 2025 for year in years):
        raise RuntimeError("Year-held-out CV needs at least three pre-2025 years")
    result = np.full(len(frame), np.nan, dtype=float)
    for fold_number, heldout in enumerate(years):
        test = frame["target_year"].astype(int).to_numpy() == heldout
        train = ~test
        estimator = make_estimator(family, contract, seed_offset=fold_number)
        fit_estimator(
            estimator, family, frame.loc[train, feature_columns],
            frame.loc[train, "is_winter_rapeseed"].to_numpy(dtype=int),
            frame.loc[train, "population_weight"].to_numpy(dtype=float),
        )
        result[test] = predict_probability(estimator, frame.loc[test, feature_columns])
    if not np.isfinite(result).all():
        raise RuntimeError("OOF prediction coverage is incomplete")
    return result


def group_oof_predictions(
    frame: pd.DataFrame, feature_columns: list[str], family: str, group_column: str,
    contract: dict[str, Any],
) -> np.ndarray:
    groups = sorted(frame[group_column].unique().tolist())
    if len(groups) < 3:
        raise RuntimeError("Grouped CV needs at least three folds")
    result = np.full(len(frame), np.nan, dtype=float)
    for fold_number, heldout in enumerate(groups):
        test = frame[group_column].to_numpy() == heldout
        train = ~test
        estimator = make_estimator(family, contract, seed_offset=100 + fold_number)
        fit_estimator(
            estimator, family, frame.loc[train, feature_columns],
            frame.loc[train, "is_winter_rapeseed"].to_numpy(dtype=int),
            frame.loc[train, "population_weight"].to_numpy(dtype=float),
        )
        result[test] = predict_probability(estimator, frame.loc[test, feature_columns])
    if not np.isfinite(result).all():
        raise RuntimeError("Grouped OOF prediction coverage is incomplete")
    return result


def crossfit_calibration(
    raw_probability: np.ndarray, frame: pd.DataFrame, method: str, group_column: str,
    contract: dict[str, Any],
) -> np.ndarray:
    groups = sorted(frame[group_column].unique().tolist())
    result = np.full(len(frame), np.nan, dtype=float)
    y = frame["is_winter_rapeseed"].to_numpy(dtype=int)
    weights = frame["population_weight"].to_numpy(dtype=float)
    for fold_number, heldout in enumerate(groups):
        test = frame[group_column].to_numpy() == heldout
        train = ~test
        calibrator = fit_calibrator(
            method, raw_probability[train], y[train], weights[train],
            int(contract["model"]["random_seed"]) + 500 + fold_number,
        )
        result[test] = calibrator.predict(raw_probability[test])
    if not np.isfinite(result).all() or ((result < 0) | (result > 1)).any():
        raise RuntimeError("Cross-fitted calibration failed")
    return result


def weighted_brier(y: np.ndarray, probability: np.ndarray, weight: np.ndarray) -> float:
    return float(np.average((np.asarray(probability) - np.asarray(y)) ** 2, weights=np.asarray(weight)))


def expected_calibration_error(y: np.ndarray, probability: np.ndarray, weight: np.ndarray, bins: int = 10) -> float:
    y = np.asarray(y, dtype=float)
    p = np.asarray(probability, dtype=float)
    w = np.asarray(weight, dtype=float)
    total = float(w.sum())
    error = 0.0
    boundaries = np.linspace(0, 1, int(bins) + 1)
    for index in range(int(bins)):
        mask = (p >= boundaries[index]) & (p < boundaries[index + 1] if index < bins - 1 else p <= boundaries[index + 1])
        if not mask.any():
            continue
        bin_weight = float(w[mask].sum())
        error += bin_weight / total * abs(float(np.average(y[mask], weights=w[mask])) - float(np.average(p[mask], weights=w[mask])))
    return float(error)


def threshold_at_precision(y: np.ndarray, probability: np.ndarray, weight: np.ndarray, target: float) -> dict[str, Any]:
    precision, recall, thresholds = precision_recall_curve(y, probability, sample_weight=weight)
    candidates = []
    for index, threshold in enumerate(thresholds):
        if float(precision[index]) + 1e-12 >= float(target):
            candidates.append((float(recall[index]), float(precision[index]), float(threshold)))
    if not candidates:
        return {"target_precision": float(target), "available": False, "threshold": 1.0, "precision": None, "recall": 0.0}
    recall_value, precision_value, threshold = max(candidates, key=lambda item: (item[0], item[1], -item[2]))
    return {
        "target_precision": float(target), "available": True, "threshold": threshold,
        "precision": precision_value, "recall": recall_value,
    }


def probability_metrics(
    y: np.ndarray, probability: np.ndarray, field_weight: np.ndarray, area_weight: np.ndarray,
    *, bins: int = 10,
) -> dict[str, Any]:
    y = np.asarray(y, dtype=int)
    p = np.asarray(probability, dtype=float)
    w = np.asarray(field_weight, dtype=float)
    aw = np.asarray(area_weight, dtype=float)
    predicted = p >= 0.5
    p95 = threshold_at_precision(y, p, w, 0.95)
    p90 = threshold_at_precision(y, p, w, 0.90)
    roc_auc = float(roc_auc_score(y, p, sample_weight=w)) if len(np.unique(y)) == 2 else None
    pr_auc = float(average_precision_score(y, p, sample_weight=w)) if int(y.sum()) else 0.0
    return {
        "precision_at_0_5": float(precision_score(y, predicted, sample_weight=w, zero_division=0)),
        "recall_at_0_5": float(recall_score(y, predicted, sample_weight=w, zero_division=0)),
        "f1_at_0_5": float(f1_score(y, predicted, sample_weight=w, zero_division=0)),
        "pr_auc": pr_auc,
        "roc_auc": roc_auc,
        "brier": weighted_brier(y, p, w),
        "ece": expected_calibration_error(y, p, w, bins=bins),
        "recall_at_95_precision": float(p95["recall"]),
        "recall_at_90_precision": float(p90["recall"]),
        "threshold_at_95_precision": p95,
        "threshold_at_90_precision": p90,
        "area_precision_at_0_5": float(precision_score(y, predicted, sample_weight=aw, zero_division=0)),
        "area_recall_at_0_5": float(recall_score(y, predicted, sample_weight=aw, zero_division=0)),
        "positive_rows": int(y.sum()), "rows": int(len(y)),
        "weighted_positive_fields": float(w[y == 1].sum()), "weighted_fields": float(w.sum()),
    }


def reliability_bins(y: np.ndarray, probability: np.ndarray, weight: np.ndarray, bins: int = 10) -> list[dict[str, Any]]:
    y = np.asarray(y, dtype=float)
    p = np.asarray(probability, dtype=float)
    w = np.asarray(weight, dtype=float)
    boundaries = np.linspace(0, 1, int(bins) + 1)
    rows = []
    for index in range(int(bins)):
        mask = (p >= boundaries[index]) & (p < boundaries[index + 1] if index < bins - 1 else p <= boundaries[index + 1])
        rows.append({
            "bin": index, "lower": float(boundaries[index]), "upper": float(boundaries[index + 1]),
            "rows": int(mask.sum()), "weighted_fields": float(w[mask].sum()) if mask.any() else 0.0,
            "mean_probability": float(np.average(p[mask], weights=w[mask])) if mask.any() else None,
            "observed_fraction": float(np.average(y[mask], weights=w[mask])) if mask.any() else None,
        })
    return rows


def arm_feature_columns(arm: str, prior_columns: list[str], satellite_columns: list[str]) -> list[str]:
    if arm == "PRIOR_ONLY":
        return list(prior_columns)
    if arm == "SATELLITE_ONLY":
        return list(satellite_columns)
    if arm == "PRIOR_PLUS_SATELLITE":
        return list(prior_columns) + list(satellite_columns)
    raise RuntimeError(f"Unknown model arm: {arm}")


def arm_families(arm: str) -> list[str]:
    if arm == "PRIOR_ONLY":
        return ["PRIOR_FREQUENCY_BASELINE", "LOGISTIC_REGRESSION", "RANDOM_FOREST"]
    return ["LOGISTIC_REGRESSION", "RANDOM_FOREST"]


def selection_key(metrics: dict[str, Any], family: str, calibration: str) -> tuple[Any, ...]:
    return (
        float(metrics["recall_at_95_precision"]), float(metrics["pr_auc"]), -float(metrics["brier"]),
        1 if family == "LOGISTIC_REGRESSION" else 0,
        1 if calibration == "PLATT" else 0,
    )
