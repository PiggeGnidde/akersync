#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerFrö – Ärter MVP v0a · C5b robustness of quadratic ILR residual texture.

This is a robustness/freeze-candidate check of C5 B2, not a model search.

Model:
  match variables + quadratic orthonormal ILR(clay,silt,sand)

Validation:
  1) leave-one-dominant-SKO-out
  2) leave-one-municipality-out
  3) pairwise held-out score comparison inside the matched twin pairs

Primary interpretation:
  Among two near-identical fields, how often does the held-out B2 model score
  the historical CONSERVART field above its unlabeled twin?

Unlabeled is not biological negative. This measures historical-use ranking.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.akerfro_ertor_v0a.matched_ranking_c3 import build_pipeline  # noqa: E402

try:
    from sklearn.metrics import roc_auc_score
except Exception as exc:  # pragma: no cover
    raise RuntimeError("C5b requires scikit-learn") from exc

DEFAULT_TWINS = ROOT / "work" / "akerfro_ertor_v0a" / "literature_tiebreak_c4b" / "near_twin_sample.parquet"
DEFAULT_OUT = ROOT / "work" / "akerfro_ertor_v0a" / "residual_texture_c5b"

MATCH_FEATURES = [
    "log_area_ha",
    "topography__slope_p90_deg",
    "akerscore__akerscore_soil_p50",
]
QUAD_ILR = [
    "texture_ilr1",
    "texture_ilr2",
    "texture_ilr1_sq",
    "texture_ilr2_sq",
    "texture_ilr_cross",
]
FEATURES = MATCH_FEATURES + QUAD_ILR


def ensure_twins(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    required = set(FEATURES + [
        "pair_id", "twin_role", "dominant_sko_id_c2", "municipality",
        "current_field_id",
    ])
    missing = sorted(required - set(out.columns))
    if missing:
        raise RuntimeError(f"C5b near-twin file missing columns: {missing}")
    if out["pair_id"].nunique() * 2 != len(out):
        raise RuntimeError("C5b expects exactly two rows per pair")
    out["y"] = out["twin_role"].eq("positive").astype(int)
    return out


def grouped_cv_predictions(frame: pd.DataFrame, group_col: str, cv_name: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    folds = []
    preds = []
    groups = sorted(frame[group_col].dropna().astype(str).unique())

    for group in groups:
        test_mask = frame[group_col].astype(str).eq(group)
        train = frame[~test_mask].copy()
        test = frame[test_mask].copy()
        if train["y"].nunique() < 2 or test["y"].nunique() < 2:
            folds.append({
                "cv": cv_name, "group": group,
                "n_test": len(test), "n_pairs": int(test["pair_id"].nunique()),
                "auc": np.nan, "pairwise_accuracy": np.nan,
                "pairwise_ties": np.nan, "status": "SKIP",
            })
            continue

        pipe = build_pipeline(FEATURES)
        pipe.fit(train[FEATURES], train["y"])
        score = pipe.predict_proba(test[FEATURES])[:, 1]

        pred = test[[
            "pair_id", "current_field_id", "twin_role", "municipality",
            "dominant_sko_id_c2", "y",
        ]].copy()
        pred["cv"] = cv_name
        pred["group"] = group
        pred["score"] = score
        pred.attrs = {}
        preds.append(pred)

        auc = float(roc_auc_score(test["y"], score))
        pw = pairwise_from_predictions(pred)
        folds.append({
            "cv": cv_name, "group": group,
            "n_test": len(test), "n_pairs": int(test["pair_id"].nunique()),
            "auc": auc,
            "pairwise_accuracy": float(pw["pairwise_accuracy"]),
            "pairwise_ties": int(pw["ties"]),
            "status": "OK",
        })

    return pd.DataFrame(folds), pd.concat(preds, ignore_index=True) if preds else pd.DataFrame()


def pairwise_from_predictions(pred: pd.DataFrame) -> dict[str, float | int]:
    wide = pred.pivot(index="pair_id", columns="twin_role", values="score").dropna()
    if len(wide) == 0:
        return {
            "n_pairs": 0, "positive_higher": 0, "twin_higher": 0, "ties": 0,
            "pairwise_accuracy": np.nan, "mean_score_difference": np.nan,
            "median_score_difference": np.nan,
        }
    diff = wide["positive"] - wide["unlabeled_twin"]
    eps = 1e-12
    pos_higher = int((diff > eps).sum())
    twin_higher = int((diff < -eps).sum())
    ties = int((diff.abs() <= eps).sum())
    denom = pos_higher + twin_higher
    acc = pos_higher / denom if denom else np.nan
    return {
        "n_pairs": int(len(wide)),
        "positive_higher": pos_higher,
        "twin_higher": twin_higher,
        "ties": ties,
        "pairwise_accuracy": float(acc),
        "mean_score_difference": float(diff.mean()),
        "median_score_difference": float(diff.median()),
    }


def exact_binomial_two_sided(k: int, n: int) -> float:
    """Exact two-sided binomial p-value under p=0.5, dependency-free.

    Uses log-space summation so large n (e.g. 3,015 matched pairs) does not
    overflow via 2**n or huge binomial coefficients.
    """
    if n <= 0:
        return np.nan
    if k < 0 or k > n:
        raise ValueError("k must satisfy 0 <= k <= n")
    lo = min(k, n-k)

    log_terms = []
    log2n = n * math.log(2.0)
    for i in range(lo + 1):
        log_p = (
            math.lgamma(n + 1)
            - math.lgamma(i + 1)
            - math.lgamma(n - i + 1)
            - log2n
        )
        log_terms.append(log_p)

    m = max(log_terms)
    log_tail = m + math.log(sum(math.exp(v - m) for v in log_terms))
    tail = math.exp(log_tail)
    return min(1.0, 2.0 * tail)


def summarize_cv(folds: pd.DataFrame, predictions: pd.DataFrame, cv_name: str) -> dict[str, float | int | str]:
    f = folds[(folds["cv"].eq(cv_name)) & folds["status"].eq("OK")].copy()
    p = predictions[predictions["cv"].eq(cv_name)].copy()
    overall_auc = float(roc_auc_score(p["y"], p["score"])) if p["y"].nunique() == 2 else np.nan
    pw = pairwise_from_predictions(p)
    pval = exact_binomial_two_sided(int(pw["positive_higher"]), int(pw["positive_higher"] + pw["twin_higher"]))
    return {
        "cv": cv_name,
        "n_valid_groups": int(len(f)),
        "fold_auc_mean": float(f["auc"].mean()) if len(f) else np.nan,
        "fold_auc_median": float(f["auc"].median()) if len(f) else np.nan,
        "fold_auc_min": float(f["auc"].min()) if len(f) else np.nan,
        "fold_auc_max": float(f["auc"].max()) if len(f) else np.nan,
        "pooled_out_of_group_auc": overall_auc,
        "pairwise_accuracy": float(pw["pairwise_accuracy"]),
        "positive_higher_pairs": int(pw["positive_higher"]),
        "twin_higher_pairs": int(pw["twin_higher"]),
        "ties": int(pw["ties"]),
        "pairwise_exact_binomial_p": float(pval),
        "mean_score_difference": float(pw["mean_score_difference"]),
        "median_score_difference": float(pw["median_score_difference"]),
    }


def pairwise_by_sko(predictions: pd.DataFrame, cv_name: str) -> pd.DataFrame:
    p = predictions[predictions["cv"].eq(cv_name)].copy()
    rows = []
    for sko, g in p.groupby("dominant_sko_id_c2", sort=True):
        pw = pairwise_from_predictions(g)
        n = int(pw["positive_higher"] + pw["twin_higher"])
        rows.append({
            "sko": str(sko),
            "n_pairs": int(pw["n_pairs"]),
            "pairwise_accuracy": float(pw["pairwise_accuracy"]),
            "positive_higher": int(pw["positive_higher"]),
            "twin_higher": int(pw["twin_higher"]),
            "ties": int(pw["ties"]),
            "exact_binomial_p": exact_binomial_two_sided(int(pw["positive_higher"]), n),
            "mean_score_difference": float(pw["mean_score_difference"]),
        })
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--twins", default=str(DEFAULT_TWINS))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    twin_path = Path(args.twins)
    if not twin_path.exists():
        raise FileNotFoundError("Run C4b first; near_twin_sample.parquet is missing")

    twins = ensure_twins(pd.read_parquet(twin_path))
    n_pairs = int(twins["pair_id"].nunique())
    if n_pairs < 2900:
        raise RuntimeError(f"C5b expects near-complete C4b twin set; found {n_pairs:,}")

    sko_folds, sko_preds = grouped_cv_predictions(
        twins, "dominant_sko_id_c2", "leave_one_SKO_out"
    )
    muni_folds, muni_preds = grouped_cv_predictions(
        twins, "municipality", "leave_one_municipality_out"
    )

    folds = pd.concat([sko_folds, muni_folds], ignore_index=True)
    predictions = pd.concat([sko_preds, muni_preds], ignore_index=True)

    sko_summary = summarize_cv(folds, predictions, "leave_one_SKO_out")
    muni_summary = summarize_cv(folds, predictions, "leave_one_municipality_out")
    summary = pd.DataFrame([sko_summary, muni_summary])
    sko_pairwise = pairwise_by_sko(predictions, "leave_one_SKO_out")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summary_path = out / "cv_summary.csv"
    folds_path = out / "group_fold_results.csv"
    preds_path = out / "out_of_group_predictions.parquet"
    sko_pair_path = out / "pairwise_by_sko.csv"

    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    folds.to_csv(folds_path, index=False, encoding="utf-8-sig")
    predictions.to_parquet(preds_path, index=False)
    sko_pairwise.to_csv(sko_pair_path, index=False, encoding="utf-8-sig")

    report = {
        "schema_version": "akerfro-ertor-residual-texture-c5b-v0a",
        "model": "matchvars + quadratic orthonormal ILR texture",
        "features": FEATURES,
        "near_twin_pairs": n_pairs,
        "primary_metric": "pairwise held-out accuracy: historical positive scored above its unlabeled twin",
        "null_pairwise_accuracy": 0.5,
        "leave_one_SKO_out": sko_summary,
        "leave_one_municipality_out": muni_summary,
        "guardrail": (
            "A pairwise accuracy above 50% means the quadratic texture model weakly reconstructs "
            "historical CONSERVART selection among near twins. It does not estimate agronomic "
            "suitability and unlabeled twins are not biological negatives."
        ),
        "freeze_interpretation": (
            "If the effect is small but directionally stable across SKO and municipality validation, "
            "freeze texture as a weak residual component rather than a primary ÄrtMatch driver."
        ),
        "outputs": {
            "cv_summary": str(summary_path),
            "fold_results": str(folds_path),
            "predictions": str(preds_path),
            "pairwise_by_sko": str(sko_pair_path),
        },
    }
    json_path = out / "c5b_summary.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 122)
    print("ÅkerFrö – Ärter MVP v0a · C5b QUADRATIC ILR ROBUSTNESS")
    print("=" * 122)
    print(f"Near-twin pairs: {n_pairs:,}")
    print("Model: match variables + quadratic orthonormal ILR(clay,silt,sand)")

    print("\nGROUPED CV SUMMARY")
    print(summary.to_string(index=False, formatters={
        "fold_auc_mean": lambda v: f"{v:.3f}",
        "fold_auc_median": lambda v: f"{v:.3f}",
        "fold_auc_min": lambda v: f"{v:.3f}",
        "fold_auc_max": lambda v: f"{v:.3f}",
        "pooled_out_of_group_auc": lambda v: f"{v:.3f}",
        "pairwise_accuracy": lambda v: f"{100*v:.2f}%",
        "pairwise_exact_binomial_p": lambda v: f"{v:.6g}",
        "mean_score_difference": lambda v: f"{v:+.5f}",
        "median_score_difference": lambda v: f"{v:+.5f}",
    }))

    print("\nPAIRWISE BY HELD-OUT SKO")
    print(sko_pairwise.to_string(index=False, formatters={
        "pairwise_accuracy": lambda v: f"{100*v:.2f}%",
        "exact_binomial_p": lambda v: f"{v:.4g}",
        "mean_score_difference": lambda v: f"{v:+.5f}",
    }))

    for row in [sko_summary, muni_summary]:
        print(
            f"\n{row['cv']}: historical positive wins "
            f"{row['positive_higher_pairs']:,} vs twin wins {row['twin_higher_pairs']:,} "
            f"(ties {row['ties']:,}) => {100*row['pairwise_accuracy']:.2f}%"
        )

    print("\nGUARDRAIL")
    print(report["guardrail"])
    print("\nFREEZE INTERPRETATION")
    print(report["freeze_interpretation"])
    print(f"\nSummary: {summary_path}")
    print(f"Pairwise by SKO: {sko_pair_path}")
    print(f"JSON: {json_path}")
    print("=" * 122)
    print("C5b QUADRATIC ILR ROBUSTNESS: PASS")
    print("=" * 122)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
