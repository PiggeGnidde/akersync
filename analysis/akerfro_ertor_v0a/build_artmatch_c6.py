#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerFrö – Ärter MVP v0a · C6 candidate product score: ÄrtMatch.

Transparent physical/structural field score on 0-100 scale.

Frozen candidate policy weights for C6:
  65% slope desirability
  25% ÅkerScore
  10% weak residual texture component

These weights are deliberately NOT optimized against the same historical pea
labels. They encode the evidence ordering from C2-C5b:
  slope strongest and robust,
  ÅkerScore secondary,
  compositional texture weak but reproducible.

Excluded by design:
  area, rotation, processor distance/logistics, current crop, contracts.
Those belong in ÄrtKandidat, not physical ÄrtMatch.

Score semantics:
  relative ranking among current Skåne fields, NOT agronomic probability.
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

from analysis.akerfro_ertor_v0a.literature_tiebreak_c4b import add_ilr  # noqa: E402
from analysis.akerfro_ertor_v0a.matched_ranking_c3 import prepare_frame  # noqa: E402
from analysis.akerfro_ertor_v0a.residual_texture_c5b import (  # noqa: E402
    MATCH_FEATURES,
    QUAD_ILR,
)

try:
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.preprocessing import StandardScaler
except Exception as exc:  # pragma: no cover
    raise RuntimeError("C6 requires scikit-learn") from exc

DEFAULT_MATRIX = ROOT / "work" / "akerfro_ertor_v0a" / "positive_profile_c1" / "field_feature_matrix.parquet"
DEFAULT_TWINS = ROOT / "work" / "akerfro_ertor_v0a" / "literature_tiebreak_c4b" / "near_twin_sample.parquet"
DEFAULT_OUT = ROOT / "data" / "derived" / "akerfro_ertor_v0a"

SLOPE_COL = "topography__slope_p90_deg"
AKERSCORE_COL = "akerscore__akerscore_soil_p50"

WEIGHTS = {
    "slope": 0.65,
    "akerscore": 0.25,
    "texture": 0.10,
}

TEXTURE_MODEL_FEATURES = MATCH_FEATURES + QUAD_ILR


def percentile_score(values: pd.Series, reference: pd.Series, higher_is_better: bool) -> pd.Series:
    """Mid-rank empirical percentile score 0..100 against a reference population."""
    ref = pd.to_numeric(reference, errors="coerce").dropna().to_numpy(float)
    ref.sort()
    x = pd.to_numeric(values, errors="coerce").to_numpy(float)
    out = np.full(len(x), np.nan, dtype=float)
    valid = np.isfinite(x)
    if len(ref) == 0:
        return pd.Series(out, index=values.index)

    left = np.searchsorted(ref, x[valid], side="left")
    right = np.searchsorted(ref, x[valid], side="right")
    # Mid-rank percentile reduces arbitrary jumps when values are tied.
    pct = (left + right) / (2.0 * len(ref))
    if not higher_is_better:
        pct = 1.0 - pct
    out[valid] = 100.0 * pct
    return pd.Series(out, index=values.index)


def fit_texture_residual_model(twins: pd.DataFrame):
    work = twins.copy()
    work["y"] = work["twin_role"].eq("positive").astype(int)

    imputer = SimpleImputer(strategy="median")
    scaler = StandardScaler()
    x = imputer.fit_transform(work[TEXTURE_MODEL_FEATURES])
    xz = scaler.fit_transform(x)

    clf = LogisticRegression(
        C=1.0,
        solver="liblinear",
        max_iter=2000,
        class_weight="balanced",
        random_state=0,
    )
    clf.fit(xz, work["y"])
    return imputer, scaler, clf


def texture_contribution(
    frame: pd.DataFrame,
    imputer: SimpleImputer,
    scaler: StandardScaler,
    clf: LogisticRegression,
) -> pd.Series:
    """Texture-only standardized-logit contribution from the full C5b B2 model."""
    x = imputer.transform(frame[TEXTURE_MODEL_FEATURES])
    xz = scaler.transform(x)
    coefs = clf.coef_[0]
    start = len(MATCH_FEATURES)
    contribution = xz[:, start:] @ coefs[start:]
    return pd.Series(contribution, index=frame.index)


def product_status(frame: pd.DataFrame) -> pd.Series:
    slope_ok = pd.to_numeric(frame[SLOPE_COL], errors="coerce").notna()
    score_ok = pd.to_numeric(frame[AKERSCORE_COL], errors="coerce").notna()
    texture_ok = frame[QUAD_ILR].apply(pd.to_numeric, errors="coerce").notna().all(axis=1)

    status = pd.Series("OK", index=frame.index, dtype="string")
    status.loc[slope_ok & score_ok & ~texture_ok] = "CORE_OK_TEXTURE_MISSING"
    status.loc[~slope_ok | ~score_ok] = "INSUFFICIENT_CORE"
    return status


def build_score(full: pd.DataFrame, twins: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    out = add_ilr(full)
    twin_model = add_ilr(twins)

    imputer, scaler, clf = fit_texture_residual_model(twin_model)
    texture_logit = texture_contribution(out, imputer, scaler, clf)
    twin_texture_logit = texture_contribution(twin_model, imputer, scaler, clf)

    out["artmatch_slope_component"] = percentile_score(
        out[SLOPE_COL], out[SLOPE_COL], higher_is_better=False
    )
    out["artmatch_akerscore_component"] = percentile_score(
        out[AKERSCORE_COL], out[AKERSCORE_COL], higher_is_better=True
    )
    out["texture_residual_logit"] = texture_logit
    out["artmatch_texture_component"] = percentile_score(
        texture_logit, texture_logit, higher_is_better=True
    )
    out["artmatch_status"] = product_status(out)

    # Texture is optional. Missing texture is explicitly neutral, not imputed
    # as good or bad in the user-facing component.
    texture_valid = out[QUAD_ILR].apply(pd.to_numeric, errors="coerce").notna().all(axis=1)
    out.loc[~texture_valid, "artmatch_texture_component"] = 50.0

    core_ok = out["artmatch_status"].ne("INSUFFICIENT_CORE")
    out["artmatch_score"] = np.nan
    out.loc[core_ok, "artmatch_score"] = (
        WEIGHTS["slope"] * out.loc[core_ok, "artmatch_slope_component"]
        + WEIGHTS["akerscore"] * out.loc[core_ok, "artmatch_akerscore_component"]
        + WEIGHTS["texture"] * out.loc[core_ok, "artmatch_texture_component"]
    )
    out["artmatch_score"] = out["artmatch_score"].clip(0.0, 100.0)

    # Explainability: point contributions sum exactly to score.
    out["artmatch_points_slope"] = WEIGHTS["slope"] * out["artmatch_slope_component"]
    out["artmatch_points_akerscore"] = WEIGHTS["akerscore"] * out["artmatch_akerscore_component"]
    out["artmatch_points_texture"] = WEIGHTS["texture"] * out["artmatch_texture_component"]

    coef_rows = []
    for feature, coef in zip(TEXTURE_MODEL_FEATURES, clf.coef_[0]):
        coef_rows.append({
            "feature": feature,
            "standardized_logit_coefficient": float(coef),
            "role": "match_covariate" if feature in MATCH_FEATURES else "texture_residual",
        })

    model_info = {
        "texture_model_training_rows": int(len(twin_model)),
        "texture_model_pairs": int(twin_model["pair_id"].nunique()),
        "texture_coefficients": coef_rows,
        "twin_texture_contribution_sd": float(twin_texture_logit.std(ddof=1)),
    }
    return out, model_info


def distribution_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, g in [
        ("all_scored", frame[frame["artmatch_score"].notna()]),
        ("historical_positive", frame[frame["is_positive"] & frame["artmatch_score"].notna()]),
        ("unlabeled", frame[(~frame["is_positive"]) & frame["artmatch_score"].notna()]),
    ]:
        x = pd.to_numeric(g["artmatch_score"], errors="coerce").dropna()
        rows.append({
            "group": label,
            "n": int(len(x)),
            "mean": float(x.mean()) if len(x) else np.nan,
            "p10": float(x.quantile(.10)) if len(x) else np.nan,
            "p25": float(x.quantile(.25)) if len(x) else np.nan,
            "p50": float(x.quantile(.50)) if len(x) else np.nan,
            "p75": float(x.quantile(.75)) if len(x) else np.nan,
            "p90": float(x.quantile(.90)) if len(x) else np.nan,
        })
    return pd.DataFrame(rows)


def decile_enrichment(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame[frame["artmatch_score"].notna()].copy()
    work["score_decile"] = pd.qcut(
        work["artmatch_score"], q=10, labels=False, duplicates="drop"
    ) + 1
    overall = float(work["is_positive"].mean())
    rows = []
    for decile, g in work.groupby("score_decile", sort=True):
        rate = float(g["is_positive"].mean())
        rows.append({
            "score_decile": int(decile),
            "n_fields": int(len(g)),
            "n_historical_positive": int(g["is_positive"].sum()),
            "positive_rate_pct": 100.0 * rate,
            "enrichment_vs_all_scored": rate / overall if overall > 0 else np.nan,
            "score_min": float(g["artmatch_score"].min()),
            "score_max": float(g["artmatch_score"].max()),
        })
    return pd.DataFrame(rows)


def pairwise_product_check(scored: pd.DataFrame, twins: pd.DataFrame) -> dict:
    lookup = scored.set_index("current_field_id")["artmatch_score"]
    t = twins[["pair_id", "current_field_id", "twin_role"]].copy()
    t["score"] = t["current_field_id"].map(lookup)
    wide = t.pivot(index="pair_id", columns="twin_role", values="score").dropna()
    diff = wide["positive"] - wide["unlabeled_twin"]
    pos = int((diff > 1e-12).sum())
    neg = int((diff < -1e-12).sum())
    ties = int((diff.abs() <= 1e-12).sum())
    denom = pos + neg
    return {
        "n_pairs_scored": int(len(wide)),
        "historical_positive_higher": pos,
        "unlabeled_twin_higher": neg,
        "ties": ties,
        "pairwise_accuracy": pos / denom if denom else np.nan,
        "mean_score_difference": float(diff.mean()) if len(diff) else np.nan,
        "median_score_difference": float(diff.median()) if len(diff) else np.nan,
    }


def rank_auc(frame: pd.DataFrame) -> float:
    q = frame[frame["artmatch_score"].notna()].copy()
    if q["is_positive"].nunique() < 2:
        return np.nan
    return float(roc_auc_score(q["is_positive"].astype(int), q["artmatch_score"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", default=str(DEFAULT_MATRIX))
    ap.add_argument("--twins", default=str(DEFAULT_TWINS))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    matrix_path = Path(args.matrix)
    twin_path = Path(args.twins)
    if not twin_path.exists():
        raise FileNotFoundError("Run C4b first; near_twin_sample.parquet is missing")

    full = prepare_frame(matrix_path)
    twins = pd.read_parquet(twin_path)
    scored, texture_info = build_score(full, twins)

    if len(scored) != 128636 or int(scored["is_positive"].sum()) != 3079:
        raise RuntimeError("C6 population anchors failed")

    dist = distribution_summary(scored)
    enrichment = decile_enrichment(scored)
    twin_check = pairwise_product_check(scored, twins)
    auc = rank_auc(scored)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    fields_path = out / "artmatch_v0a_fields.parquet"
    csv_path = out / "artmatch_v0a_fields.csv"
    dist_path = out / "artmatch_v0a_distribution.csv"
    enrichment_path = out / "artmatch_v0a_decile_enrichment.csv"
    top_path = out / "artmatch_v0a_top100.csv"
    coef_path = out / "artmatch_v0a_texture_coefficients.csv"

    export_cols = [
        "current_field_id", "current_block_id", "current_skiftesbeteckning",
        "municipality", "dominant_sko_id_c2", "is_positive",
        "static__field_area_m2", SLOPE_COL, AKERSCORE_COL,
        "soil__clay_mean", "soil__silt_mean", "soil__sand_mean",
        "artmatch_slope_component", "artmatch_akerscore_component",
        "artmatch_texture_component", "texture_residual_logit",
        "artmatch_points_slope", "artmatch_points_akerscore",
        "artmatch_points_texture", "artmatch_score", "artmatch_status",
    ]
    export_cols = [c for c in export_cols if c in scored.columns]
    scored[export_cols].to_parquet(fields_path, index=False)
    scored[export_cols].to_csv(csv_path, index=False, encoding="utf-8-sig")
    dist.to_csv(dist_path, index=False, encoding="utf-8-sig")
    enrichment.to_csv(enrichment_path, index=False, encoding="utf-8-sig")
    scored[export_cols].sort_values(
        "artmatch_score", ascending=False, na_position="last"
    ).head(100).to_csv(top_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(texture_info["texture_coefficients"]).to_csv(
        coef_path, index=False, encoding="utf-8-sig"
    )

    status_counts = scored["artmatch_status"].value_counts(dropna=False).to_dict()
    report = {
        "schema_version": "akerfro-ertor-artmatch-c6-v0a-candidate",
        "population_fields": int(len(scored)),
        "historical_positive_fields": int(scored["is_positive"].sum()),
        "score_semantics": "relative physical/structural pea-match ranking among current Skåne fields; not probability",
        "weights": WEIGHTS,
        "component_definitions": {
            "slope": "inverse whole-Skåne empirical percentile of slope P90; flatter is better",
            "akerscore": "whole-Skåne empirical percentile of ÅkerScore P50; higher is better",
            "texture": (
                "whole-Skåne empirical percentile of texture-only standardized-logit contribution "
                "from the C5b quadratic ILR near-twin model"
            ),
        },
        "excluded_from_artmatch": [
            "field area",
            "crop rotation/history eligibility",
            "processor distance/logistics",
            "current crop",
            "contracts",
            "drought/irrigation risk",
        ],
        "missing_policy": {
            "slope_or_akerscore_missing": "ÄrtMatch null; INSUFFICIENT_CORE",
            "texture_missing_only": "texture component = neutral 50; CORE_OK_TEXTURE_MISSING",
        },
        "status_counts": {str(k): int(v) for k, v in status_counts.items()},
        "raw_historical_selection_rank_auc": auc,
        "near_twin_product_pairwise": twin_check,
        "texture_model": texture_info,
        "guardrail": (
            "Weights are transparent product-policy weights reflecting evidence strength, not fitted agronomic optima. "
            "ÄrtMatch must stay separate from ÄrtKandidat, which will add rotation, area, logistics and other current-season constraints."
        ),
        "outputs": {
            "fields_parquet": str(fields_path),
            "fields_csv": str(csv_path),
            "distribution": str(dist_path),
            "decile_enrichment": str(enrichment_path),
            "top100": str(top_path),
            "texture_coefficients": str(coef_path),
        },
    }
    json_path = out / "artmatch_v0a_summary.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 124)
    print("ÅkerFrö – Ärter MVP v0a · C6 ÄRTMATCH CANDIDATE PRODUCT SCORE")
    print("=" * 124)
    print(f"Fields: {len(scored):,} · historical positives: {int(scored['is_positive'].sum()):,}")
    print(
        "Weights: slope 65% · ÅkerScore 25% · weak residual texture 10% "
        "(fixed policy weights; not label-optimized)"
    )
    print("\nSTATUS")
    for k, v in status_counts.items():
        print(f"  {k}: {v:,}")

    print("\nSCORE DISTRIBUTION")
    print(dist.to_string(index=False, formatters={
        "mean": lambda v: f"{v:.2f}",
        "p10": lambda v: f"{v:.2f}",
        "p25": lambda v: f"{v:.2f}",
        "p50": lambda v: f"{v:.2f}",
        "p75": lambda v: f"{v:.2f}",
        "p90": lambda v: f"{v:.2f}",
    }))

    print("\nHISTORICAL POSITIVE ENRICHMENT BY ÄRTMATCH DECILE")
    print(enrichment.to_string(index=False, formatters={
        "positive_rate_pct": lambda v: f"{v:.3f}",
        "enrichment_vs_all_scored": lambda v: f"{v:.2f}x",
        "score_min": lambda v: f"{v:.2f}",
        "score_max": lambda v: f"{v:.2f}",
    }))

    print(f"\nRaw historical-selection rank AUC: {auc:.3f}")
    print(
        "Near-twin product check: historical positive higher "
        f"{twin_check['historical_positive_higher']:,} vs twin higher "
        f"{twin_check['unlabeled_twin_higher']:,} "
        f"=> {100*twin_check['pairwise_accuracy']:.2f}%"
    )

    print("\nTOP 20 ÄRTMATCH FIELDS")
    show = [
        "current_field_id", "municipality", "artmatch_score",
        "artmatch_slope_component", "artmatch_akerscore_component",
        "artmatch_texture_component", SLOPE_COL, AKERSCORE_COL,
    ]
    print(
        scored[show]
        .sort_values("artmatch_score", ascending=False, na_position="last")
        .head(20)
        .to_string(index=False, formatters={
            "artmatch_score": lambda v: f"{v:.2f}",
            "artmatch_slope_component": lambda v: f"{v:.1f}",
            "artmatch_akerscore_component": lambda v: f"{v:.1f}",
            "artmatch_texture_component": lambda v: f"{v:.1f}",
            SLOPE_COL: lambda v: f"{v:.3f}",
            AKERSCORE_COL: lambda v: f"{v:.2f}",
        })
    )

    print("\nEXCLUDED FROM ÄRTMATCH")
    print("  area · rotation · processor/logistics · current crop/contracts · drought/irrigation risk")
    print("\nGUARDRAIL")
    print(report["guardrail"])
    print(f"\nField product: {fields_path}")
    print(f"Distribution: {dist_path}")
    print(f"Decile enrichment: {enrichment_path}")
    print(f"Summary: {json_path}")
    print("=" * 124)
    print("C6 ÄRTMATCH CANDIDATE SCORE: PASS")
    print("=" * 124)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
