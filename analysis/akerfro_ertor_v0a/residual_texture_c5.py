#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerFrö – Ärter MVP v0a · C5 residual texture surface.

Learn whether soil texture contains residual information after C4b near-twin
matching has made fields essentially identical on:
  - municipality x dominant SKO
  - field area
  - slope P90
  - ÅkerScore P50

Models are evaluated leave-one-SKO-out:
  B0 match variables only
  B1 + linear orthonormal ILR(clay,silt,sand)
  B2 + quadratic ILR surface
  B3 + regularized tensor-product cubic spline in ILR space

The spline is fitted inside each training fold; held-out SKO labels are never
used to construct the texture surface. A final full-sample surface is exported
only for interpretation/visualisation.

Semantics: historical CONSERVART-use ranking among near twins, not agronomic
suitability probability and not biological positive/negative classification.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.akerfro_ertor_v0a.matched_ranking_c3 import build_pipeline  # noqa: E402

try:
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.preprocessing import SplineTransformer, StandardScaler
except Exception as exc:  # pragma: no cover
    raise RuntimeError("C5 requires scikit-learn with SplineTransformer") from exc

DEFAULT_TWINS = ROOT / "work" / "akerfro_ertor_v0a" / "literature_tiebreak_c4b" / "near_twin_sample.parquet"
DEFAULT_OUT = ROOT / "work" / "akerfro_ertor_v0a" / "residual_texture_c5"

MATCH_FEATURES = [
    "log_area_ha",
    "topography__slope_p90_deg",
    "akerscore__akerscore_soil_p50",
]
ILR_LINEAR = ["texture_ilr1", "texture_ilr2"]
ILR_QUAD = [
    "texture_ilr1", "texture_ilr2",
    "texture_ilr1_sq", "texture_ilr2_sq", "texture_ilr_cross",
]
MODELS = {
    "B0_matchvars": MATCH_FEATURES,
    "B1_match_plus_linear_ILR": MATCH_FEATURES + ILR_LINEAR,
    "B2_match_plus_quadratic_ILR": MATCH_FEATURES + ILR_QUAD,
}
SPLINE_MODEL = "B3_match_plus_tensor_spline_ILR"

SPLINE_N_KNOTS = 5
SPLINE_DEGREE = 3
SPLINE_C = 0.20


def inverse_ilr(z1: np.ndarray, z2: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Inverse of the orthonormal ILR basis used in C4b, returned as percentages."""
    z1 = np.asarray(z1, dtype=float)
    z2 = np.asarray(z2, dtype=float)
    e1 = np.array([math.sqrt(2.0 / 3.0), -1.0 / math.sqrt(6.0), -1.0 / math.sqrt(6.0)])
    e2 = np.array([0.0, 1.0 / math.sqrt(2.0), -1.0 / math.sqrt(2.0)])
    clr = z1[..., None] * e1 + z2[..., None] * e2
    comp = np.exp(clr)
    comp = 100.0 * comp / comp.sum(axis=-1, keepdims=True)
    return comp[..., 0], comp[..., 1], comp[..., 2]


def forward_ilr(clay, silt, sand, pseudocount: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Forward ILR, primarily for round-trip tests and surface labelling."""
    c = np.asarray(clay, dtype=float) + pseudocount
    si = np.asarray(silt, dtype=float) + pseudocount
    sa = np.asarray(sand, dtype=float) + pseudocount
    z1 = math.sqrt(2.0 / 3.0) * np.log(c / np.sqrt(si * sa))
    z2 = math.sqrt(1.0 / 2.0) * np.log(si / sa)
    return z1, z2


def tensor_basis(b1: np.ndarray, b2: np.ndarray) -> np.ndarray:
    """Row-wise tensor product of two spline basis matrices."""
    if b1.shape[0] != b2.shape[0]:
        raise ValueError("Spline bases must have equal row counts")
    return np.einsum("ni,nj->nij", b1, b2).reshape(b1.shape[0], -1)


@dataclass
class TensorSplineModel:
    match_imputer: SimpleImputer
    match_scaler: StandardScaler
    ilr_imputer: SimpleImputer
    spline1: SplineTransformer
    spline2: SplineTransformer
    spline_scaler: StandardScaler
    classifier: LogisticRegression

    def transform(self, frame: pd.DataFrame) -> np.ndarray:
        xm = self.match_imputer.transform(frame[MATCH_FEATURES])
        xm = self.match_scaler.transform(xm)

        zi = self.ilr_imputer.transform(frame[ILR_LINEAR])
        b1 = self.spline1.transform(zi[:, [0]])
        b2 = self.spline2.transform(zi[:, [1]])
        bt = tensor_basis(b1, b2)
        bt = self.spline_scaler.transform(bt)
        return np.hstack([xm, bt])

    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        return self.classifier.predict_proba(self.transform(frame))[:, 1]

    def decision_function(self, frame: pd.DataFrame) -> np.ndarray:
        return self.classifier.decision_function(self.transform(frame))


def fit_tensor_spline(frame: pd.DataFrame, y: pd.Series) -> TensorSplineModel:
    match_imputer = SimpleImputer(strategy="median")
    match_scaler = StandardScaler()
    xm = match_imputer.fit_transform(frame[MATCH_FEATURES])
    xm = match_scaler.fit_transform(xm)

    ilr_imputer = SimpleImputer(strategy="median")
    zi = ilr_imputer.fit_transform(frame[ILR_LINEAR])

    spline1 = SplineTransformer(
        n_knots=SPLINE_N_KNOTS,
        degree=SPLINE_DEGREE,
        knots="quantile",
        include_bias=False,
        extrapolation="linear",
    )
    spline2 = SplineTransformer(
        n_knots=SPLINE_N_KNOTS,
        degree=SPLINE_DEGREE,
        knots="quantile",
        include_bias=False,
        extrapolation="linear",
    )
    b1 = spline1.fit_transform(zi[:, [0]])
    b2 = spline2.fit_transform(zi[:, [1]])
    bt = tensor_basis(b1, b2)
    spline_scaler = StandardScaler()
    bt = spline_scaler.fit_transform(bt)

    design = np.hstack([xm, bt])
    classifier = LogisticRegression(
        C=SPLINE_C,
        solver="liblinear",
        max_iter=3000,
        class_weight="balanced",
        random_state=0,
    )
    classifier.fit(design, y.astype(int))
    return TensorSplineModel(
        match_imputer=match_imputer,
        match_scaler=match_scaler,
        ilr_imputer=ilr_imputer,
        spline1=spline1,
        spline2=spline2,
        spline_scaler=spline_scaler,
        classifier=classifier,
    )


def ensure_features(twins: pd.DataFrame) -> pd.DataFrame:
    out = twins.copy()
    needed = set(MATCH_FEATURES + ILR_QUAD + ["dominant_sko_id_c2", "twin_role", "pair_id"])
    missing = sorted(needed - set(out.columns))
    if missing:
        raise RuntimeError(f"C5 near-twin file missing required columns: {missing}")
    out["y"] = out["twin_role"].eq("positive").astype(int)
    if out["pair_id"].nunique() * 2 != len(out):
        raise RuntimeError("C5 expects exactly two rows per C4b pair")
    return out


def simple_fold_predictions(
    train: pd.DataFrame,
    test: pd.DataFrame,
    features: list[str],
) -> np.ndarray:
    pipe = build_pipeline(features)
    pipe.fit(train[features], train["y"])
    return pipe.predict_proba(test[features])[:, 1]


def leave_one_sko_out(twins: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    folds = []
    predictions = []
    skos = sorted(twins["dominant_sko_id_c2"].dropna().astype(str).unique())

    for sko in skos:
        test_mask = twins["dominant_sko_id_c2"].astype(str).eq(sko)
        train = twins[~test_mask].copy()
        test = twins[test_mask].copy()
        if train["y"].nunique() < 2 or test["y"].nunique() < 2:
            for model in list(MODELS) + [SPLINE_MODEL]:
                folds.append({
                    "model": model, "sko": sko, "n_test": len(test),
                    "n_test_pairs": int(test["pair_id"].nunique()),
                    "auc": np.nan, "status": "SKIP",
                })
            continue

        for model, features in MODELS.items():
            score = simple_fold_predictions(train, test, features)
            auc = float(roc_auc_score(test["y"], score))
            folds.append({
                "model": model, "sko": sko, "n_test": len(test),
                "n_test_pairs": int(test["pair_id"].nunique()),
                "auc": auc, "status": "OK",
            })
            p = test[[
                "pair_id", "current_field_id", "municipality",
                "dominant_sko_id_c2", "twin_role", "y",
            ]].copy()
            p["model"] = model
            p["score"] = score
            p.attrs = {}
            predictions.append(p)

        spline = fit_tensor_spline(train, train["y"])
        score = spline.predict_proba(test)
        auc = float(roc_auc_score(test["y"], score))
        folds.append({
            "model": SPLINE_MODEL, "sko": sko, "n_test": len(test),
            "n_test_pairs": int(test["pair_id"].nunique()),
            "auc": auc, "status": "OK",
        })
        p = test[[
            "pair_id", "current_field_id", "municipality",
            "dominant_sko_id_c2", "twin_role", "y",
        ]].copy()
        p["model"] = SPLINE_MODEL
        p["score"] = score
        p.attrs = {}
        predictions.append(p)

    return pd.DataFrame(folds), pd.concat(predictions, ignore_index=True)


def summarize_models(folds: pd.DataFrame, predictions: pd.DataFrame) -> pd.DataFrame:
    order = list(MODELS) + [SPLINE_MODEL]
    rows = []
    for model in order:
        f = folds[(folds["model"].eq(model)) & folds["status"].eq("OK")]
        p = predictions[predictions["model"].eq(model)]
        pooled = float(roc_auc_score(p["y"], p["score"])) if p["y"].nunique() == 2 else np.nan
        rows.append({
            "model": model,
            "n_valid_sko_folds": int(len(f)),
            "fold_auc_mean": float(f["auc"].mean()) if len(f) else np.nan,
            "fold_auc_median": float(f["auc"].median()) if len(f) else np.nan,
            "fold_auc_min": float(f["auc"].min()) if len(f) else np.nan,
            "fold_auc_max": float(f["auc"].max()) if len(f) else np.nan,
            "pooled_out_of_sko_auc": pooled,
        })
    out = pd.DataFrame(rows)
    base = float(out.loc[out["model"].eq("B0_matchvars"), "pooled_out_of_sko_auc"].iloc[0])
    quad = float(out.loc[out["model"].eq("B2_match_plus_quadratic_ILR"), "pooled_out_of_sko_auc"].iloc[0])
    out["gain_vs_B0_pooled"] = out["pooled_out_of_sko_auc"] - base
    out["gain_vs_quadratic_pooled"] = out["pooled_out_of_sko_auc"] - quad
    return out


def fold_delta_table(folds: pd.DataFrame) -> pd.DataFrame:
    good = folds[folds["status"].eq("OK")].pivot(index="sko", columns="model", values="auc")
    rows = []
    base = good["B0_matchvars"]
    quad = good["B2_match_plus_quadratic_ILR"]
    for model in list(MODELS) + [SPLINE_MODEL]:
        delta0 = good[model] - base
        deltaq = good[model] - quad
        rows.append({
            "model": model,
            "mean_delta_vs_B0": float(delta0.mean()),
            "median_delta_vs_B0": float(delta0.median()),
            "folds_better_than_B0": int((delta0 > 0).sum()),
            "folds_worse_than_B0": int((delta0 < 0).sum()),
            "mean_delta_vs_quadratic": float(deltaq.mean()),
            "folds_better_than_quadratic": int((deltaq > 0).sum()),
        })
    return pd.DataFrame(rows)


def full_surface(twins: pd.DataFrame, model: TensorSplineModel, grid_n: int = 61) -> pd.DataFrame:
    z1 = pd.to_numeric(twins["texture_ilr1"], errors="coerce")
    z2 = pd.to_numeric(twins["texture_ilr2"], errors="coerce")
    q1 = z1.quantile([0.01, 0.99])
    q2 = z2.quantile([0.01, 0.99])
    g1 = np.linspace(float(q1.iloc[0]), float(q1.iloc[1]), grid_n)
    g2 = np.linspace(float(q2.iloc[0]), float(q2.iloc[1]), grid_n)
    zz1, zz2 = np.meshgrid(g1, g2, indexing="ij")

    grid = pd.DataFrame({
        "texture_ilr1": zz1.ravel(),
        "texture_ilr2": zz2.ravel(),
    })
    for col in MATCH_FEATURES:
        grid[col] = float(pd.to_numeric(twins[col], errors="coerce").median())

    clay, silt, sand = inverse_ilr(grid["texture_ilr1"].to_numpy(), grid["texture_ilr2"].to_numpy())
    grid["clay_pct"] = clay
    grid["silt_pct"] = silt
    grid["sand_pct"] = sand

    score = model.predict_proba(grid)
    logit = model.decision_function(grid)
    med = pd.DataFrame({
        "texture_ilr1": [float(z1.median())],
        "texture_ilr2": [float(z2.median())],
    })
    for col in MATCH_FEATURES:
        med[col] = float(pd.to_numeric(twins[col], errors="coerce").median())
    reference_logit = float(model.decision_function(med)[0])

    grid["historical_use_texture_score"] = score
    grid["relative_logit_vs_median_texture"] = logit - reference_logit

    # Mark broad empirical marginal support to discourage interpretation of
    # far extrapolation corners as agronomic optima.
    clay_obs = pd.to_numeric(twins["soil__clay_mean"], errors="coerce")
    silt_obs = pd.to_numeric(twins["soil__silt_mean"], errors="coerce")
    sand_obs = pd.to_numeric(twins["soil__sand_mean"], errors="coerce")
    bounds = {}
    for name, series in [("clay", clay_obs), ("silt", silt_obs), ("sand", sand_obs)]:
        bounds[name] = (float(series.quantile(.01)), float(series.quantile(.99)))
    grid["within_marginal_01_99_support"] = (
        grid["clay_pct"].between(*bounds["clay"])
        & grid["silt_pct"].between(*bounds["silt"])
        & grid["sand_pct"].between(*bounds["sand"])
    )
    return grid


def pair_score_advantage(predictions: pd.DataFrame, model: str) -> pd.DataFrame:
    p = predictions[predictions["model"].eq(model)].copy()
    wide = p.pivot(index="pair_id", columns="twin_role", values="score").dropna()
    wide["positive_minus_twin_score"] = wide["positive"] - wide["unlabeled_twin"]
    return wide.reset_index()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--twins", default=str(DEFAULT_TWINS))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    twin_path = Path(args.twins)
    if not twin_path.exists():
        raise FileNotFoundError("Run C4b first; near_twin_sample.parquet is missing")

    twins = ensure_features(pd.read_parquet(twin_path))
    n_pairs = int(twins["pair_id"].nunique())
    if n_pairs < 2900:
        raise RuntimeError(f"C5 expects near-complete C4b twins; found only {n_pairs:,} pairs")

    folds, predictions = leave_one_sko_out(twins)
    comparison = summarize_models(folds, predictions)
    deltas = fold_delta_table(folds)

    full_model = fit_tensor_spline(twins, twins["y"])
    surface = full_surface(twins, full_model)
    pair_adv = pair_score_advantage(predictions, SPLINE_MODEL)

    supported = surface[surface["within_marginal_01_99_support"]].copy()
    top_surface = supported.nlargest(25, "relative_logit_vs_median_texture")
    bottom_surface = supported.nsmallest(25, "relative_logit_vs_median_texture")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    comparison_path = out / "model_comparison.csv"
    folds_path = out / "leave_one_sko_out_folds.csv"
    deltas_path = out / "fold_auc_deltas.csv"
    predictions_path = out / "out_of_sko_predictions.parquet"
    surface_path = out / "texture_surface_grid.csv"
    top_path = out / "surface_top_supported_cells.csv"
    bottom_path = out / "surface_bottom_supported_cells.csv"
    pair_path = out / "spline_pair_score_advantage.csv"

    comparison.to_csv(comparison_path, index=False, encoding="utf-8-sig")
    folds.to_csv(folds_path, index=False, encoding="utf-8-sig")
    deltas.to_csv(deltas_path, index=False, encoding="utf-8-sig")
    predictions.to_parquet(predictions_path, index=False)
    surface.to_csv(surface_path, index=False, encoding="utf-8-sig")
    top_surface.to_csv(top_path, index=False, encoding="utf-8-sig")
    bottom_surface.to_csv(bottom_path, index=False, encoding="utf-8-sig")
    pair_adv.to_csv(pair_path, index=False, encoding="utf-8-sig")

    spline_row = comparison[comparison["model"].eq(SPLINE_MODEL)].iloc[0]
    quad_row = comparison[comparison["model"].eq("B2_match_plus_quadratic_ILR")].iloc[0]
    spline_delta = deltas[deltas["model"].eq(SPLINE_MODEL)].iloc[0]

    report = {
        "schema_version": "akerfro-ertor-residual-texture-c5-v0a",
        "near_twin_pairs": n_pairs,
        "validation": "leave-one-dominant-SKO-out",
        "spline": {
            "basis": "tensor product of two cubic B-spline bases in orthonormal ILR space",
            "n_knots_per_axis": SPLINE_N_KNOTS,
            "degree": SPLINE_DEGREE,
            "regularization_C": SPLINE_C,
            "fit_inside_each_training_fold": True,
        },
        "spline_fold_auc_mean": float(spline_row["fold_auc_mean"]),
        "spline_pooled_auc": float(spline_row["pooled_out_of_sko_auc"]),
        "quadratic_fold_auc_mean": float(quad_row["fold_auc_mean"]),
        "quadratic_pooled_auc": float(quad_row["pooled_out_of_sko_auc"]),
        "spline_mean_fold_delta_vs_B0": float(spline_delta["mean_delta_vs_B0"]),
        "spline_folds_better_than_B0": int(spline_delta["folds_better_than_B0"]),
        "spline_folds_better_than_quadratic": int(spline_delta["folds_better_than_quadratic"]),
        "guardrail": (
            "C5 learns residual texture association with historical CONSERVART selection among "
            "near twins. The learned surface is not a calibrated agronomic suitability surface. "
            "Ca/pH, Aphanomyces, drainage infrastructure and irrigation remain unobserved."
        ),
        "outputs": {
            "model_comparison": str(comparison_path),
            "folds": str(folds_path),
            "fold_deltas": str(deltas_path),
            "predictions": str(predictions_path),
            "surface_grid": str(surface_path),
            "surface_top_supported_cells": str(top_path),
            "surface_bottom_supported_cells": str(bottom_path),
            "pair_score_advantage": str(pair_path),
        },
    }
    json_path = out / "c5_summary.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 122)
    print("ÅkerFrö – Ärter MVP v0a · C5 RESIDUAL TEXTURE SURFACE")
    print("=" * 122)
    print(f"Near-twin pairs: {n_pairs:,} · rows: {len(twins):,}")
    print(
        f"Tensor spline: {SPLINE_N_KNOTS} knots/axis · degree {SPLINE_DEGREE} · "
        f"C={SPLINE_C:.2f} · fitted inside each train fold"
    )

    print("\nMODEL COMPARISON")
    print(comparison.to_string(index=False, formatters={
        "fold_auc_mean": lambda v: f"{v:.3f}",
        "fold_auc_median": lambda v: f"{v:.3f}",
        "fold_auc_min": lambda v: f"{v:.3f}",
        "fold_auc_max": lambda v: f"{v:.3f}",
        "pooled_out_of_sko_auc": lambda v: f"{v:.3f}",
        "gain_vs_B0_pooled": lambda v: f"{v:+.3f}",
        "gain_vs_quadratic_pooled": lambda v: f"{v:+.3f}",
    }))

    print("\nFOLD ROBUSTNESS")
    print(deltas.to_string(index=False, formatters={
        "mean_delta_vs_B0": lambda v: f"{v:+.3f}",
        "median_delta_vs_B0": lambda v: f"{v:+.3f}",
        "mean_delta_vs_quadratic": lambda v: f"{v:+.3f}",
    }))

    print("\nTOP SUPPORTED TEXTURE CELLS FROM FULL-SAMPLE SPLINE")
    print(top_surface[[
        "clay_pct", "silt_pct", "sand_pct",
        "historical_use_texture_score", "relative_logit_vs_median_texture",
    ]].head(15).to_string(index=False, formatters={
        "clay_pct": lambda v: f"{v:5.1f}",
        "silt_pct": lambda v: f"{v:5.1f}",
        "sand_pct": lambda v: f"{v:5.1f}",
        "historical_use_texture_score": lambda v: f"{v:.3f}",
        "relative_logit_vs_median_texture": lambda v: f"{v:+.3f}",
    }))

    print("\nBOTTOM SUPPORTED TEXTURE CELLS FROM FULL-SAMPLE SPLINE")
    print(bottom_surface[[
        "clay_pct", "silt_pct", "sand_pct",
        "historical_use_texture_score", "relative_logit_vs_median_texture",
    ]].head(10).to_string(index=False, formatters={
        "clay_pct": lambda v: f"{v:5.1f}",
        "silt_pct": lambda v: f"{v:5.1f}",
        "sand_pct": lambda v: f"{v:5.1f}",
        "historical_use_texture_score": lambda v: f"{v:.3f}",
        "relative_logit_vs_median_texture": lambda v: f"{v:+.3f}",
    }))

    print("\nGUARDRAIL")
    print(report["guardrail"])
    print(f"\nModel comparison: {comparison_path}")
    print(f"Fold deltas: {deltas_path}")
    print(f"Texture surface: {surface_path}")
    print(f"Summary: {json_path}")
    print("=" * 122)
    print("C5 RESIDUAL TEXTURE SURFACE: PASS")
    print("=" * 122)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
