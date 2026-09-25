#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerFrö – Ärter MVP v0a · C3 locally matched PU ranking.

Build a deterministic locally matched analysis set:
  positive = current field with >=1 clean historical CONSERVART year
  unlabeled controls = same municipality x dominant SKO x global log-area decile

Then compare nested, simple regularized logistic ranking models under
leave-one-SKO-out validation.

Important semantics:
- unlabeled is NOT a biological negative class;
- predicted probabilities are NOT agronomic suitability probabilities;
- AUC measures ability to rank historical-use positives above matched unlabeled
  fields in held-out SKO geography.
"""
from __future__ import annotations

import argparse
import hashlib
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

from analysis.akerfro_ertor_v0a.controlled_profile_c2 import attach_sko  # noqa: E402

try:
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
except Exception as exc:  # pragma: no cover - runtime dependency guard
    raise RuntimeError(
        "C3 requires scikit-learn. Install project requirements before running C3."
    ) from exc

DEFAULT_MATRIX = ROOT / "work" / "akerfro_ertor_v0a" / "positive_profile_c1" / "field_feature_matrix.parquet"
DEFAULT_OUT = ROOT / "work" / "akerfro_ertor_v0a" / "matched_ranking_c3"

CONTROLS_PER_POSITIVE = 8
RANDOM_SALT = "akerfro-ertor-c3-v0a"

FEATURE_MODELS = {
    "M0_area": [
        "log_area_ha",
    ],
    "M1_area_slope": [
        "log_area_ha",
        "topography__slope_p90_deg",
    ],
    "M2_area_slope_akerscore": [
        "log_area_ha",
        "topography__slope_p90_deg",
        "akerscore__akerscore_soil_p50",
    ],
    "M3_core_plus": [
        "log_area_ha",
        "topography__slope_p90_deg",
        "akerscore__akerscore_soil_p50",
        "static__dominant_soil_class",
        "hydrology__twi_mean",
        "geometry__rectangularity",
        "geometry__compactness_4piA_P2",
        "soil__organic_ge20_share_pct",
    ],
}

DISPLAY = {
    "log_area_ha": "log(area)",
    "topography__slope_p90_deg": "slope P90",
    "akerscore__akerscore_soil_p50": "ÅkerScore P50",
    "static__dominant_soil_class": "historic soil class",
    "hydrology__twi_mean": "TWI mean",
    "geometry__rectangularity": "rectangularity",
    "geometry__compactness_4piA_P2": "compactness",
    "soil__organic_ge20_share_pct": "organic >=20% share",
}


def stable_hash(value: str) -> str:
    return hashlib.sha256((RANDOM_SALT + "|" + value).encode("utf-8")).hexdigest()


def make_area_decile(frame: pd.DataFrame) -> pd.Series:
    area_m2 = pd.to_numeric(frame["static__field_area_m2"], errors="coerce")
    if area_m2.isna().any() or (area_m2 <= 0).any():
        raise RuntimeError("C3 requires complete positive static field area")
    log_area = np.log(area_m2.to_numpy(float))
    return pd.Series(
        pd.qcut(log_area, q=10, labels=False, duplicates="drop"),
        index=frame.index,
        dtype="Int64",
    )


def prepare_frame(matrix_path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(matrix_path)
    if len(frame) != 128636 or int(frame["is_positive"].sum()) != 3079:
        raise RuntimeError("C3 anchors require 128,636 current fields and 3,079 positives")
    frame, _ = attach_sko(frame)
    frame["dominant_sko_id_c2"] = frame["dominant_sko_id_c2"].astype("string")
    if frame["dominant_sko_id_c2"].isna().any():
        raise RuntimeError("C3 requires complete dominant SKO")
    frame["area_decile_c3"] = make_area_decile(frame)
    area_ha = pd.to_numeric(frame["static__field_area_m2"], errors="coerce") / 10000.0
    frame["log_area_ha"] = np.log(area_ha)
    frame["local_match_stratum"] = (
        frame["municipality"].astype("string")
        + "|"
        + frame["dominant_sko_id_c2"].astype("string")
        + "|A"
        + frame["area_decile_c3"].astype("string")
    )
    return frame


def matched_sample(
    frame: pd.DataFrame,
    controls_per_positive: int,
    *,
    return_diagnostics: bool = False,
):
    keep_parts: list[pd.DataFrame] = []
    diagnostics = []

    for stratum, g in frame.groupby("local_match_stratum", sort=True, dropna=False):
        pos = g[g["is_positive"]].copy()
        unl = g[~g["is_positive"]].copy()
        if pos.empty or unl.empty:
            diagnostics.append({
                "stratum": str(stratum), "n_positive": len(pos), "n_unlabeled": len(unl),
                "n_controls_selected": 0, "status": "NO_COMMON_SUPPORT",
            })
            continue

        target = min(len(unl), controls_per_positive * len(pos))
        unl = unl.assign(
            _stable_order=unl["current_field_id"].astype(str).map(stable_hash)
        ).sort_values("_stable_order", kind="mergesort").head(target).drop(columns="_stable_order")

        pos = pos.assign(sample_role="positive")
        unl = unl.assign(sample_role="matched_unlabeled")
        keep_parts.extend([pos, unl])
        diagnostics.append({
            "stratum": str(stratum), "n_positive": len(pos), "n_unlabeled": len(g) - len(pos),
            "n_controls_selected": len(unl), "status": "MATCHED",
        })

    if not keep_parts:
        raise RuntimeError("No C3 common-support strata")
    out = pd.concat(keep_parts, ignore_index=True)
    diag = pd.DataFrame(diagnostics)
    if return_diagnostics:
        return out, diag
    return out


def build_pipeline(features: list[str]) -> Pipeline:
    numeric = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
    ])
    prep = ColumnTransformer(
        [("numeric", numeric, features)],
        remainder="drop",
        verbose_feature_names_out=False,
    )
    clf = LogisticRegression(
        C=1.0,
        solver="liblinear",
        max_iter=2000,
        class_weight="balanced",
        random_state=0,
    )
    return Pipeline([("prep", prep), ("clf", clf)])


def leave_one_sko_out(
    sample: pd.DataFrame,
    model_name: str,
    features: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    missing = [c for c in features if c not in sample.columns]
    if missing:
        raise RuntimeError(f"{model_name} missing C1 feature(s): {missing}")

    folds = []
    preds = []
    for sko in sorted(sample["dominant_sko_id_c2"].dropna().astype(str).unique()):
        test_mask = sample["dominant_sko_id_c2"].astype(str).eq(sko)
        train = sample[~test_mask].copy()
        test = sample[test_mask].copy()
        y_train = train["is_positive"].astype(int)
        y_test = test["is_positive"].astype(int)
        if y_test.nunique() < 2 or y_train.nunique() < 2:
            folds.append({
                "model": model_name, "sko": sko, "n_train": len(train), "n_test": len(test),
                "n_test_positive": int(y_test.sum()), "n_test_unlabeled": int((1-y_test).sum()),
                "auc": np.nan, "status": "SKIP_ONE_CLASS",
            })
            continue

        pipe = build_pipeline(features)
        pipe.fit(train[features], y_train)
        score = pipe.predict_proba(test[features])[:, 1]
        auc = float(roc_auc_score(y_test, score))
        folds.append({
            "model": model_name, "sko": sko, "n_train": len(train), "n_test": len(test),
            "n_test_positive": int(y_test.sum()), "n_test_unlabeled": int((1-y_test).sum()),
            "auc": auc, "status": "OK",
        })
        pred = test[[
            "current_field_id", "municipality", "dominant_sko_id_c2",
            "local_match_stratum", "is_positive", "sample_role"
        ]].copy()
        pred["model"] = model_name
        pred["score"] = score
        pred.attrs = {}
        preds.append(pred)

    return pd.DataFrame(folds), pd.concat(preds, ignore_index=True) if preds else pd.DataFrame()


def coefficient_table(sample: pd.DataFrame, model_name: str, features: list[str]) -> pd.DataFrame:
    pipe = build_pipeline(features)
    pipe.fit(sample[features], sample["is_positive"].astype(int))
    coef = pipe.named_steps["clf"].coef_[0]
    return pd.DataFrame({
        "model": model_name,
        "feature": features,
        "display_feature": [DISPLAY.get(f, f) for f in features],
        "standardized_logit_coefficient": coef.astype(float),
        "odds_ratio_per_1sd": np.exp(coef.astype(float)),
    }).sort_values("standardized_logit_coefficient", key=lambda s: s.abs(), ascending=False)


def overall_auc(pred: pd.DataFrame) -> float | None:
    if pred.empty or pred["is_positive"].nunique() < 2:
        return None
    return float(roc_auc_score(pred["is_positive"].astype(int), pred["score"].astype(float)))


def summarize_models(folds: pd.DataFrame, predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for model in FEATURE_MODELS:
        f = folds[(folds["model"] == model) & (folds["status"] == "OK")].copy()
        p = predictions[predictions["model"] == model].copy()
        rows.append({
            "model": model,
            "n_features": len(FEATURE_MODELS[model]),
            "n_valid_sko_folds": len(f),
            "fold_auc_mean": float(f["auc"].mean()) if len(f) else np.nan,
            "fold_auc_median": float(f["auc"].median()) if len(f) else np.nan,
            "fold_auc_min": float(f["auc"].min()) if len(f) else np.nan,
            "fold_auc_max": float(f["auc"].max()) if len(f) else np.nan,
            "pooled_out_of_sko_auc": overall_auc(p),
        })
    out = pd.DataFrame(rows)
    if len(out):
        base = float(out.loc[out["model"].eq("M0_area"), "pooled_out_of_sko_auc"].iloc[0])
        out["auc_gain_vs_area"] = out["pooled_out_of_sko_auc"] - base
        prior = None
        gains = []
        for _, r in out.iterrows():
            auc = float(r["pooled_out_of_sko_auc"])
            gains.append(np.nan if prior is None else auc - prior)
            prior = auc
        out["incremental_auc_gain"] = gains
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", default=str(DEFAULT_MATRIX))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--controls-per-positive", type=int, default=CONTROLS_PER_POSITIVE)
    args = ap.parse_args()

    if args.controls_per_positive < 1:
        raise ValueError("--controls-per-positive must be >=1")

    frame = prepare_frame(Path(args.matrix))
    sample, diag = matched_sample(
        frame,
        args.controls_per_positive,
        return_diagnostics=True,
    )

    n_pos = int(sample["is_positive"].sum())
    n_unl = int((~sample["is_positive"]).sum())
    if n_pos < 3000:
        raise RuntimeError(f"C3 common support retained only {n_pos:,}/3,079 positives")

    fold_parts = []
    pred_parts = []
    coef_parts = []
    for name, features in FEATURE_MODELS.items():
        folds, preds = leave_one_sko_out(sample, name, features)
        fold_parts.append(folds)
        if len(preds):
            pred_parts.append(preds)
        coef_parts.append(coefficient_table(sample, name, features))

    folds = pd.concat(fold_parts, ignore_index=True)
    predictions = pd.concat(pred_parts, ignore_index=True)
    coefs = pd.concat(coef_parts, ignore_index=True)
    summary = summarize_models(folds, predictions)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sample_path = out / "matched_sample.parquet"
    diag_path = out / "matching_diagnostics.csv"
    folds_path = out / "leave_one_sko_out_folds.csv"
    predictions_path = out / "out_of_sko_predictions.parquet"
    summary_path = out / "model_comparison.csv"
    coefs_path = out / "full_sample_standardized_coefficients.csv"

    sample.to_parquet(sample_path, index=False)
    diag.to_csv(diag_path, index=False, encoding="utf-8-sig")
    folds.to_csv(folds_path, index=False, encoding="utf-8-sig")
    predictions.to_parquet(predictions_path, index=False)
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    coefs.to_csv(coefs_path, index=False, encoding="utf-8-sig")

    report = {
        "schema_version": "akerfro-ertor-matched-ranking-c3-v0a",
        "semantics": "positive-unlabeled ranking of historical CONSERVART use, not suitability probability",
        "controls_per_positive_target": int(args.controls_per_positive),
        "matched_positive_fields": n_pos,
        "matched_unlabeled_fields": n_unl,
        "matched_strata": int((diag["status"] == "MATCHED").sum()),
        "positive_retention_pct": 100.0 * n_pos / 3079.0,
        "validation": "leave-one-dominant-SKO-out",
        "models": FEATURE_MODELS,
        "guardrail": (
            "AUC quantifies held-out geographic separation of historical-use positives from locally "
            "matched unlabeled fields. It does not estimate biological suitability or the probability "
            "that an unlabeled field could grow conservärt."
        ),
        "outputs": {
            "matched_sample": str(sample_path),
            "matching_diagnostics": str(diag_path),
            "folds": str(folds_path),
            "predictions": str(predictions_path),
            "model_comparison": str(summary_path),
            "coefficients": str(coefs_path),
        },
    }
    json_path = out / "c3_summary.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 112)
    print("ÅkerFrö – Ärter MVP v0a · C3 LOCALLY MATCHED PU RANKING")
    print("=" * 112)
    print(
        f"Matched positives: {n_pos:,}/3,079 ({report['positive_retention_pct']:.1f}%) · "
        f"matched unlabeled: {n_unl:,} · matched strata: {report['matched_strata']:,}"
    )
    print(f"Validation: {report['validation']}")
    print("\nNESTED MODEL COMPARISON")
    print(summary.to_string(index=False, formatters={
        "fold_auc_mean": lambda v: f"{v:.3f}",
        "fold_auc_median": lambda v: f"{v:.3f}",
        "fold_auc_min": lambda v: f"{v:.3f}",
        "fold_auc_max": lambda v: f"{v:.3f}",
        "pooled_out_of_sko_auc": lambda v: f"{v:.3f}",
        "auc_gain_vs_area": lambda v: f"{v:+.3f}",
        "incremental_auc_gain": lambda v: "" if pd.isna(v) else f"{v:+.3f}",
    }))

    print("\nFULL-SAMPLE STANDARDIZED COEFFICIENTS (descriptive; signs are useful, not causal)")
    for model in FEATURE_MODELS:
        print(f"\n[{model}]")
        q = coefs[coefs["model"].eq(model)]
        print(q[["display_feature", "standardized_logit_coefficient", "odds_ratio_per_1sd"]].to_string(
            index=False,
            formatters={
                "standardized_logit_coefficient": lambda v: f"{v:+.3f}",
                "odds_ratio_per_1sd": lambda v: f"{v:.3f}",
            },
        ))

    print("\nGUARDRAIL")
    print(report["guardrail"])
    print(f"\nMatched sample: {sample_path}")
    print(f"Model comparison: {summary_path}")
    print(f"Fold results: {folds_path}")
    print(f"Coefficients: {coefs_path}")
    print(f"Summary: {json_path}")
    print("=" * 112)
    print("C3 MATCHED PU RANKING: PASS")
    print("=" * 112)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
