#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerFrö – Ärter MVP v0a · C4b literature tie-breaker among near twins.

Question
--------
When fields are already "otherwise similar" on the empirically important
street-smart selection variables (local geography, field area, slope and
ÅkerScore), does the pre-registered agronomic literature information still
separate historical CONSERVART positives from unlabeled near twins?

Design
------
* one-to-one deterministic nearest-neighbour matching without replacement
* exact stratum: municipality x dominant SKO
* distance variables: log(area), slope P90, ÅkerScore P50
* global label-free standardisation for matching distance
* leave-one-SKO-out ranking models on the matched twin sample

Literature variables are NOT collapsed into the saturated C4 0-1 prior.
Fixed/pre-registered tie-breakers:
  - literature core texture (clay 8-25, silt 20-60, sand 20-65)
  - sand >70%
  - sand >75%
  - clay >30% (reported, not assumed a hard exclusion)
  - fine-soil x high-TWI interaction

Compositional robustness:
  orthonormal ILR(clay,silt,sand) plus quadratic/cross terms and wetness
  interaction. This is an empirical robustness model, not a fixed literature
  score.

Unlabeled means unknown, not biological negative.
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

from analysis.akerfro_ertor_v0a.literature_prior_c4 import build_literature_prior  # noqa: E402
from analysis.akerfro_ertor_v0a.matched_ranking_c3 import build_pipeline, prepare_frame  # noqa: E402

try:
    from sklearn.metrics import roc_auc_score
except Exception as exc:  # pragma: no cover
    raise RuntimeError("C4b requires scikit-learn") from exc

DEFAULT_MATRIX = ROOT / "work" / "akerfro_ertor_v0a" / "positive_profile_c1" / "field_feature_matrix.parquet"
DEFAULT_OUT = ROOT / "work" / "akerfro_ertor_v0a" / "literature_tiebreak_c4b"

MATCH_FEATURES = [
    "log_area_ha",
    "topography__slope_p90_deg",
    "akerscore__akerscore_soil_p50",
]

LIT_RULE_FEATURES = [
    "lit_core_texture",
    "lit_sand_gt70",
    "lit_sand_gt75",
    "lit_clay_gt30",
    "lit_wet_fine_interaction",
]

ILR_FEATURES = [
    "texture_ilr1",
    "texture_ilr2",
    "texture_ilr1_sq",
    "texture_ilr2_sq",
    "texture_ilr_cross",
    "lit_wet_fine_interaction",
]

MODELS = {
    "T0_matchvars": MATCH_FEATURES,
    "T1_lit_rules": LIT_RULE_FEATURES,
    "T2_match_plus_lit_rules": MATCH_FEATURES + LIT_RULE_FEATURES,
    "T3_match_plus_ILR": MATCH_FEATURES + ILR_FEATURES,
}

RANDOM_SALT = "akerfro-ertor-c4b-v0a"


def stable_hash(value: str) -> str:
    return hashlib.sha256((RANDOM_SALT + "|" + str(value)).encode("utf-8")).hexdigest()


def add_ilr(frame: pd.DataFrame, pseudocount: float = 0.1) -> pd.DataFrame:
    """Add an orthonormal 3-part ILR basis and low-order nonlinear terms."""
    out = frame.copy()
    clay = pd.to_numeric(out["soil__clay_mean"], errors="coerce")
    silt = pd.to_numeric(out["soil__silt_mean"], errors="coerce")
    sand = pd.to_numeric(out["soil__sand_mean"], errors="coerce")
    c = np.clip(clay.to_numpy(float), 0.0, None) + pseudocount
    si = np.clip(silt.to_numpy(float), 0.0, None) + pseudocount
    sa = np.clip(sand.to_numpy(float), 0.0, None) + pseudocount
    valid = np.isfinite(c) & np.isfinite(si) & np.isfinite(sa)

    ilr1 = np.full(len(out), np.nan)
    ilr2 = np.full(len(out), np.nan)
    # Balance 1: clay vs geometric mean(silt,sand)
    ilr1[valid] = math.sqrt(2.0 / 3.0) * np.log(
        c[valid] / np.sqrt(si[valid] * sa[valid])
    )
    # Balance 2: silt vs sand
    ilr2[valid] = math.sqrt(1.0 / 2.0) * np.log(si[valid] / sa[valid])

    out["texture_ilr1"] = ilr1
    out["texture_ilr2"] = ilr2
    out["texture_ilr1_sq"] = ilr1 * ilr1
    out["texture_ilr2_sq"] = ilr2 * ilr2
    out["texture_ilr_cross"] = ilr1 * ilr2
    return out


def robust_scale_reference(frame: pd.DataFrame, features: list[str]) -> dict[str, tuple[float, float]]:
    """Label-free robust location/scale used only for matching distance."""
    result = {}
    for col in features:
        x = pd.to_numeric(frame[col], errors="coerce").dropna().to_numpy(float)
        if len(x) == 0:
            raise RuntimeError(f"No valid values for matching feature {col}")
        med = float(np.median(x))
        q25, q75 = np.quantile(x, [0.25, 0.75])
        scale = float((q75 - q25) / 1.349)
        if not np.isfinite(scale) or scale <= 0:
            scale = float(np.std(x, ddof=1))
        if not np.isfinite(scale) or scale <= 0:
            raise RuntimeError(f"Zero/invalid matching scale for {col}")
        result[col] = (med, scale)
    return result


def standardize(frame: pd.DataFrame, ref: dict[str, tuple[float, float]]) -> pd.DataFrame:
    out = pd.DataFrame(index=frame.index)
    for col, (med, scale) in ref.items():
        out[col] = (pd.to_numeric(frame[col], errors="coerce") - med) / scale
    return out


def greedy_unique_twins(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One unique unlabeled twin per positive within municipality x SKO."""
    eligible = frame.copy()
    valid = eligible[MATCH_FEATURES].apply(pd.to_numeric, errors="coerce").notna().all(axis=1)
    eligible = eligible.loc[valid].copy()
    eligible["twin_stratum"] = (
        eligible["municipality"].astype("string")
        + "|"
        + eligible["dominant_sko_id_c2"].astype("string")
    )

    ref = robust_scale_reference(eligible, MATCH_FEATURES)
    z = standardize(eligible, ref)
    for col in MATCH_FEATURES:
        eligible[f"_z_{col}"] = z[col]

    pairs = []
    diag = []
    pair_counter = 0

    for stratum, g in eligible.groupby("twin_stratum", sort=True):
        pos = g[g["is_positive"]].copy()
        ctl = g[~g["is_positive"]].copy()
        if pos.empty or ctl.empty:
            diag.append({
                "stratum": str(stratum), "n_positive": len(pos), "n_unlabeled": len(ctl),
                "n_pairs": 0, "status": "NO_COMMON_SUPPORT",
            })
            continue

        # Deterministic order avoids dependence on source row order.
        pos = pos.assign(
            _order=pos["current_field_id"].astype(str).map(stable_hash)
        ).sort_values("_order", kind="mergesort").drop(columns="_order")
        ctl = ctl.assign(
            _order=ctl["current_field_id"].astype(str).map(stable_hash)
        ).sort_values("_order", kind="mergesort").drop(columns="_order")

        available = np.ones(len(ctl), dtype=bool)
        ctl_z = ctl[[f"_z_{c}" for c in MATCH_FEATURES]].to_numpy(float)
        ctl_indices = ctl.index.to_numpy()

        n_pairs = 0
        for pidx, prow in pos.iterrows():
            avail_idx = np.flatnonzero(available)
            if len(avail_idx) == 0:
                break
            pz = prow[[f"_z_{c}" for c in MATCH_FEATURES]].to_numpy(float)
            delta = ctl_z[avail_idx] - pz
            dist2 = np.einsum("ij,ij->i", delta, delta)
            local_best = int(np.argmin(dist2))
            chosen_pos = int(avail_idx[local_best])
            cidx = int(ctl_indices[chosen_pos])
            available[chosen_pos] = False

            pair_counter += 1
            n_pairs += 1
            distance = float(math.sqrt(float(dist2[local_best])))
            pairs.append({
                "pair_id": pair_counter,
                "stratum": str(stratum),
                "sko": str(prow["dominant_sko_id_c2"]),
                "positive_index": int(pidx),
                "control_index": cidx,
                "match_distance": distance,
            })

        diag.append({
            "stratum": str(stratum), "n_positive": len(pos), "n_unlabeled": len(ctl),
            "n_pairs": n_pairs, "status": "MATCHED" if n_pairs else "NO_PAIRS",
        })

    pair_df = pd.DataFrame(pairs)
    if pair_df.empty:
        raise RuntimeError("C4b produced no near-twin pairs")

    rows = []
    for _, pr in pair_df.iterrows():
        for role, idx in [("positive", pr["positive_index"]), ("unlabeled_twin", pr["control_index"])]:
            row = frame.loc[int(idx)].copy()
            row["pair_id"] = int(pr["pair_id"])
            row["twin_role"] = role
            row["match_distance"] = float(pr["match_distance"])
            row["twin_stratum"] = str(pr["stratum"])
            rows.append(row)
    twins = pd.DataFrame(rows).reset_index(drop=True)
    return twins, pd.DataFrame(diag)


def pooled_smd(a: np.ndarray, b: np.ndarray) -> float:
    a = a[np.isfinite(a)]
    b = b[np.isfinite(b)]
    if len(a) < 2 or len(b) < 2:
        return np.nan
    sa = float(np.std(a, ddof=1))
    sb = float(np.std(b, ddof=1))
    denom = math.sqrt((sa * sa + sb * sb) / 2.0)
    return float((np.mean(a) - np.mean(b)) / denom) if denom > 0 else np.nan


def balance_table(twins: pd.DataFrame) -> pd.DataFrame:
    rows = []
    pos = twins[twins["twin_role"].eq("positive")].sort_values("pair_id")
    ctl = twins[twins["twin_role"].eq("unlabeled_twin")].sort_values("pair_id")
    for col in MATCH_FEATURES:
        a = pd.to_numeric(pos[col], errors="coerce").to_numpy(float)
        b = pd.to_numeric(ctl[col], errors="coerce").to_numpy(float)
        diff = a - b
        rows.append({
            "feature": col,
            "positive_mean": float(np.nanmean(a)),
            "control_mean": float(np.nanmean(b)),
            "smd": pooled_smd(a, b),
            "median_abs_pair_difference": float(np.nanmedian(np.abs(diff))),
            "p90_abs_pair_difference": float(np.nanquantile(np.abs(diff), .90)),
        })
    return pd.DataFrame(rows)


def paired_binary_checks(twins: pd.DataFrame) -> pd.DataFrame:
    wide = twins.pivot(index="pair_id", columns="twin_role", values=[
        "lit_core_texture", "lit_sand_gt70", "lit_sand_gt75", "lit_clay_gt30"
    ])
    specs = [
        ("H1 sand >70%", "lit_sand_gt70", "lower among positives"),
        ("H1b sand >75%", "lit_sand_gt75", "lower among positives"),
        ("H2 core texture", "lit_core_texture", "higher among positives"),
        ("H3 clay >30%", "lit_clay_gt30", "reported; no hard exclusion"),
    ]
    rows = []
    for label, col, expected in specs:
        p = wide[(col, "positive")].astype(float)
        c = wide[(col, "unlabeled_twin")].astype(float)
        valid = p.notna() & c.notna()
        p = p[valid]
        c = c[valid]
        p1c0 = int(((p == 1) & (c == 0)).sum())
        p0c1 = int(((p == 0) & (c == 1)).sum())
        rows.append({
            "hypothesis": label,
            "expected": expected,
            "n_pairs": int(len(p)),
            "positive_share_pct": 100.0 * float(p.mean()),
            "twin_share_pct": 100.0 * float(c.mean()),
            "paired_difference_pp": 100.0 * float((p - c).mean()),
            "discordant_positive1_twin0": p1c0,
            "discordant_positive0_twin1": p0c1,
        })
    return pd.DataFrame(rows)


def paired_continuous_checks(twins: pd.DataFrame) -> pd.DataFrame:
    pos = twins[twins["twin_role"].eq("positive")].set_index("pair_id")
    ctl = twins[twins["twin_role"].eq("unlabeled_twin")].set_index("pair_id")
    specs = [
        ("clay mean", "soil__clay_mean"),
        ("silt mean", "soil__silt_mean"),
        ("sand mean", "soil__sand_mean"),
        ("fine x high-TWI interaction", "lit_wet_fine_interaction"),
    ]
    rows = []
    for label, col in specs:
        p = pd.to_numeric(pos[col], errors="coerce")
        c = pd.to_numeric(ctl[col], errors="coerce")
        valid = p.notna() & c.notna()
        diff = (p[valid] - c[valid]).to_numpy(float)
        rows.append({
            "metric": label,
            "n_pairs": int(valid.sum()),
            "positive_median": float(p[valid].median()),
            "twin_median": float(c[valid].median()),
            "median_paired_difference": float(np.median(diff)) if len(diff) else np.nan,
            "mean_paired_difference": float(np.mean(diff)) if len(diff) else np.nan,
        })
    return pd.DataFrame(rows)


def leave_one_sko_out(
    twins: pd.DataFrame,
    model_name: str,
    features: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = twins.copy()
    work["y"] = work["twin_role"].eq("positive").astype(int)
    folds = []
    preds = []
    for sko in sorted(work["dominant_sko_id_c2"].astype(str).unique()):
        test_mask = work["dominant_sko_id_c2"].astype(str).eq(sko)
        train = work[~test_mask]
        test = work[test_mask]
        y_train = train["y"]
        y_test = test["y"]
        if y_train.nunique() < 2 or y_test.nunique() < 2:
            folds.append({
                "model": model_name, "sko": sko, "n_test": len(test),
                "n_test_pairs": int(test["pair_id"].nunique()),
                "auc": np.nan, "status": "SKIP",
            })
            continue
        pipe = build_pipeline(features)
        pipe.fit(train[features], y_train)
        score = pipe.predict_proba(test[features])[:, 1]
        auc = float(roc_auc_score(y_test, score))
        folds.append({
            "model": model_name, "sko": sko, "n_test": len(test),
            "n_test_pairs": int(test["pair_id"].nunique()),
            "auc": auc, "status": "OK",
        })
        pred = test[[
            "pair_id", "current_field_id", "municipality",
            "dominant_sko_id_c2", "twin_role"
        ]].copy()
        pred["model"] = model_name
        pred["score"] = score
        pred.attrs = {}
        preds.append(pred)
    return pd.DataFrame(folds), pd.concat(preds, ignore_index=True)


def summarize_models(folds: pd.DataFrame, predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for model in MODELS:
        f = folds[(folds["model"].eq(model)) & folds["status"].eq("OK")]
        p = predictions[predictions["model"].eq(model)]
        y = p["twin_role"].eq("positive").astype(int)
        pooled = float(roc_auc_score(y, p["score"])) if y.nunique() == 2 else np.nan
        rows.append({
            "model": model,
            "n_features": len(MODELS[model]),
            "n_valid_sko_folds": int(len(f)),
            "fold_auc_mean": float(f["auc"].mean()) if len(f) else np.nan,
            "fold_auc_median": float(f["auc"].median()) if len(f) else np.nan,
            "fold_auc_min": float(f["auc"].min()) if len(f) else np.nan,
            "fold_auc_max": float(f["auc"].max()) if len(f) else np.nan,
            "pooled_out_of_sko_auc": pooled,
        })
    out = pd.DataFrame(rows)
    base = float(out.loc[out["model"].eq("T0_matchvars"), "pooled_out_of_sko_auc"].iloc[0])
    out["gain_vs_matchvars"] = out["pooled_out_of_sko_auc"] - base
    return out


def full_coefficients(twins: pd.DataFrame) -> pd.DataFrame:
    rows = []
    y = twins["twin_role"].eq("positive").astype(int)
    for model, features in MODELS.items():
        pipe = build_pipeline(features)
        pipe.fit(twins[features], y)
        coef = pipe.named_steps["clf"].coef_[0]
        for feature, c in zip(features, coef):
            rows.append({
                "model": model,
                "feature": feature,
                "standardized_logit_coefficient": float(c),
                "odds_ratio_per_1sd": float(math.exp(float(c))),
            })
    return pd.DataFrame(rows)


def literature_dominance_candidates(twins: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Partial-order comparison: twin no worse on fixed prior criteria, better on >=1.

    Direction used:
      core texture: higher is better
      sand >70: lower is better
      sand >75: lower is better
      wet-fine interaction: lower is better
    clay >30 is reported but deliberately NOT used as a hard negative.
    """
    pos = twins[twins["twin_role"].eq("positive")].set_index("pair_id")
    ctl = twins[twins["twin_role"].eq("unlabeled_twin")].set_index("pair_id")
    common = pos.index.intersection(ctl.index)
    pos = pos.loc[common]
    ctl = ctl.loc[common]

    p_core = pos["lit_core_texture"].astype(float)
    c_core = ctl["lit_core_texture"].astype(float)
    p70 = pos["lit_sand_gt70"].astype(float)
    c70 = ctl["lit_sand_gt70"].astype(float)
    p75 = pos["lit_sand_gt75"].astype(float)
    c75 = ctl["lit_sand_gt75"].astype(float)
    pw = pd.to_numeric(pos["lit_wet_fine_interaction"], errors="coerce")
    cw = pd.to_numeric(ctl["lit_wet_fine_interaction"], errors="coerce")

    valid = pw.notna() & cw.notna()
    c_no_worse = (c_core >= p_core) & (c70 <= p70) & (c75 <= p75) & (cw <= pw)
    c_strict = (c_core > p_core) | (c70 < p70) | (c75 < p75) | (cw < pw)
    p_no_worse = (p_core >= c_core) & (p70 <= c70) & (p75 <= c75) & (pw <= cw)
    p_strict = (p_core > c_core) | (p70 < c70) | (p75 < c75) | (pw < cw)

    control_dominates = valid & c_no_worse & c_strict
    positive_dominates = valid & p_no_worse & p_strict

    selected = ctl.loc[control_dominates].copy()
    psel = pos.loc[control_dominates]
    selected["positive_twin_field_id"] = psel["current_field_id"].to_numpy()
    selected["positive_twin_match_distance"] = psel["match_distance"].to_numpy()
    selected["delta_wet_fine_control_minus_positive"] = (
        pd.to_numeric(selected["lit_wet_fine_interaction"], errors="coerce").to_numpy()
        - pd.to_numeric(psel["lit_wet_fine_interaction"], errors="coerce").to_numpy()
    )
    selected["control_core_minus_positive"] = (
        selected["lit_core_texture"].astype(int).to_numpy()
        - psel["lit_core_texture"].astype(int).to_numpy()
    )
    selected["control_sand70_minus_positive"] = (
        selected["lit_sand_gt70"].astype(int).to_numpy()
        - psel["lit_sand_gt70"].astype(int).to_numpy()
    )
    selected = selected.sort_values(
        ["control_core_minus_positive", "control_sand70_minus_positive",
         "delta_wet_fine_control_minus_positive", "match_distance"],
        ascending=[False, True, True, True],
        kind="mergesort",
    )

    stats = {
        "valid_pairs": int(valid.sum()),
        "unlabeled_twin_literature_dominates": int(control_dominates.sum()),
        "positive_literature_dominates": int(positive_dominates.sum()),
        "incomparable_or_equal": int(valid.sum() - control_dominates.sum() - positive_dominates.sum()),
    }
    return selected, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", default=str(DEFAULT_MATRIX))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    base = prepare_frame(Path(args.matrix))
    # Reuse C4 only for pre-registered rule components; ignore saturated C4 score.
    full = build_literature_prior(base, twi_reference=base["hydrology__twi_mean"])
    full = add_ilr(full)

    twins, matching_diag = greedy_unique_twins(full)
    n_pairs = int(twins["pair_id"].nunique())
    n_positive = int(twins["twin_role"].eq("positive").sum())

    balance = balance_table(twins)
    binary = paired_binary_checks(twins)
    continuous = paired_continuous_checks(twins)

    fold_parts = []
    pred_parts = []
    for model, features in MODELS.items():
        f, p = leave_one_sko_out(twins, model, features)
        fold_parts.append(f)
        pred_parts.append(p)
    folds = pd.concat(fold_parts, ignore_index=True)
    predictions = pd.concat(pred_parts, ignore_index=True)
    model_summary = summarize_models(folds, predictions)
    coefficients = full_coefficients(twins)

    candidates, dominance = literature_dominance_candidates(twins)

    distances = twins.drop_duplicates("pair_id")["match_distance"]
    distance_summary = {
        "p50": float(distances.quantile(.50)),
        "p90": float(distances.quantile(.90)),
        "p95": float(distances.quantile(.95)),
        "max": float(distances.max()),
    }

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    twins_path = out / "near_twin_sample.parquet"
    diag_path = out / "matching_diagnostics.csv"
    balance_path = out / "matching_balance.csv"
    binary_path = out / "paired_literature_binary_checks.csv"
    continuous_path = out / "paired_literature_continuous_checks.csv"
    models_path = out / "model_comparison.csv"
    folds_path = out / "leave_one_sko_out_folds.csv"
    coef_path = out / "full_sample_coefficients.csv"
    cand_path = out / "unlabeled_literature_dominates_positive_twin.csv"

    twins.to_parquet(twins_path, index=False)
    matching_diag.to_csv(diag_path, index=False, encoding="utf-8-sig")
    balance.to_csv(balance_path, index=False, encoding="utf-8-sig")
    binary.to_csv(binary_path, index=False, encoding="utf-8-sig")
    continuous.to_csv(continuous_path, index=False, encoding="utf-8-sig")
    model_summary.to_csv(models_path, index=False, encoding="utf-8-sig")
    folds.to_csv(folds_path, index=False, encoding="utf-8-sig")
    coefficients.to_csv(coef_path, index=False, encoding="utf-8-sig")
    candidates.to_csv(cand_path, index=False, encoding="utf-8-sig")

    report = {
        "schema_version": "akerfro-ertor-literature-tiebreak-c4b-v0a",
        "design": "1:1 unique near-twin matching within municipality x dominant SKO",
        "matching_features": MATCH_FEATURES,
        "matched_pairs": n_pairs,
        "matched_positive_retention_pct_of_3079": 100.0 * n_positive / 3079.0,
        "match_distance": distance_summary,
        "models": MODELS,
        "literature_dominance": dominance,
        "guardrail": (
            "C4b tests whether literature-defined soil information separates historical-use positives "
            "from unlabeled near twins after matching on local geography, area, slope and ÅkerScore. "
            "It still does not identify biological negatives or prove causal agronomic effects."
        ),
        "not_used": (
            "The saturated C4 literature_prior_score is deliberately not used as a tie-breaker. "
            "Clay >30% is reported but not treated as a hard exclusion."
        ),
        "outputs": {
            "twins": str(twins_path),
            "balance": str(balance_path),
            "paired_binary_checks": str(binary_path),
            "paired_continuous_checks": str(continuous_path),
            "model_comparison": str(models_path),
            "folds": str(folds_path),
            "coefficients": str(coef_path),
            "literature_dominant_unlabeled_twins": str(cand_path),
        },
    }
    json_path = out / "c4b_summary.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 120)
    print("ÅkerFrö – Ärter MVP v0a · C4b LITERATURE TIE-BREAKER AMONG NEAR TWINS")
    print("=" * 120)
    print(
        f"Matched pairs: {n_pairs:,} · positive retention: "
        f"{100*n_positive/3079:.1f}% of 3,079"
    )
    print(
        f"Match distance: P50={distance_summary['p50']:.3f} "
        f"P90={distance_summary['p90']:.3f} P95={distance_summary['p95']:.3f} "
        f"max={distance_summary['max']:.3f}"
    )

    print("\nMATCHING BALANCE")
    print(balance.to_string(index=False, formatters={
        "positive_mean": lambda v: f"{v:.4f}",
        "control_mean": lambda v: f"{v:.4f}",
        "smd": lambda v: f"{v:+.4f}",
        "median_abs_pair_difference": lambda v: f"{v:.4f}",
        "p90_abs_pair_difference": lambda v: f"{v:.4f}",
    }))

    print("\nPAIRED PRE-REGISTERED LITERATURE CHECKS")
    print(binary.to_string(index=False, formatters={
        "positive_share_pct": lambda v: f"{v:.2f}",
        "twin_share_pct": lambda v: f"{v:.2f}",
        "paired_difference_pp": lambda v: f"{v:+.2f}",
    }))

    print("\nPAIRED CONTINUOUS TEXTURE/HYDROLOGY CHECKS")
    print(continuous.to_string(index=False, formatters={
        "positive_median": lambda v: f"{v:.3f}",
        "twin_median": lambda v: f"{v:.3f}",
        "median_paired_difference": lambda v: f"{v:+.3f}",
        "mean_paired_difference": lambda v: f"{v:+.3f}",
    }))

    print("\nNEAR-TWIN MODEL CHALLENGE")
    print(model_summary.to_string(index=False, formatters={
        "fold_auc_mean": lambda v: f"{v:.3f}",
        "fold_auc_median": lambda v: f"{v:.3f}",
        "fold_auc_min": lambda v: f"{v:.3f}",
        "fold_auc_max": lambda v: f"{v:.3f}",
        "pooled_out_of_sko_auc": lambda v: f"{v:.3f}",
        "gain_vs_matchvars": lambda v: f"{v:+.3f}",
    }))

    print("\nLITERATURE PARTIAL-ORDER DOMINANCE")
    print(
        f"  valid pairs: {dominance['valid_pairs']:,}\n"
        f"  unlabeled twin literature-dominates historical positive: "
        f"{dominance['unlabeled_twin_literature_dominates']:,}\n"
        f"  historical positive literature-dominates unlabeled twin: "
        f"{dominance['positive_literature_dominates']:,}\n"
        f"  equal/incomparable: {dominance['incomparable_or_equal']:,}"
    )

    if len(candidates):
        show = [
            "current_field_id", "positive_twin_field_id", "municipality",
            "static__field_area_m2", "topography__slope_p90_deg",
            "akerscore__akerscore_soil_p50", "soil__clay_mean",
            "soil__silt_mean", "soil__sand_mean", "lit_core_texture",
            "lit_sand_gt70", "lit_wet_fine_interaction", "match_distance",
        ]
        print("\nTOP 20 UNLABELED TWINS FAVOURED BY FIXED LITERATURE CRITERIA")
        print(candidates[[c for c in show if c in candidates.columns]].head(20).to_string(index=False))

    print("\nGUARDRAIL")
    print(report["guardrail"])
    print("\nNOTE")
    print(report["not_used"])
    print(f"\nNear twins: {twins_path}")
    print(f"Matching balance: {balance_path}")
    print(f"Model comparison: {models_path}")
    print(f"Literature-dominant unlabeled twins: {cand_path}")
    print(f"Summary: {json_path}")
    print("=" * 120)
    print("C4b LITERATURE TIE-BREAKER: PASS")
    print("=" * 120)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
