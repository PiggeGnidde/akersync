#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Calibrate the lightweight Fast V2 surrogate against route-pilot folders.

Example:
  py -3 src\46_calibrate_akerdrift_fast_v2.py ^
    --input data\pilot\lomma_200 --input data\pilot\eslov_200 ^
    --input data\pilot\simrishamn_200

Only comparable route rows (route_status=OK) are fitted.  The script performs
leave-one-municipality-out validation, then exports a frozen JSON model fitted
to all comparable fields.  It uses only NumPy, pandas and SciPy already present
in the repository requirements.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


ROOT = Path(__file__).resolve().parents[1]
MODEL_VERSION = "akerdrift-fast-v2-routecal-rc0"
CONTINUOUS = [
    "fast_geometry_score", "log_area_ha", "rectangularity",
    "compactness", "log_erl_m",
]
BINARY = ["has_holes", "holes_capped_5"]
KNOT_QUANTILES = (0.25, 0.50, 0.75)
RIDGE_ALPHA = 1.0


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Saknar {path}")
    return pd.read_csv(path, encoding="utf-8-sig")


def load_pilot(directory: Path) -> pd.DataFrame:
    manifest = _read_csv(directory / "sample_manifest.csv")
    route = pd.concat([
        _read_csv(directory / "qa" / "largest_disagreements.csv"),
        _read_csv(directory / "qa" / "stress_fields.csv"),
    ], ignore_index=True)
    if len(manifest) != 200 or len(route) != 200:
        raise ValueError(f"{directory}: förväntade 200 manifest- och ruttrader")
    if manifest["field_key"].duplicated().any() or route["field_key"].duplicated().any():
        raise ValueError(f"{directory}: dubbla field_key")
    joined = route.merge(
        manifest, on="field_key", how="left", validate="one_to_one",
        suffixes=("_route", "_fast"),
    )
    if joined["selection_order_fast"].isna().any():
        raise ValueError(f"{directory}: ruttrad saknar manifestmatch")
    municipalities = joined["kommun"].dropna().astype(str).unique()
    if len(municipalities) != 1:
        raise ValueError(f"{directory}: förväntade exakt en kommun")
    versions = joined["route_model_version"].dropna().astype(str).unique()
    if set(versions) != {"akerdrift-route-pilot-v1a-rc1.1"}:
        raise ValueError(f"{directory}: kräver route-pilot-v1a-rc1.1")
    joined["municipality"] = municipalities[0]
    joined["fast_geometry_score"] = pd.to_numeric(joined["geometry_score_fast"], errors="coerce")
    joined["target_geometry_score"] = pd.to_numeric(joined["geometry_score_route"], errors="coerce")
    joined["terrain_factor"] = pd.to_numeric(joined["drift_terrain_factor"], errors="coerce")
    joined["log_area_ha"] = np.log(pd.to_numeric(joined["area_ha_route"], errors="coerce"))
    joined["log_erl_m"] = np.log(pd.to_numeric(joined["erl"], errors="coerce"))
    joined["has_holes"] = joined["hole_count_fast"].gt(0).astype(float)
    joined["holes_capped_5"] = pd.to_numeric(joined["hole_count_fast"], errors="coerce").clip(0, 5)
    return joined


def load_inputs(paths: Iterable[Path]) -> pd.DataFrame:
    frames = [load_pilot(path.resolve()) for path in paths]
    if len(frames) < 3:
        raise ValueError("Minst tre kommunmappar krävs för leave-one-municipality-out")
    result = pd.concat(frames, ignore_index=True)
    if result["field_key"].duplicated().any():
        duplicates = int(result["field_key"].duplicated().sum())
        raise ValueError(f"Pilotmapparna innehåller {duplicates} dubbla field_key")
    return result


def design_spec(frame: pd.DataFrame) -> dict[str, Any]:
    ranges = {
        name: [float(frame[name].min()), float(frame[name].max())]
        for name in CONTINUOUS
    }
    knots = {
        name: [float(value) for value in frame[name].quantile(KNOT_QUANTILES)]
        for name in CONTINUOUS
    }
    return {"clip_ranges": ranges, "knots": knots}


def design_matrix(frame: pd.DataFrame, spec: dict[str, Any]) -> np.ndarray:
    columns: list[np.ndarray] = []
    for name in CONTINUOUS:
        low, high = spec["clip_ranges"][name]
        values = frame[name].to_numpy(dtype=np.float64).clip(low, high)
        columns.append(values)
        columns.extend(np.maximum(0.0, values - knot) for knot in spec["knots"][name])
    columns.extend(frame[name].to_numpy(dtype=np.float64) for name in BINARY)
    return np.column_stack(columns)


def fit_model(frame: pd.DataFrame) -> dict[str, Any]:
    spec = design_spec(frame)
    matrix = design_matrix(frame, spec)
    mean = matrix.mean(axis=0)
    scale = matrix.std(axis=0)
    scale[scale <= 1e-12] = 1.0
    standardized = (matrix - mean) / scale
    target = frame["target_geometry_score"].to_numpy(dtype=np.float64)
    intercept = float(target.mean())
    gram = standardized.T @ standardized
    coefficients = np.linalg.solve(
        gram + RIDGE_ALPHA * np.eye(gram.shape[0]),
        standardized.T @ (target - intercept),
    )
    return {
        **spec,
        "basis_mean": mean.tolist(),
        "basis_scale": scale.tolist(),
        "coefficients": coefficients.tolist(),
        "intercept": intercept,
    }


def predict_geometry(frame: pd.DataFrame, fitted: dict[str, Any]) -> np.ndarray:
    matrix = design_matrix(frame, fitted)
    mean = np.asarray(fitted["basis_mean"], dtype=np.float64)
    scale = np.asarray(fitted["basis_scale"], dtype=np.float64)
    coefficients = np.asarray(fitted["coefficients"], dtype=np.float64)
    return np.clip(float(fitted["intercept"]) + ((matrix - mean) / scale) @ coefficients, 0, 100)


def metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    difference = predicted - actual
    absolute = np.abs(difference)
    return {
        "spearman": float(spearmanr(actual, predicted).statistic),
        "median_absolute_difference": float(np.median(absolute)),
        "p95_absolute_difference": float(np.quantile(absolute, 0.95)),
        "median_bias": float(np.median(difference)),
        "rmse": float(math.sqrt(np.mean(difference ** 2))),
    }


def evaluate_logo(comparable: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    predictions: list[pd.DataFrame] = []
    for municipality in sorted(comparable["municipality"].unique()):
        train = comparable[comparable["municipality"] != municipality]
        test = comparable[comparable["municipality"] == municipality].copy()
        fitted = fit_model(train)
        geometry = predict_geometry(test, fitted)
        test["prediction"] = np.clip(geometry * test["terrain_factor"].to_numpy(), 0, 100)
        predictions.append(test)
    predicted = pd.concat(predictions, ignore_index=True)
    rows: list[dict[str, Any]] = []
    for (municipality, cohort), part in predicted.groupby(["municipality", "validation_cohort_route"]):
        rows.append({
            "scope": "municipality", "municipality": municipality,
            "cohort": cohort, "n": len(part),
            **metrics(part["route_score"].to_numpy(), part["prediction"].to_numpy()),
        })
    for cohort, part in predicted.groupby("validation_cohort_route"):
        rows.append({
            "scope": "pooled", "municipality": "ALL", "cohort": cohort,
            "n": len(part),
            **metrics(part["route_score"].to_numpy(), part["prediction"].to_numpy()),
        })
    return pd.DataFrame(rows), predicted


def baseline_metrics(comparable: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for cohort, part in comparable.groupby("validation_cohort_route"):
        prediction = np.clip(
            part["fast_geometry_score"].to_numpy() * part["terrain_factor"].to_numpy(), 0, 100,
        )
        rows.append({"model": "fast_v1", "cohort": cohort, "n": len(part), **metrics(part["route_score"].to_numpy(), prediction)})
    return pd.DataFrame(rows)


def write_json(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    all_rows = load_inputs([Path(value) for value in args.input])
    comparable = all_rows[all_rows["route_status"].eq("OK")].copy()
    required = CONTINUOUS + BINARY + ["target_geometry_score", "terrain_factor", "route_score"]
    if comparable[required].isna().any().any() or not np.isfinite(comparable[required].to_numpy(float)).all():
        raise ValueError("Jämförbara rader innehåller saknade eller icke-ändliga modellvärden")
    validation, predictions = evaluate_logo(comparable)
    baseline = baseline_metrics(comparable)
    fitted = fit_model(comparable)
    output = Path(args.output_dir)
    if not output.is_absolute():
        output = ROOT / output
    output.mkdir(parents=True, exist_ok=True)
    model = {
        "model_version": MODEL_VERSION,
        "model_role": "route_calibrated_fast_surrogate",
        "target": "akerdrift-route-pilot-v1a-rc1.1.geometry_score",
        "terrain": {
            "operation": "geometry_score_times_existing_drift_terrain_factor",
            "twi_in_score": False,
        },
        "geometry_model": {
            "type": "additive_piecewise_linear_ridge",
            "continuous_features": CONTINUOUS,
            "binary_features": BINARY,
            "knot_quantiles": list(KNOT_QUANTILES),
            "ridge_alpha": RIDGE_ALPHA,
            **fitted,
        },
        "calibration": {
            "municipalities": sorted(comparable["municipality"].unique()),
            "n_comparable": int(len(comparable)),
            "n_normal": int(comparable["validation_cohort_route"].eq("normal").sum()),
            "n_stress": int(comparable["validation_cohort_route"].eq("stress").sum()),
            "n_small_or_narrow_excluded": int(all_rows["route_status"].eq("SMALL_OR_NARROW_FIELD").sum()),
        },
    }
    write_json(model, output / "akerdrift_fast_v2_routecal_rc0.json")
    validation.to_csv(output / "leave_one_municipality_out.csv", index=False, encoding="utf-8-sig")
    baseline.to_csv(output / "fast_v1_baseline.csv", index=False, encoding="utf-8-sig")
    predictions[[
        "municipality", "field_key", "validation_cohort_route", "route_score", "prediction",
    ]].to_csv(output / "held_out_predictions.csv", index=False, encoding="utf-8-sig")
    print(f"DATA: {len(all_rows):,} skiften · {len(comparable):,} jämförbara · {len(all_rows)-len(comparable):,} exkluderade")
    for row in validation[validation["scope"].eq("pooled")].itertuples(index=False):
        print(
            f"V2 {row.cohort.upper()} (n={row.n}): Spearman {row.spearman:.3f} · "
            f"median |Δ| {row.median_absolute_difference:.2f} · P95 |Δ| {row.p95_absolute_difference:.2f}"
        )
    print(f"KLART: {output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, help="Uppackad *_200-pilotmapp; upprepa minst tre gånger")
    parser.add_argument("--output-dir", default="data/derived/akerdrift_fast_v2_calibration")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
