#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reproduce ÅkerScore × ÅkerMinne external behavioural validation v1.0.

This analysis tests whether ÅkerScore contains information beyond the historic
agricultural class under a revealed-preference / rational-land-use hypothesis.

Frozen primary design:
- Historic agricultural classes 5-10 only.
- Valid ÅkerScore Soil P50.
- Historic class coverage_unique >= 0.95.
- Dominant historic class share >= 0.95.
- mixed_soil_class == False.
- At least 8 of 11 ÅkerMinne years have status SINGLE_CROP.
- Crop-use shares use SINGLE_CROP years only.
- Local quintiles are formed inside historic class × SKO × municipality groups
  with at least 25 strict-cohort fields.
- Quintiles use rank(method="first") followed by qcut(5), freezing tie handling.
- Block fixed effects compare fields within current block × historic class and
  control for log(field area).
- Cluster bootstrap resamples local class × SKO × municipality groups with
  replacement; seed=20260830, B=5000.

The script is read-only with respect to project source/derived data. Results
are written under the chosen output directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from crop_groups import classify_crop_names


VERSION = "akerscore-akerminne-validation-v1.0"
BOOTSTRAP_SEED = 20260830
BOOTSTRAP_REPLICATES = 5000

EXPECTED_FILENAMES = {
    "context": "field_static_context_selected.csv.gz",
    "history": "akerminne_2015_2025_selected.csv.gz",
    "score": "akerscore_soil_skiften_selected.csv.gz",
}


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def jsonable(value):
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [jsonable(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if pd.isna(value):
        return None
    return value


def verify_input_hashes(input_dir: Path, manifest_path: Path) -> list[str]:
    manifest = read_json(manifest_path)
    errors = []
    for filename, meta in manifest["files"].items():
        path = input_dir / filename
        if not path.exists():
            errors.append(f"missing input: {path}")
            continue
        digest = sha256_file(path)
        if digest.lower() != str(meta["sha256"]).lower():
            errors.append(
                f"SHA256 mismatch for {filename}: expected {meta['sha256']}, got {digest}"
            )
    return errors


def add_crop_flags(history: pd.DataFrame) -> pd.DataFrame:
    out = history.copy()
    flags = classify_crop_names(out["dominant_crop_name"])
    for col in flags.columns:
        out[col] = flags[col].to_numpy()
    return out


def build_field_history_metrics(history: pd.DataFrame) -> pd.DataFrame:
    good = history[history["status"].eq("SINGLE_CROP")].copy()
    metrics = (
        good.groupby("current_field_id", sort=False)
        .agg(
            good_years=("history_year", "size"),
            cereal_share=("is_cereal", "mean"),
            vall_share=("is_vall", "mean"),
            broad_share=("is_broad_production", "mean"),
            cereal_n=("is_cereal", "sum"),
            vall_n=("is_vall", "sum"),
        )
    )
    denom = metrics["cereal_n"] + metrics["vall_n"]
    metrics["cereal_vs_vall_ratio"] = np.where(
        denom > 0, metrics["cereal_n"] / denom, np.nan
    )
    return metrics


def strict_cohort(
    context: pd.DataFrame,
    score: pd.DataFrame,
    field_history: pd.DataFrame,
) -> pd.DataFrame:
    score_keep = score[
        ["current_field_id", "akerscore_soil_p50", "area_ha"]
    ].copy()

    base = (
        context.merge(score_keep, on="current_field_id", how="left", validate="one_to_one")
        .merge(
            field_history[["good_years"]],
            left_on="current_field_id",
            right_index=True,
            how="left",
            validate="one_to_one",
        )
    )

    mask = (
        base["dominant_soil_class"].between(5, 10)
        & base["akerscore_soil_p50"].notna()
        & (base["soil_class_coverage_unique"] >= 0.95)
        & (base["dominant_soil_class_share"] >= 0.95)
        & (~base["mixed_soil_class"].fillna(False))
        & (base["good_years"] >= 8)
    )

    out = base.loc[mask].copy()
    out = out.merge(
        field_history.drop(columns=["good_years"]),
        left_on="current_field_id",
        right_index=True,
        how="left",
        validate="one_to_one",
    )
    return out


def make_quintiles(values: pd.Series) -> pd.Series:
    ranked = values.rank(method="first")
    return pd.qcut(ranked, 5, labels=[1, 2, 3, 4, 5]).astype(int)


def local_quintile_analysis(strict: pd.DataFrame):
    keys = ["dominant_soil_class", "dominant_sko_id", "municipality"]
    group_size = strict.groupby(keys, dropna=False).size()
    eligible = group_size[group_size >= 25].index

    local = strict.copy()
    local["_local_group"] = list(
        zip(
            local["dominant_soil_class"],
            local["dominant_sko_id"],
            local["municipality"],
        )
    )
    eligible_set = set(eligible)
    local = local[local["_local_group"].isin(eligible_set)].copy()
    local["local_score_quintile"] = (
        local.groupby(keys, dropna=False)["akerscore_soil_p50"]
        .transform(make_quintiles)
        .astype(int)
    )

    table = (
        local.groupby("local_score_quintile")
        .agg(
            n=("current_field_id", "size"),
            mean_score=("akerscore_soil_p50", "mean"),
            cereal_share=("cereal_share", "mean"),
            vall_share=("vall_share", "mean"),
            broad_share=("broad_share", "mean"),
            cereal_vs_vall=("cereal_vs_vall_ratio", "mean"),
        )
        .reset_index()
        .rename(columns={"local_score_quintile": "q"})
    )
    return local, table, len(eligible_set)


def class_quintile_analysis(strict: pd.DataFrame) -> pd.DataFrame:
    work = strict.copy()
    work["class_score_quintile"] = (
        work.groupby("dominant_soil_class")["akerscore_soil_p50"]
        .transform(make_quintiles)
        .astype(int)
    )

    rows = []
    for klass, g in work.groupby("dominant_soil_class", sort=True):
        q1 = g[g["class_score_quintile"].eq(1)]
        q5 = g[g["class_score_quintile"].eq(5)]
        rows.append(
            {
                "historic_class": int(klass),
                "n": int(len(g)),
                "q1_mean_score": float(q1["akerscore_soil_p50"].mean()),
                "q5_mean_score": float(q5["akerscore_soil_p50"].mean()),
                "q1_cereal_share": float(q1["cereal_share"].mean()),
                "q5_cereal_share": float(q5["cereal_share"].mean()),
                "q1_vall_share": float(q1["vall_share"].mean()),
                "q5_vall_share": float(q5["vall_share"].mean()),
            }
        )
    return pd.DataFrame(rows)


def cluster_bootstrap(local: pd.DataFrame) -> dict:
    rows = []
    for gid, g in local.groupby("_local_group", sort=True):
        rec = {}
        for q in (1, 5):
            s = g.loc[g["local_score_quintile"].eq(q), "cereal_share"]
            rec[f"sum{q}"] = float(s.sum())
            rec[f"n{q}"] = int(len(s))
        rows.append(rec)

    arr = pd.DataFrame(rows)[["sum1", "n1", "sum5", "n5"]].to_numpy(float)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    values = np.empty(BOOTSTRAP_REPLICATES, dtype=float)

    for i in range(BOOTSTRAP_REPLICATES):
        idx = rng.integers(0, len(arr), len(arr))
        s = arr[idx].sum(axis=0)
        values[i] = s[2] / s[3] - s[0] / s[1]

    observed = (
        local.loc[local["local_score_quintile"].eq(5), "cereal_share"].mean()
        - local.loc[local["local_score_quintile"].eq(1), "cereal_share"].mean()
    )
    q025, q975 = np.quantile(values, [0.025, 0.975])
    return {
        "seed": BOOTSTRAP_SEED,
        "replicates": BOOTSTRAP_REPLICATES,
        "observed_q5_minus_q1": float(observed),
        "ci_2_5_pct": float(q025),
        "ci_97_5_pct": float(q975),
    }


def year_by_year(history: pd.DataFrame, local: pd.DataFrame) -> pd.DataFrame:
    h = history.merge(
        local[["current_field_id", "local_score_quintile"]],
        on="current_field_id",
        how="inner",
        validate="many_to_one",
    )
    h = h[
        h["status"].eq("SINGLE_CROP")
        & (h["is_cereal"] | h["is_vall"])
    ].copy()

    rows = []
    for year, g in h.groupby("history_year", sort=True):
        p = g.groupby("local_score_quintile")["is_cereal"].mean()
        rows.append(
            {
                "year": int(year),
                "q1_cereal_of_cereal_plus_vall": float(p.loc[1]),
                "q5_cereal_of_cereal_plus_vall": float(p.loc[5]),
                "q5_minus_q1": float(p.loc[5] - p.loc[1]),
            }
        )
    return pd.DataFrame(rows)


def fixed_effect_regression(strict: pd.DataFrame):
    keys = ["current_block_id", "dominant_soil_class"]
    stats = strict.groupby(keys).agg(
        n=("current_field_id", "size"),
        score_range=(
            "akerscore_soil_p50",
            lambda s: float(s.max() - s.min()),
        ),
    )
    eligible = stats[
        (stats["n"] >= 2) & (stats["score_range"] > 1e-9)
    ].index

    work = strict.copy()
    work["_block_group"] = list(
        zip(work["current_block_id"], work["dominant_soil_class"])
    )
    eligible_set = set(eligible)
    work = work[work["_block_group"].isin(eligible_set)].copy()
    work["log_area"] = np.log(work["area_ha"].clip(lower=1e-9))

    columns = [
        "akerscore_soil_p50",
        "log_area",
        "cereal_share",
        "vall_share",
        "broad_share",
    ]
    for col in columns:
        work[col + "_dm"] = (
            work[col] - work.groupby("_block_group")[col].transform("mean")
        )

    X = np.column_stack(
        [
            work["akerscore_soil_p50_dm"].to_numpy(float),
            work["log_area_dm"].to_numpy(float),
        ]
    )

    coefficient_rows = []
    for endpoint in ("cereal_share", "vall_share", "broad_share"):
        beta = np.linalg.lstsq(
            X, work[endpoint + "_dm"].to_numpy(float), rcond=None
        )[0]
        coefficient_rows.append(
            {
                "endpoint": endpoint,
                "score_coef_per_point": float(beta[0]),
                "score_effect_per_10": float(beta[0] * 10.0),
                "log_area_coef": float(beta[1]),
            }
        )

    pair_rows = []
    for gid, g in work.groupby("_block_group", sort=False):
        score_range = (
            g["akerscore_soil_p50"].max()
            - g["akerscore_soil_p50"].min()
        )
        if score_range < 20.0:
            continue
        high = g.loc[g["akerscore_soil_p50"].idxmax()]
        low = g.loc[g["akerscore_soil_p50"].idxmin()]
        pair_rows.append(
            {
                "current_block_id": gid[0],
                "historic_class": int(gid[1]),
                "high_field_id": high["current_field_id"],
                "low_field_id": low["current_field_id"],
                "score_diff": float(
                    high["akerscore_soil_p50"]
                    - low["akerscore_soil_p50"]
                ),
                "cereal_diff": float(
                    high["cereal_share"] - low["cereal_share"]
                ),
                "vall_diff": float(
                    high["vall_share"] - low["vall_share"]
                ),
                "broad_diff": float(
                    high["broad_share"] - low["broad_share"]
                ),
            }
        )

    return (
        work,
        pd.DataFrame(coefficient_rows),
        pd.DataFrame(pair_rows),
        len(eligible_set),
    )


def low_class_extremes(strict: pd.DataFrame) -> dict:
    work = strict[strict["dominant_soil_class"].isin([5, 6])].copy()
    high = work[work["akerscore_soil_p50"] >= 85.0]
    low = work[work["akerscore_soil_p50"] <= 50.0]
    return {
        "high_score_ge_85": {
            "n": int(len(high)),
            "cereal_share": float(high["cereal_share"].mean()),
            "vall_share": float(high["vall_share"].mean()),
            "broad_share": float(high["broad_share"].mean()),
        },
        "low_score_le_50": {
            "n": int(len(low)),
            "cereal_share": float(low["cereal_share"].mean()),
            "vall_share": float(low["vall_share"].mean()),
            "broad_share": float(low["broad_share"].mean()),
        },
    }


def compare_number(actual: float, expected: float, tolerance: float) -> bool:
    return math.isclose(
        float(actual), float(expected), rel_tol=0.0, abs_tol=tolerance
    )


def verification_checks(results: dict, expected: dict):
    checks = []

    def exact(label, actual, exp):
        checks.append(
            {
                "label": label,
                "actual": actual,
                "expected": exp,
                "pass": actual == exp,
            }
        )

    def numeric(label, actual, exp, tol=1e-8):
        checks.append(
            {
                "label": label,
                "actual": float(actual),
                "expected": float(exp),
                "tolerance": tol,
                "pass": compare_number(actual, exp, tol),
            }
        )

    exact(
        "strict_fields",
        results["inventory"]["strict_fields"],
        expected["inventory"]["strict_fields"],
    )
    exact(
        "local_quintile_fields",
        results["inventory"]["local_quintile_fields"],
        expected["inventory"]["local_quintile_fields"],
    )
    exact(
        "local_groups",
        results["inventory"]["local_groups"],
        expected["inventory"]["local_groups"],
    )
    exact(
        "block_groups",
        results["block"]["groups"],
        expected["block"]["groups"],
    )
    exact(
        "block_fields",
        results["block"]["fields"],
        expected["block"]["fields"],
    )
    exact(
        "block_pairs_ge20",
        results["block"]["pairs_ge20"],
        expected["block"]["pairs_ge20"],
    )

    actual_q = {int(r["q"]): r for r in results["local_quintiles"]}
    expected_q = {int(r["q"]): r for r in expected["local_quintiles"]}
    for q in range(1, 6):
        exact(f"Q{q}_n", actual_q[q]["n"], expected_q[q]["n"])
        for metric in (
            "mean_score",
            "cereal_share",
            "vall_share",
            "cereal_vs_vall",
        ):
            numeric(
                f"Q{q}_{metric}",
                actual_q[q][metric],
                expected_q[q][metric],
                1e-8,
            )

    numeric(
        "bootstrap_observed",
        results["bootstrap"]["observed_q5_minus_q1"],
        expected["bootstrap"]["observed_q5_minus_q1"],
        1e-8,
    )
    numeric(
        "bootstrap_ci_low",
        results["bootstrap"]["ci_2_5_pct"],
        expected["bootstrap"]["ci_2_5_pct"],
        1e-8,
    )
    numeric(
        "bootstrap_ci_high",
        results["bootstrap"]["ci_97_5_pct"],
        expected["bootstrap"]["ci_97_5_pct"],
        1e-8,
    )

    return checks


def main() -> int:
    ap = argparse.ArgumentParser()
    here = Path(__file__).resolve().parent
    default_repo = here.parents[1]
    ap.add_argument(
        "--input-dir",
        default=str(default_repo / "work" / "akerscore_validation_csv_upload"),
    )
    ap.add_argument(
        "--output-dir",
        default=str(default_repo / "work" / "akerscore_akerminne_validation_v1"),
    )
    ap.add_argument(
        "--input-manifest",
        default=str(here / "manifests" / "input_manifest.json"),
    )
    ap.add_argument(
        "--expected-results",
        default=str(here / "expected_results.json"),
    )
    args = ap.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    manifest_path = Path(args.input_manifest)
    expected_path = Path(args.expected_results)

    print("=" * 84)
    print("ÅkerScore × ÅkerMinne behavioural validation v1.0")
    print("=" * 84)
    print(f"Input:  {input_dir}")
    print(f"Output: {output_dir}")

    errors = verify_input_hashes(input_dir, manifest_path)
    if errors:
        print("\nINPUT VERIFICATION: FAIL")
        for e in errors:
            print(" -", e)
        return 1
    print("\nINPUT VERIFICATION: PASS")

    context = pd.read_csv(
        input_dir / EXPECTED_FILENAMES["context"], compression="gzip", low_memory=False
    )
    history = pd.read_csv(
        input_dir / EXPECTED_FILENAMES["history"], compression="gzip", low_memory=False
    )
    score = pd.read_csv(
        input_dir / EXPECTED_FILENAMES["score"], compression="gzip", low_memory=False
    )

    print(
        f"Loaded context={len(context):,}, history={len(history):,}, score={len(score):,}"
    )

    history = add_crop_flags(history)
    field_history = build_field_history_metrics(history)
    strict = strict_cohort(context, score, field_history)

    local, local_table, local_group_count = local_quintile_analysis(strict)
    class_table = class_quintile_analysis(strict)
    bootstrap = cluster_bootstrap(local)
    year_table = year_by_year(history, local)
    block_fields, fe_table, pair_table, block_group_count = fixed_effect_regression(strict)
    low56 = low_class_extremes(strict)

    pair_means = {
        "score_diff": float(pair_table["score_diff"].mean()),
        "cereal_diff": float(pair_table["cereal_diff"].mean()),
        "vall_diff": float(pair_table["vall_diff"].mean()),
        "broad_diff": float(pair_table["broad_diff"].mean()),
    }

    results = {
        "analysis_version": VERSION,
        "inventory": {
            "context_rows": int(len(context)),
            "history_rows": int(len(history)),
            "score_rows": int(len(score)),
            "strict_fields": int(len(strict)),
            "local_quintile_fields": int(len(local)),
            "local_groups": int(local_group_count),
        },
        "local_quintiles": local_table.to_dict(orient="records"),
        "class_q1_q5": class_table.to_dict(orient="records"),
        "bootstrap": bootstrap,
        "year_by_year": year_table.to_dict(orient="records"),
        "block": {
            "groups": int(block_group_count),
            "fields": int(len(block_fields)),
            "fixed_effect_coefficients": fe_table.to_dict(orient="records"),
            "pairs_ge20": int(len(pair_table)),
            "pair_mean_differences": pair_means,
        },
        "low_class_5_6_extremes": low56,
        "method": {
            "strict_class_min": 5,
            "strict_class_max": 10,
            "class_coverage_unique_min": 0.95,
            "dominant_class_share_min": 0.95,
            "mixed_soil_class_allowed": False,
            "minimum_single_crop_years": 8,
            "local_group_dimensions": [
                "dominant_soil_class",
                "dominant_sko_id",
                "municipality",
            ],
            "local_group_min_fields": 25,
            "quintile_tie_method": "rank(method='first') then qcut(5)",
            "block_fixed_effect_group": [
                "current_block_id",
                "dominant_soil_class",
            ],
            "block_area_control": "log(area_ha), demeaned within block/class",
            "pair_min_score_difference": 20.0,
            "history_denominator": "SINGLE_CROP years only",
        },
    }
    results = jsonable(results)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    local_table.to_csv(output_dir / "local_quintiles.csv", index=False, encoding="utf-8-sig")
    class_table.to_csv(output_dir / "class_q1_q5.csv", index=False, encoding="utf-8-sig")
    year_table.to_csv(output_dir / "year_by_year.csv", index=False, encoding="utf-8-sig")
    fe_table.to_csv(output_dir / "block_fixed_effects.csv", index=False, encoding="utf-8-sig")
    pair_table.to_csv(output_dir / "block_pairs_ge20.csv", index=False, encoding="utf-8-sig")

    expected = read_json(expected_path)
    checks = verification_checks(results, expected)
    verification = {
        "analysis_version": VERSION,
        "all_pass": bool(all(c["pass"] for c in checks)),
        "checks": checks,
    }
    (output_dir / "verification.json").write_text(
        json.dumps(verification, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("\nCORE RESULTS")
    print(f"  Strict fields:          {len(strict):,}")
    print(f"  Local quintile fields:  {len(local):,}")
    print(f"  Local groups:           {local_group_count:,}")
    print(
        "  Q5-Q1 cereal share:    "
        f"{100*bootstrap['observed_q5_minus_q1']:.2f} percentage points"
    )
    print(
        "  Bootstrap 95% CI:      "
        f"{100*bootstrap['ci_2_5_pct']:.2f} to "
        f"{100*bootstrap['ci_97_5_pct']:.2f} pp"
    )
    print(f"  Block/class groups:     {block_group_count:,}")
    print(f"  Block/class fields:     {len(block_fields):,}")
    print(f"  >=20-score pairs:       {len(pair_table):,}")

    print("\nVERIFICATION")
    failed = [c for c in checks if not c["pass"]]
    if failed:
        print("RESULT VERIFICATION: FAIL")
        for c in failed:
            print(
                f" - {c['label']}: actual={c['actual']} expected={c['expected']}"
            )
        return 1

    print("RESULT VERIFICATION: PASS")
    print(f"\nResults written to:\n{output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
