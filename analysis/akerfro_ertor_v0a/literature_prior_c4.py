#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerFrö – Ärter MVP v0a · C4 literature-prior challenge.

Purpose
-------
Keep two information sources separate:

1) empirical historical-use ranking from C3 (area + slope + ÅkerScore), and
2) a FIXED agronomic literature prior based on the pre-registered MD synthesis.

The literature prior is deliberately NOT fitted to pea labels. Its texture shape
is fixed from the broad literature hypotheses:
  core: clay 8-25%, silt 20-60%, sand 20-65%
  broader feasible region: soft tails, no hard exclusions.

Wetness interaction:
  high TWI combined with high fine fraction receives a soft penalty, reflecting
  waterlogging/drainage risk. No sand x drought interaction is implemented
  because C1/C3 do not contain an independent drought/irrigation proxy.

The challenge then asks whether this fixed prior adds held-out-SKO ranking value
on top of the empirical C3 model, and identifies unlabeled fields with high
literature prior but low historical-use match.

Important: this is positive-unlabeled ranking, not a biological probability.
"""
from __future__ import annotations

import argparse
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

from analysis.akerfro_ertor_v0a.matched_ranking_c3 import (  # noqa: E402
    build_pipeline,
    matched_sample,
    prepare_frame,
)

try:
    from sklearn.metrics import roc_auc_score
except Exception as exc:  # pragma: no cover
    raise RuntimeError("C4 requires scikit-learn") from exc

DEFAULT_MATRIX = ROOT / "work" / "akerfro_ertor_v0a" / "positive_profile_c1" / "field_feature_matrix.parquet"
DEFAULT_OUT = ROOT / "work" / "akerfro_ertor_v0a" / "literature_prior_c4"
CONTROLS_PER_POSITIVE = 8

EMPIRICAL_FEATURES = [
    "log_area_ha",
    "topography__slope_p90_deg",
    "akerscore__akerscore_soil_p50",
]
PLUS_PRIOR_FEATURES = EMPIRICAL_FEATURES + ["literature_prior_score"]

TEXTURE_COLUMNS = [
    "soil__clay_mean",
    "soil__silt_mean",
    "soil__sand_mean",
]
TWI_COLUMN = "hydrology__twi_mean"


def soft_plateau(values, lo: float, hi: float, lo_scale: float, hi_scale: float) -> np.ndarray:
    """Smooth score in (0,1], equal to 1 inside [lo,hi], Gaussian tails outside."""
    x = np.asarray(values, dtype=float)
    distance = np.zeros_like(x, dtype=float)
    lower = x < lo
    upper = x > hi
    distance[lower] = (lo - x[lower]) / lo_scale
    distance[upper] = (x[upper] - hi) / hi_scale
    return np.exp(-0.5 * distance * distance)


def percentile_rank_from_reference(values: pd.Series, reference: pd.Series) -> pd.Series:
    """Empirical percentile against a label-free reference distribution."""
    ref = pd.to_numeric(reference, errors="coerce").dropna().to_numpy(float)
    ref.sort()
    x = pd.to_numeric(values, errors="coerce").to_numpy(float)
    out = np.full(len(x), np.nan, dtype=float)
    valid = np.isfinite(x)
    if len(ref):
        out[valid] = np.searchsorted(ref, x[valid], side="right") / len(ref)
    return pd.Series(out, index=values.index)


def build_literature_prior(frame: pd.DataFrame, twi_reference: pd.Series | None = None) -> pd.DataFrame:
    """Add fixed literature-prior components without using pea labels."""
    missing = [c for c in TEXTURE_COLUMNS + [TWI_COLUMN] if c not in frame.columns]
    if missing:
        raise RuntimeError(f"C4 missing required feature(s): {missing}")

    out = frame.copy()
    clay = pd.to_numeric(out["soil__clay_mean"], errors="coerce")
    silt = pd.to_numeric(out["soil__silt_mean"], errors="coerce")
    sand = pd.to_numeric(out["soil__sand_mean"], errors="coerce")
    twi = pd.to_numeric(out[TWI_COLUMN], errors="coerce")

    # Fixed broad literature shape. Scores never hard-cut a field to zero.
    clay_score = soft_plateau(clay, 8.0, 25.0, 5.0, 10.0)
    silt_score = soft_plateau(silt, 20.0, 60.0, 10.0, 15.0)
    sand_score = soft_plateau(sand, 20.0, 65.0, 10.0, 15.0)

    # Geometric mean prevents any one fraction from dominating while respecting
    # the compositional nature of clay+silt+sand.
    texture_score = np.power(
        np.clip(clay_score * silt_score * sand_score, 1e-12, None),
        1.0 / 3.0,
    )

    reference = twi if twi_reference is None else twi_reference
    twi_pct = percentile_rank_from_reference(twi, reference)

    fine_share = (clay + silt) / 100.0
    # Literature gives direction, not a precise threshold. Use a deliberately
    # broad label-free interaction: penalty grows only in top TWI quartile and
    # when fine fraction exceeds 50%.
    wet_excess = np.clip((twi_pct.to_numpy(float) - 0.75) / 0.25, 0.0, 1.0)
    fine_excess = np.clip((fine_share.to_numpy(float) - 0.50) / 0.40, 0.0, 1.0)
    wet_fine_interaction = wet_excess * fine_excess
    wet_penalty = np.exp(-0.75 * wet_fine_interaction)

    prior = texture_score * wet_penalty
    texture_sum = clay + silt + sand

    out["lit_clay_score"] = clay_score
    out["lit_silt_score"] = silt_score
    out["lit_sand_score"] = sand_score
    out["lit_texture_score"] = texture_score
    out["lit_twi_percentile"] = twi_pct
    out["lit_wet_fine_interaction"] = wet_fine_interaction
    out["lit_wet_penalty"] = wet_penalty
    out["literature_prior_score"] = prior
    out["texture_sum_pct"] = texture_sum
    out["lit_core_texture"] = (
        clay.between(8.0, 25.0)
        & silt.between(20.0, 60.0)
        & sand.between(20.0, 65.0)
    )
    out["lit_sand_gt70"] = sand.gt(70.0)
    out["lit_sand_gt75"] = sand.gt(75.0)
    out["lit_clay_gt30"] = clay.gt(30.0)
    return out


def direct_prior_folds(sample: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    folds = []
    preds = []
    for sko in sorted(sample["dominant_sko_id_c2"].astype(str).unique()):
        test = sample[sample["dominant_sko_id_c2"].astype(str).eq(sko)].copy()
        y = test["is_positive"].astype(int)
        score = pd.to_numeric(test["literature_prior_score"], errors="coerce")
        valid = score.notna()
        if valid.sum() == 0 or y.loc[valid].nunique() < 2:
            auc = np.nan
            status = "SKIP"
        else:
            auc = float(roc_auc_score(y.loc[valid], score.loc[valid]))
            status = "OK"
        folds.append({
            "model": "LIT_fixed_prior",
            "sko": sko,
            "n_test": int(len(test)),
            "n_valid": int(valid.sum()),
            "n_test_positive": int(y.sum()),
            "auc": auc,
            "status": status,
        })
        pred = test.loc[valid, [
            "current_field_id", "municipality", "dominant_sko_id_c2",
            "local_match_stratum", "is_positive", "sample_role",
        ]].copy()
        pred["model"] = "LIT_fixed_prior"
        pred["score"] = score.loc[valid].to_numpy(float)
        pred.attrs = {}
        preds.append(pred)
    return pd.DataFrame(folds), pd.concat(preds, ignore_index=True)


def fitted_model_folds(
    sample: pd.DataFrame,
    model_name: str,
    features: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    folds = []
    preds = []
    for sko in sorted(sample["dominant_sko_id_c2"].astype(str).unique()):
        test_mask = sample["dominant_sko_id_c2"].astype(str).eq(sko)
        train = sample[~test_mask].copy()
        test = sample[test_mask].copy()
        y_train = train["is_positive"].astype(int)
        y_test = test["is_positive"].astype(int)
        if y_train.nunique() < 2 or y_test.nunique() < 2:
            folds.append({
                "model": model_name, "sko": sko, "n_test": len(test),
                "n_valid": len(test), "n_test_positive": int(y_test.sum()),
                "auc": np.nan, "status": "SKIP",
            })
            continue
        pipe = build_pipeline(features)
        pipe.fit(train[features], y_train)
        score = pipe.predict_proba(test[features])[:, 1]
        auc = float(roc_auc_score(y_test, score))
        folds.append({
            "model": model_name, "sko": sko, "n_test": len(test),
            "n_valid": len(test), "n_test_positive": int(y_test.sum()),
            "auc": auc, "status": "OK",
        })
        pred = test[[
            "current_field_id", "municipality", "dominant_sko_id_c2",
            "local_match_stratum", "is_positive", "sample_role",
        ]].copy()
        pred["model"] = model_name
        pred["score"] = score
        pred.attrs = {}
        preds.append(pred)
    return pd.DataFrame(folds), pd.concat(preds, ignore_index=True)


def pooled_auc(pred: pd.DataFrame) -> float:
    if pred.empty or pred["is_positive"].nunique() < 2:
        return math.nan
    return float(roc_auc_score(pred["is_positive"].astype(int), pred["score"].astype(float)))


def summarize_models(folds: pd.DataFrame, predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for model in ["LIT_fixed_prior", "M2_empirical", "M2_plus_LIT"]:
        f = folds[(folds["model"] == model) & folds["status"].eq("OK")]
        p = predictions[predictions["model"].eq(model)]
        rows.append({
            "model": model,
            "n_valid_sko_folds": int(len(f)),
            "fold_auc_mean": float(f["auc"].mean()) if len(f) else np.nan,
            "fold_auc_median": float(f["auc"].median()) if len(f) else np.nan,
            "fold_auc_min": float(f["auc"].min()) if len(f) else np.nan,
            "fold_auc_max": float(f["auc"].max()) if len(f) else np.nan,
            "pooled_out_of_sko_auc": pooled_auc(p),
        })
    out = pd.DataFrame(rows)
    base = float(out.loc[out["model"].eq("M2_empirical"), "pooled_out_of_sko_auc"].iloc[0])
    out["gain_vs_M2"] = out["pooled_out_of_sko_auc"] - base
    return out


def hypothesis_table(sample: pd.DataFrame) -> pd.DataFrame:
    pos = sample[sample["is_positive"]]
    ctl = sample[~sample["is_positive"]]
    rows = []

    def add(name: str, mask_col: str, expected: str):
        p = float(pos[mask_col].mean()) if len(pos) else np.nan
        c = float(ctl[mask_col].mean()) if len(ctl) else np.nan
        rr = p / c if c > 0 else np.nan
        rows.append({
            "hypothesis": name,
            "expected_direction": expected,
            "positive_share_pct": 100 * p,
            "control_share_pct": 100 * c,
            "positive_to_control_ratio": rr,
        })

    add("H1 sand >70%", "lit_sand_gt70", "underrepresented among positives")
    add("H1b sand >75%", "lit_sand_gt75", "underrepresented among positives")
    add("H2 literature core texture", "lit_core_texture", "overrepresented among positives")
    add("H3 clay >30% (no hard exclusion)", "lit_clay_gt30", "context-dependent; not forced negative")

    # Continuous prior as a fifth pre-registered-style check.
    rows.append({
        "hypothesis": "Fixed literature prior score",
        "expected_direction": "higher among positives if prior aligns with historical selection",
        "positive_share_pct": float(pos["literature_prior_score"].median()) * 100,
        "control_share_pct": float(ctl["literature_prior_score"].median()) * 100,
        "positive_to_control_ratio": (
            float(pos["literature_prior_score"].median())
            / float(ctl["literature_prior_score"].median())
            if float(ctl["literature_prior_score"].median()) > 0 else np.nan
        ),
    })
    return pd.DataFrame(rows)


def texture_bins(sample: pd.DataFrame) -> pd.DataFrame:
    work = sample.copy()
    clay = pd.to_numeric(work["soil__clay_mean"], errors="coerce")
    silt = pd.to_numeric(work["soil__silt_mean"], errors="coerce")
    work["clay_bin"] = pd.cut(
        clay, bins=[-np.inf, 5, 8, 12, 18, 25, 30, 40, np.inf],
        labels=["<5", "5-8", "8-12", "12-18", "18-25", "25-30", "30-40", "40+"],
        right=False,
    )
    work["silt_bin"] = pd.cut(
        silt, bins=[-np.inf, 10, 20, 30, 40, 50, 60, 70, np.inf],
        labels=["<10", "10-20", "20-30", "30-40", "40-50", "50-60", "60-70", "70+"],
        right=False,
    )
    rows = []
    for (cb, sb), g in work.groupby(["clay_bin", "silt_bin"], observed=True):
        np_ = int(g["is_positive"].sum())
        nu = int((~g["is_positive"]).sum())
        if np_ + nu < 10:
            continue
        rows.append({
            "clay_bin": str(cb), "silt_bin": str(sb),
            "n_positive": np_, "n_unlabeled": nu,
            "positive_share_within_cell_pct": 100.0 * np_ / (np_ + nu),
            "n_total": np_ + nu,
        })
    return pd.DataFrame(rows)


def full_sample_empirical_score(sample: pd.DataFrame, full: pd.DataFrame) -> tuple[pd.Series, Any]:
    pipe = build_pipeline(EMPIRICAL_FEATURES)
    pipe.fit(sample[EMPIRICAL_FEATURES], sample["is_positive"].astype(int))
    score = pipe.predict_proba(full[EMPIRICAL_FEATURES])[:, 1]
    return pd.Series(score, index=full.index), pipe


def candidate_table(full: pd.DataFrame, sample: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    empirical, _ = full_sample_empirical_score(sample, full)
    out = full.copy()
    out["empirical_M2_score"] = empirical
    unl = out[~out["is_positive"]].copy()
    prior = pd.to_numeric(unl["literature_prior_score"], errors="coerce")
    emp = pd.to_numeric(unl["empirical_M2_score"], errors="coerce")

    prior_cut = float(prior.quantile(0.90))
    emp_cut = float(emp.quantile(0.50))
    cand = unl[(prior >= prior_cut) & (emp <= emp_cut)].copy()
    cand["literature_prior_percentile_unlabeled"] = prior.loc[cand.index].rank(pct=True)
    # rank against all unlabeled explicitly, not only candidate subset
    sorted_prior = np.sort(prior.dropna().to_numpy(float))
    sorted_emp = np.sort(emp.dropna().to_numpy(float))
    cand["literature_prior_percentile_unlabeled"] = np.searchsorted(
        sorted_prior, cand["literature_prior_score"].to_numpy(float), side="right"
    ) / len(sorted_prior)
    cand["empirical_percentile_unlabeled"] = np.searchsorted(
        sorted_emp, cand["empirical_M2_score"].to_numpy(float), side="right"
    ) / len(sorted_emp)

    keep = [
        "current_field_id", "current_block_id", "current_skiftesbeteckning",
        "municipality", "dominant_sko_id_c2", "static__field_area_m2",
        "soil__clay_mean", "soil__silt_mean", "soil__sand_mean",
        "hydrology__twi_mean", "topography__slope_p90_deg",
        "akerscore__akerscore_soil_p50", "literature_prior_score",
        "lit_texture_score", "lit_wet_fine_interaction",
        "empirical_M2_score", "literature_prior_percentile_unlabeled",
        "empirical_percentile_unlabeled",
    ]
    cand = cand[[c for c in keep if c in cand.columns]].sort_values(
        ["literature_prior_score", "empirical_M2_score"],
        ascending=[False, True],
        kind="mergesort",
    )
    return cand, {
        "literature_prior_p90_unlabeled": prior_cut,
        "empirical_M2_p50_unlabeled": emp_cut,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", default=str(DEFAULT_MATRIX))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--controls-per-positive", type=int, default=CONTROLS_PER_POSITIVE)
    args = ap.parse_args()

    base = prepare_frame(Path(args.matrix))
    # Build the prior on the complete Skåne universe; no pea labels are used.
    full = build_literature_prior(base, twi_reference=base[TWI_COLUMN])
    sample, diag = matched_sample(
        full, args.controls_per_positive, return_diagnostics=True
    )

    npos = int(sample["is_positive"].sum())
    if npos < 3000:
        raise RuntimeError(f"C4 common support retained only {npos:,}/3,079 positives")

    # Texture data QA.
    valid_texture = sample[TEXTURE_COLUMNS].notna().all(axis=1)
    texture_sum = pd.to_numeric(sample.loc[valid_texture, "texture_sum_pct"], errors="coerce")
    median_abs_sum_error = float((texture_sum - 100.0).abs().median()) if len(texture_sum) else np.nan

    f0, p0 = direct_prior_folds(sample)
    f1, p1 = fitted_model_folds(sample, "M2_empirical", EMPIRICAL_FEATURES)
    f2, p2 = fitted_model_folds(sample, "M2_plus_LIT", PLUS_PRIOR_FEATURES)
    folds = pd.concat([f0, f1, f2], ignore_index=True)
    predictions = pd.concat([p0, p1, p2], ignore_index=True)
    summary = summarize_models(folds, predictions)
    hypotheses = hypothesis_table(sample)
    bins = texture_bins(sample)
    candidates, cuts = candidate_table(full, sample)

    # Full-sample coefficients only to inspect prior direction conditional on M2.
    plus = build_pipeline(PLUS_PRIOR_FEATURES)
    plus.fit(sample[PLUS_PRIOR_FEATURES], sample["is_positive"].astype(int))
    coef = plus.named_steps["clf"].coef_[0]
    coefficients = pd.DataFrame({
        "feature": PLUS_PRIOR_FEATURES,
        "standardized_logit_coefficient": coef.astype(float),
        "odds_ratio_per_1sd": np.exp(coef.astype(float)),
    })

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summary_path = out / "model_comparison.csv"
    folds_path = out / "leave_one_sko_out_folds.csv"
    hypotheses_path = out / "literature_hypothesis_checks.csv"
    bins_path = out / "texture_clay_silt_bins.csv"
    candidates_path = out / "high_prior_low_empirical_candidates.csv"
    coef_path = out / "M2_plus_LIT_coefficients.csv"
    prior_fields_path = out / "field_literature_prior.parquet"
    diag_path = out / "matching_diagnostics.csv"

    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    folds.to_csv(folds_path, index=False, encoding="utf-8-sig")
    hypotheses.to_csv(hypotheses_path, index=False, encoding="utf-8-sig")
    bins.to_csv(bins_path, index=False, encoding="utf-8-sig")
    candidates.to_csv(candidates_path, index=False, encoding="utf-8-sig")
    coefficients.to_csv(coef_path, index=False, encoding="utf-8-sig")
    diag.to_csv(diag_path, index=False, encoding="utf-8-sig")
    full[[
        "current_field_id", "is_positive",
        "soil__clay_mean", "soil__silt_mean", "soil__sand_mean",
        TWI_COLUMN, "lit_texture_score", "lit_twi_percentile",
        "lit_wet_fine_interaction", "lit_wet_penalty",
        "literature_prior_score", "lit_core_texture",
        "lit_sand_gt70", "lit_sand_gt75", "lit_clay_gt30",
        "texture_sum_pct",
    ]].to_parquet(prior_fields_path, index=False)

    report = {
        "schema_version": "akerfro-ertor-literature-prior-c4-v0a",
        "current_fields": int(len(full)),
        "matched_positive_fields": npos,
        "matched_unlabeled_fields": int((~sample["is_positive"]).sum()),
        "literature_prior_is_label_fitted": False,
        "texture_prior": {
            "clay_core_pct": [8, 25],
            "silt_core_pct": [20, 60],
            "sand_core_pct": [20, 65],
            "tail_function": "Gaussian distance outside core intervals; no hard cutoff",
        },
        "wetness_interaction": (
            "soft penalty for high fine fraction x top-quartile TWI; direction from literature, "
            "TWI percentile from label-free full-Skåne distribution"
        ),
        "not_tested": (
            "sand x drought/irrigation interaction: no independent drought/irrigation proxy in C1/C3 feature matrix"
        ),
        "texture_complete_matched_pct": 100.0 * float(valid_texture.mean()),
        "median_abs_texture_sum_error_pct_points": median_abs_sum_error,
        "candidate_definition": {
            "literature_prior": ">= unlabeled P90",
            "empirical_M2": "<= unlabeled P50",
            **cuts,
        },
        "candidate_count": int(len(candidates)),
        "guardrail": (
            "The fixed literature prior tests agronomic plausibility, not a calibrated suitability probability. "
            "Historical-use positives are contract/process selections and unlabeled fields are not biological negatives."
        ),
        "outputs": {
            "model_comparison": str(summary_path),
            "folds": str(folds_path),
            "hypothesis_checks": str(hypotheses_path),
            "texture_bins": str(bins_path),
            "high_prior_low_empirical_candidates": str(candidates_path),
            "coefficients": str(coef_path),
            "field_prior": str(prior_fields_path),
        },
    }
    json_path = out / "c4_summary.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 118)
    print("ÅkerFrö – Ärter MVP v0a · C4 LITERATURE PRIOR CHALLENGE")
    print("=" * 118)
    print(
        f"Fields: {len(full):,} · matched positives: {npos:,} · "
        f"matched unlabeled: {int((~sample['is_positive']).sum()):,}"
    )
    print(
        f"Texture complete in matched sample: {100*valid_texture.mean():.1f}% · "
        f"median |clay+silt+sand-100|: {median_abs_sum_error:.3f} %-points"
    )
    print("\nMODEL CHALLENGE")
    print(summary.to_string(index=False, formatters={
        "fold_auc_mean": lambda v: f"{v:.3f}",
        "fold_auc_median": lambda v: f"{v:.3f}",
        "fold_auc_min": lambda v: f"{v:.3f}",
        "fold_auc_max": lambda v: f"{v:.3f}",
        "pooled_out_of_sko_auc": lambda v: f"{v:.3f}",
        "gain_vs_M2": lambda v: f"{v:+.3f}",
    }))

    print("\nPRE-REGISTERED LITERATURE CHECKS")
    print(hypotheses.to_string(index=False, formatters={
        "positive_share_pct": lambda v: f"{v:.2f}",
        "control_share_pct": lambda v: f"{v:.2f}",
        "positive_to_control_ratio": lambda v: f"{v:.3f}",
    }))

    print("\nM2 + LITERATURE PRIOR STANDARDIZED COEFFICIENTS")
    print(coefficients.to_string(index=False, formatters={
        "standardized_logit_coefficient": lambda v: f"{v:+.3f}",
        "odds_ratio_per_1sd": lambda v: f"{v:.3f}",
    }))

    print(
        f"\nHIGH-LITERATURE / LOW-EMPIRICAL UNLABELED CANDIDATES: {len(candidates):,}\n"
        f"  prior >= unlabeled P90 ({cuts['literature_prior_p90_unlabeled']:.4f})\n"
        f"  empirical M2 <= unlabeled P50 ({cuts['empirical_M2_p50_unlabeled']:.4f})"
    )
    if len(candidates):
        show_cols = [
            "current_field_id", "municipality", "static__field_area_m2",
            "soil__clay_mean", "soil__silt_mean", "soil__sand_mean",
            "topography__slope_p90_deg", "akerscore__akerscore_soil_p50",
            "literature_prior_score", "empirical_M2_score",
        ]
        print("\nTOP 20 'STREET-SMART MISSED THESE?' CANDIDATES")
        print(candidates[show_cols].head(20).to_string(index=False))

    print("\nNOT TESTED")
    print(report["not_tested"])
    print("\nGUARDRAIL")
    print(report["guardrail"])
    print(f"\nModel comparison: {summary_path}")
    print(f"Hypothesis checks: {hypotheses_path}")
    print(f"Candidate list: {candidates_path}")
    print(f"Field prior: {prior_fields_path}")
    print(f"Summary: {json_path}")
    print("=" * 118)
    print("C4 LITERATURE PRIOR CHALLENGE: PASS")
    print("=" * 118)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
