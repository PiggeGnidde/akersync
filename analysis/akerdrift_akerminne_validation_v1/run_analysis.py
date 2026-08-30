#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reproduce ÅkerDrift × ÅkerMinne validation v1.0.

Read-only analysis. Core scientific interpretation:
- Raw ÅkerDrift is strongly associated with crop-use patterns.
- ÅkerDrift is also strongly associated with field area.
- After flexible log(area) and local historic-class × SKO × municipality controls,
  the official ÅkerDrift score adds essentially no information to the central
  broad-production-vs-vall choice and only tiny information to rotation metrics.
- A separate secondary endpoint shows a material association with whether
  SINGLE_CROP years are productive broad-production/vall at all.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.interpolate import BSpline
from scipy.stats import norm, spearmanr

VERSION = "akerdrift-akerminne-validation-v1.0"

DRIFT_MEMBER = "akerdrift_hybrid_rc1_selected.csv.gz"
CONTEXT_MEMBER = "field_static_context_selected.csv.gz"
HISTORY_MEMBER = "akerminne_2015_2025_selected.csv.gz"

CEREAL_PATTERN = r"Vete|Korn|Havre|Råg|Rågvete|Blandsäd|Spannmålsförsök|spannmål"
CEREAL_EXCLUDE_LITERAL = "Proteingrödsblandningar"
BROAD_PATTERN = (
    r"Raps|Sockerbet|potatis|ärter|Åkerbön|Sötlupin|Majs|grönsak|lök|"
    r"morot|sallat|kål|broccoli|spenat|pumpa|rödbet|sparris|jordärtskock|"
    r"krydd|selleri|gurka|palsternack|rabarber|purjolök|Oljelin|Hampa|"
    r"Solros|foderbet|Konservärter|Fruktodling|Jordgubbsodling|bärodling"
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def jsonable(v):
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    if isinstance(v, list):
        return [jsonable(x) for x in v]
    if isinstance(v, tuple):
        return [jsonable(x) for x in v]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    return v


def verify_zip_member(z: zipfile.ZipFile, member: str, expected_sha: str) -> bytes:
    try:
        data = z.read(member)
    except KeyError as exc:
        raise RuntimeError(f"missing ZIP member: {member}") from exc
    digest = sha256_bytes(data)
    if digest.lower() != expected_sha.lower():
        raise RuntimeError(
            f"SHA256 mismatch for {member}: expected {expected_sha}, got {digest}"
        )
    return data


def read_csv_gz_bytes(data: bytes, usecols: list[str]) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(data), compression="gzip", usecols=usecols)


def classify_history(history: pd.DataFrame) -> pd.DataFrame:
    """Classify crop names once per unique label, then map back by factor codes."""
    out = history.copy()
    names = out["dominant_crop_name"].fillna("").astype(str)
    codes, uniques = pd.factorize(names, sort=False)
    u = pd.Series(uniques, dtype="string")

    cereal_u = (
        u.str.contains(CEREAL_PATTERN, case=False, regex=True)
        & ~u.str.contains(CEREAL_EXCLUDE_LITERAL, case=False, regex=False)
    ).to_numpy(bool)
    vall_u = (
        u.str.contains("Slåtter och betesvall", case=False, regex=False)
        | u.str.contains("Slåttervall på åker", case=False, regex=False)
        | u.eq("Undantag 2023 miljöyta. Används för vall")
    ).to_numpy(bool)
    broad_u = cereal_u | u.str.contains(BROAD_PATTERN, case=False, regex=True).to_numpy(bool)

    out["is_cereal"] = cereal_u[codes]
    out["is_vall"] = vall_u[codes]
    out["is_broad"] = broad_u[codes]
    out["is_raps"] = u.str.contains("Raps", case=False, regex=False).to_numpy(bool)[codes]
    out["is_sugarbeet"] = u.str.contains("Sockerbet", case=False, regex=True).to_numpy(bool)[codes]
    out["is_potato"] = u.str.contains("potatis", case=False, regex=True).to_numpy(bool)[codes]
    out["is_maize"] = u.str.contains("Majs", case=False, regex=False).to_numpy(bool)[codes]
    return out

def build_field_metrics(good: pd.DataFrame):
    field = (
        good.groupby("current_field_id", sort=False)
        .agg(
            good_years=("history_year", "size"),
            cereal_share=("is_cereal", "mean"),
            vall_share=("is_vall", "mean"),
            broad_share=("is_broad", "mean"),
            broad_n=("is_broad", "sum"),
            vall_n=("is_vall", "sum"),
        )
    )
    field["productive_n"] = field["broad_n"] + field["vall_n"]
    field["broad_vs_vall"] = np.where(
        field["productive_n"] > 0,
        field["broad_n"] / field["productive_n"],
        np.nan,
    )

    productive = good.loc[good["is_broad"] | good["is_vall"]].copy()
    prod = (
        productive.groupby("current_field_id", sort=False)
        .agg(
            productive_n2=("history_year", "size"),
            broad_productive_share=("is_broad", "mean"),
            cereal_productive_share=("is_cereal", "mean"),
            raps_productive_share=("is_raps", "mean"),
            sugarbeet_productive_share=("is_sugarbeet", "mean"),
            potato_productive_share=("is_potato", "mean"),
            maize_productive_share=("is_maize", "mean"),
        )
    )
    return good, productive, field, prod


def build_rotation_metrics(productive: pd.DataFrame) -> pd.DataFrame:
    p = productive[
        [
            "current_field_id",
            "history_year",
            "is_cereal",
            "is_vall",
            "is_raps",
            "is_sugarbeet",
            "is_potato",
            "is_maize",
        ]
    ].copy()

    conditions = [
        p["is_cereal"],
        p["is_vall"],
        p["is_raps"],
        p["is_sugarbeet"],
        p["is_potato"],
        p["is_maize"],
    ]
    labels = ["cereal", "vall", "raps", "sugarbeet", "potato", "maize"]
    p["rotation_category"] = np.select(conditions, labels, default="other_broad")
    p.sort_values(["current_field_id", "history_year"], inplace=True)

    ct = p.groupby(["current_field_id", "rotation_category"]).size().unstack(fill_value=0)
    categories = labels + ["other_broad"]
    for c in categories:
        if c not in ct.columns:
            ct[c] = 0
    ct = ct[categories]

    n = ct.sum(axis=1)
    probs = ct.div(n, axis=0)
    entropy = -(
        probs.where(probs > 0) * np.log(probs.where(probs > 0))
    ).sum(axis=1) / np.log(8.0)
    category_count = (ct > 0).sum(axis=1)

    prev_field = p["current_field_id"].shift()
    prev_cat = p["rotation_category"].shift()
    prev_year = p["history_year"].shift()
    consecutive_calendar = (
        p["current_field_id"].eq(prev_field)
        & (p["history_year"] - prev_year).eq(1)
    )
    p["calendar_switch"] = np.where(
        consecutive_calendar,
        p["rotation_category"].ne(prev_cat).astype(float),
        np.nan,
    )
    switch = p.groupby("current_field_id")["calendar_switch"].mean()

    return pd.DataFrame(
        {
            "productive_n3": n,
            "rotation_category_count": category_count,
            "rotation_entropy": entropy,
            "rotation_calendar_switch_rate": switch,
        }
    )


def make_quintile(values: pd.Series) -> pd.Series:
    ranked = values.rank(method="first")
    return pd.qcut(ranked, 5, labels=[1, 2, 3, 4, 5]).astype(int)


def bs8_matrix(log_area: np.ndarray) -> np.ndarray:
    """Patsy-compatible bs(x, df=8, degree=3, include_intercept=False)-1."""
    x = np.asarray(log_area, dtype=float)
    if not np.all(np.isfinite(x)):
        raise ValueError("non-finite log(area) in spline input")
    degree = 3
    interior = np.quantile(x, np.arange(1, 6, dtype=float) / 6.0)
    knots = np.r_[np.repeat(x.min(), degree + 1), interior, np.repeat(x.max(), degree + 1)]
    n_basis = len(knots) - degree - 1
    coeff = np.eye(n_basis)
    full = BSpline(knots, coeff, degree, extrapolate=False)(x)
    # Patsy drops the first basis function when include_intercept=False.
    return np.asarray(full[:, 1:], dtype=float)


def cluster_ols(y: np.ndarray, X: np.ndarray, groups: np.ndarray):
    y = np.asarray(y, dtype=float)
    X = np.asarray(X, dtype=float)
    groups = np.asarray(groups)
    n, k = X.shape
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    resid = y - X @ beta
    bread = np.linalg.inv(X.T @ X)

    codes, uniques = pd.factorize(groups, sort=False)
    G = len(uniques)
    scores = np.zeros((G, k), dtype=float)
    np.add.at(scores, codes, X * resid[:, None])
    meat = scores.T @ scores
    correction = (G / (G - 1.0)) * ((n - 1.0) / (n - k))
    cov = correction * (bread @ meat @ bread)
    se = np.sqrt(np.maximum(np.diag(cov), 0.0))
    z = np.divide(beta, se, out=np.full_like(beta, np.nan), where=se > 0)
    p = 2.0 * norm.sf(np.abs(z))
    return beta, se, p


def controlled_fit(df: pd.DataFrame, endpoint: str) -> dict:
    work = df.loc[df[endpoint].notna()].copy()
    log_area = np.log(work["area_ha"].clip(lower=1e-12).to_numpy(float))
    B = bs8_matrix(log_area)
    basis_cols = [f"area_bs_{i}" for i in range(B.shape[1])]

    tmp = pd.DataFrame(B, columns=basis_cols, index=work.index)
    tmp["drift"] = work["akerdrift_score"].to_numpy(float)
    tmp["y"] = work[endpoint].to_numpy(float)
    tmp["group"] = work["_group_id"].to_numpy(int)

    cols = ["y", "drift"] + basis_cols
    dm = tmp[cols] - tmp.groupby("group", sort=False)[cols].transform("mean")
    y = dm["y"].to_numpy(float)
    X0 = dm[basis_cols].to_numpy(float)
    X1 = dm[["drift"] + basis_cols].to_numpy(float)

    b0 = np.linalg.lstsq(X0, y, rcond=None)[0]
    pred0 = X0 @ b0
    beta, se, p = cluster_ols(y, X1, tmp["group"].to_numpy())
    pred1 = X1 @ beta

    denom = float(np.sum(y * y))
    r2_base = 1.0 - float(np.sum((y - pred0) ** 2)) / denom
    r2_aug = 1.0 - float(np.sum((y - pred1) ** 2)) / denom

    effect = float(beta[0] * 10.0)
    effect_se = float(se[0] * 10.0)
    return {
        "n": int(len(work)),
        "effect_per_10": effect,
        "effect_per_10_pp": effect * 100.0,
        "ci_low": effect - 1.96 * effect_se,
        "ci_high": effect + 1.96 * effect_se,
        "ci_low_pp": (effect - 1.96 * effect_se) * 100.0,
        "ci_high_pp": (effect + 1.96 * effect_se) * 100.0,
        "p_value": float(p[0]),
        "base_within_r2": r2_base,
        "aug_within_r2": r2_aug,
        "delta_r2": r2_aug - r2_base,
    }


def approx_check(path: str, actual: float, spec: dict, errors: list[str]):
    target = float(spec["value"])
    tol = float(spec["tol"])
    if not math.isfinite(actual) or abs(actual - target) > tol:
        errors.append(f"{path}: expected {target} ± {tol}, got {actual}")


def get_nested(d: dict, path: str):
    cur = d
    for part in path.split("."):
        cur = cur[part]
    return cur


def verify_results(results: dict, expected: dict):
    errors: list[str] = []
    for path, target in expected.get("exact", {}).items():
        actual = get_nested(results, path)
        if int(actual) != int(target):
            errors.append(f"{path}: expected {target}, got {actual}")

    for path, spec in expected.get("approx", {}).items():
        approx_check(path, float(get_nested(results, path)), spec, errors)

    inv = expected.get("invariants", {})
    if abs(results["controlled"]["broad_vs_vall"]["effect_per_10_pp"]) > inv["primary_broad_vs_vall_abs_effect_pp_max"]:
        errors.append("primary broad-vs-vall effect exceeds frozen null-materiality guardrail")
    if results["controlled"]["broad_vs_vall"]["delta_r2"] > inv["primary_broad_vs_vall_delta_r2_max"]:
        errors.append("primary broad-vs-vall delta R2 exceeds frozen guardrail")
    if abs(results["rotation"]["controlled"]["category_count"]["effect_per_10"]) > inv["rotation_category_count_abs_effect_max"]:
        errors.append("rotation category-count effect exceeds frozen guardrail")
    if abs(results["rotation"]["controlled"]["entropy"]["effect_per_10"]) > inv["rotation_entropy_abs_effect_max"]:
        errors.append("rotation entropy effect exceeds frozen guardrail")
    if abs(results["rotation"]["controlled"]["calendar_switch"]["effect_per_10"]) > inv["rotation_calendar_switch_abs_effect_max"]:
        errors.append("rotation switch effect exceeds frozen guardrail")
    if results["productive_use"]["effect_per_10_pp"] < inv["productive_use_effect_pp_min"]:
        errors.append("productive-use effect falls below frozen positive-signal guardrail")
    if results["productive_use"]["delta_r2"] < inv["productive_use_delta_r2_min"]:
        errors.append("productive-use delta R2 falls below frozen positive-signal guardrail")

    if errors:
        raise RuntimeError("RESULT VERIFICATION FAILED:\n" + "\n".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--drift-input", required=True)
    parser.add_argument("--history-input", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    here = Path(__file__).resolve().parent
    manifest = load_json(here / "manifests" / "input_manifest.json")
    expected = load_json(here / "expected_results.json")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    file_specs = {(x["source_group"], x["relative_path"]): x for x in manifest["files"]}

    with zipfile.ZipFile(args.drift_input) as zd:
        drift_bytes = verify_zip_member(
            zd,
            DRIFT_MEMBER,
            file_specs[("akerdrift", DRIFT_MEMBER)]["sha256"],
        )
        drift = read_csv_gz_bytes(
            drift_bytes,
            ["field_key", "area_ha", "akerdrift_score", "drift_model_version"],
        )

    with zipfile.ZipFile(args.history_input) as zh:
        context_bytes = verify_zip_member(
            zh,
            CONTEXT_MEMBER,
            file_specs[("akerminne_context", CONTEXT_MEMBER)]["sha256"],
        )
        history_bytes = verify_zip_member(
            zh,
            HISTORY_MEMBER,
            file_specs[("akerminne_context", HISTORY_MEMBER)]["sha256"],
        )
        context = read_csv_gz_bytes(
            context_bytes,
            [
                "current_field_id",
                "municipality",
                "dominant_soil_class",
                "dominant_soil_class_share",
                "soil_class_coverage_unique",
                "mixed_soil_class",
                "dominant_sko_id",
            ],
        )
        history = read_csv_gz_bytes(
            history_bytes,
            ["current_field_id", "history_year", "dominant_crop_name", "status"],
        )

    if len(drift) != 128636 or len(context) != 128636 or len(history) != 1414996:
        raise RuntimeError("input row-count sanity check failed")
    versions = sorted(drift["drift_model_version"].dropna().astype(str).unique().tolist())
    if versions != ["akerdrift-fast-v2-hybrid-rc1"]:
        raise RuntimeError(f"unexpected ÅkerDrift model versions: {versions}")
    if int(drift["akerdrift_score"].notna().sum()) != 128597:
        raise RuntimeError("unexpected number of scored ÅkerDrift rows")

    print("INPUT VERIFICATION: PASS")
    print(f"Loaded drift={len(drift):,}, context={len(context):,}, history={len(history):,}")

    good = history.loc[history["status"].eq("SINGLE_CROP")].copy()
    good = classify_history(good)
    good, productive, field_metrics, productive_metrics = build_field_metrics(good)
    rotation_metrics = build_rotation_metrics(productive)

    # Raw descriptive cohort.
    raw = drift.merge(field_metrics, left_on="field_key", right_index=True, how="inner")
    raw = raw.loc[raw["akerdrift_score"].notna() & raw["good_years"].ge(8)].copy()

    raw_stats = {
        "spearman_drift_area": float(spearmanr(raw["akerdrift_score"], raw["area_ha"]).statistic),
        "spearman_drift_cereal": float(spearmanr(raw["akerdrift_score"], raw["cereal_share"]).statistic),
        "spearman_drift_vall": float(spearmanr(raw["akerdrift_score"], raw["vall_share"]).statistic),
        "spearman_drift_broad": float(spearmanr(raw["akerdrift_score"], raw["broad_share"]).statistic),
        "spearman_logarea_cereal": float(spearmanr(np.log(raw["area_ha"]), raw["cereal_share"]).statistic),
        "spearman_logarea_vall": float(spearmanr(np.log(raw["area_ha"]), raw["vall_share"]).statistic),
        "spearman_logarea_broad": float(spearmanr(np.log(raw["area_ha"]), raw["broad_share"]).statistic),
    }

    base = (
        context.merge(
            drift[["field_key", "area_ha", "akerdrift_score"]],
            left_on="current_field_id",
            right_on="field_key",
            how="left",
            validate="one_to_one",
        )
        .merge(
            field_metrics[["good_years"]],
            left_on="current_field_id",
            right_index=True,
            how="left",
            validate="one_to_one",
        )
    )

    strict_mask = (
        base["dominant_soil_class"].between(5, 10)
        & base["akerdrift_score"].notna()
        & base["soil_class_coverage_unique"].ge(0.95)
        & base["dominant_soil_class_share"].ge(0.95)
        & (~base["mixed_soil_class"].fillna(False))
        & base["good_years"].ge(8)
    )
    strict = base.loc[strict_mask].copy()
    strict = strict.merge(
        field_metrics.drop(columns=["good_years"]),
        left_on="current_field_id",
        right_index=True,
        how="left",
        validate="one_to_one",
    )

    group_keys = ["dominant_soil_class", "dominant_sko_id", "municipality"]
    strict["_group_n"] = strict.groupby(group_keys, dropna=False)["current_field_id"].transform("size")
    local = strict.loc[strict["_group_n"].ge(25)].copy()
    local["_group_id"] = local.groupby(group_keys, dropna=False, sort=True).ngroup().astype(int)
    local["area_q"] = local.groupby(group_keys, dropna=False)["area_ha"].transform(make_quintile)
    local["drift_q"] = local.groupby(group_keys, dropna=False)["akerdrift_score"].transform(make_quintile)

    work = local.merge(
        productive_metrics,
        left_on="current_field_id",
        right_index=True,
        how="left",
        validate="one_to_one",
    )
    work = work.loc[work["productive_n2"].ge(4)].copy()

    def qdiff(df: pd.DataFrame, qcol: str, endpoint: str) -> float:
        return float(df.loc[df[qcol].eq(5), endpoint].mean() - df.loc[df[qcol].eq(1), endpoint].mean())

    quintile = {
        "area_q5_minus_q1_broad_vs_vall_pp": 100.0 * qdiff(work, "area_q", "broad_vs_vall"),
        "area_q5_minus_q1_cereal_productive_pp": 100.0 * qdiff(work, "area_q", "cereal_productive_share"),
        "drift_q5_minus_q1_broad_vs_vall_pp": 100.0 * qdiff(work, "drift_q", "broad_vs_vall"),
        "drift_q5_minus_q1_cereal_productive_pp": 100.0 * qdiff(work, "drift_q", "cereal_productive_share"),
    }

    controlled = {
        "broad_vs_vall": controlled_fit(work, "broad_productive_share"),
        "cereal_productive": controlled_fit(work, "cereal_productive_share"),
        "raps": controlled_fit(work, "raps_productive_share"),
        "sugarbeet": controlled_fit(work, "sugarbeet_productive_share"),
        "potato": controlled_fit(work, "potato_productive_share"),
        "maize": controlled_fit(work, "maize_productive_share"),
    }

    local["productive_use_share"] = local["broad_share"] + local["vall_share"]
    productive_use = controlled_fit(local, "productive_use_share")

    rot = local.merge(
        rotation_metrics,
        left_on="current_field_id",
        right_index=True,
        how="inner",
        validate="one_to_one",
    )
    rot = rot.loc[rot["productive_n3"].ge(4)].copy()

    rotation = {
        "area_q5_minus_q1_category_count": qdiff(rot, "area_q", "rotation_category_count"),
        "area_q5_minus_q1_entropy": qdiff(rot, "area_q", "rotation_entropy"),
        "area_q5_minus_q1_calendar_switch_pp": 100.0 * qdiff(rot, "area_q", "rotation_calendar_switch_rate"),
        "drift_q5_minus_q1_category_count": qdiff(rot, "drift_q", "rotation_category_count"),
        "drift_q5_minus_q1_entropy": qdiff(rot, "drift_q", "rotation_entropy"),
        "drift_q5_minus_q1_calendar_switch_pp": 100.0 * qdiff(rot, "drift_q", "rotation_calendar_switch_rate"),
        "controlled": {
            "category_count": controlled_fit(rot, "rotation_category_count"),
            "entropy": controlled_fit(rot, "rotation_entropy"),
            "calendar_switch": controlled_fit(rot, "rotation_calendar_switch_rate"),
        },
    }

    results = {
        "version": VERSION,
        "inventory": {
            "drift_rows": int(len(drift)),
            "drift_scored_rows": int(drift["akerdrift_score"].notna().sum()),
            "history_rows": int(len(history)),
            "context_rows": int(len(context)),
            "raw_cohort_n": int(len(raw)),
            "strict_cohort_n": int(len(strict)),
            "local_cohort_n": int(len(local)),
            "local_group_n": int(local["_group_id"].nunique()),
            "productive4_n": int(len(work)),
            "rotation_switch_n": int(rot["rotation_calendar_switch_rate"].notna().sum()),
        },
        "raw": raw_stats,
        "quintile": quintile,
        "controlled": controlled,
        "productive_use": productive_use,
        "rotation": rotation,
    }

    # Flatten convenience values used by expected_results paths.
    results["controlled"]["broad_vs_vall"]["effect_per_10_pp"] = controlled["broad_vs_vall"]["effect_per_10_pp"]
    results["controlled"]["cereal_productive"]["effect_per_10_pp"] = controlled["cereal_productive"]["effect_per_10_pp"]
    for k in ["raps", "sugarbeet", "potato", "maize"]:
        results["controlled"][k]["effect_per_10_pp"] = controlled[k]["effect_per_10_pp"]
    # Expected-results aliases.
    results["rotation"]["controlled"]["category_count"]["effect_per_10"] = rotation["controlled"]["category_count"]["effect_per_10"]
    results["rotation"]["controlled"]["entropy"]["effect_per_10"] = rotation["controlled"]["entropy"]["effect_per_10"]
    results["rotation"]["controlled"]["calendar_switch"]["effect_per_10"] = rotation["controlled"]["calendar_switch"]["effect_per_10"]

    verify_results(results, expected)
    print("RESULT VERIFICATION: PASS")

    # Human-readable outputs.
    pd.DataFrame(
        [{"metric": k, "value": v} for k, v in raw_stats.items()]
    ).to_csv(out_dir / "raw_correlations.csv", index=False)
    pd.DataFrame([quintile]).to_csv(out_dir / "quintile_contrasts.csv", index=False)
    pd.DataFrame(
        [{"endpoint": k, **v} for k, v in controlled.items()]
    ).to_csv(out_dir / "controlled_crop_endpoints.csv", index=False)
    pd.DataFrame(
        [
            {"endpoint": "productive_use_share", **productive_use},
            {"endpoint": "rotation_category_count", **rotation["controlled"]["category_count"]},
            {"endpoint": "rotation_entropy", **rotation["controlled"]["entropy"]},
            {"endpoint": "rotation_calendar_switch", **rotation["controlled"]["calendar_switch"]},
        ]
    ).to_csv(out_dir / "controlled_rotation_and_use_endpoints.csv", index=False)
    (out_dir / "summary.json").write_text(
        json.dumps(jsonable(results), indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print()
    print("=" * 92)
    print("AkerDrift x AkerMinne validation v1.0")
    print("=" * 92)
    print(f"Raw cohort:           {len(raw):,}")
    print(f"Strict/local cohort:  {len(strict):,} / {len(local):,} in {local['_group_id'].nunique():,} groups")
    print(f"Productive >=4 years: {len(work):,}")
    print()
    print(f"Raw Spearman Drift~area:   {raw_stats['spearman_drift_area']:.4f}")
    print(f"Raw Spearman Drift~cereal: {raw_stats['spearman_drift_cereal']:.4f}")
    print(f"Raw Spearman Drift~broad:  {raw_stats['spearman_drift_broad']:.4f}")
    print()
    b = controlled["broad_vs_vall"]
    print(
        f"Controlled broad-vs-vall per +10 Drift: {b['effect_per_10_pp']:+.2f} pp "
        f"(95% CI {b['ci_low_pp']:+.2f} to {b['ci_high_pp']:+.2f}); "
        f"delta R2={b['delta_r2']:.6f}"
    )
    pu = productive_use
    print(
        f"Secondary productive-use per +10 Drift: {pu['effect_per_10_pp']:+.2f} pp "
        f"(95% CI {pu['ci_low_pp']:+.2f} to {pu['ci_high_pp']:+.2f}); "
        f"delta R2={pu['delta_r2']:.4f}"
    )
    print()
    for label, key in [
        ("rotation categories", "category_count"),
        ("rotation entropy", "entropy"),
        ("calendar switch rate", "calendar_switch"),
    ]:
        r = rotation["controlled"][key]
        print(f"{label}: effect/+10={r['effect_per_10']:+.5f}, p={r['p_value']:.3f}")
    print()
    print("RESULT VERIFICATION: PASS")
    print(f"Output: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
