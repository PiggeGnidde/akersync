#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerPuls geometry-persistence prior study (zero Sentinel PU).

Reads the frozen ÅkerMinne v1 municipality summaries, all anchored to the
current 2025 field geometry, and asks:

1) How often is a 2025 field strict 1:1 with each historical year?
2) Are the *same* fields repeatedly stable, beyond an independent-years
   benchmark with the observed year-specific marginal rates?
3) Does 2015-2023 stability stratify the probability that 2024 is strict 1:1
   with 2025, and does split/merge history stratify 2024 split/merge risk?

The 2024 calibration is descriptive rather than a causal out-of-time forecast:
all identity labels are defined relative to the frozen 2025 reference geometry.
No frozen ÅkerMinne artifacts are modified.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "akerpuls_geometry_persistence_study_v0.json"

IDENTITY_ORDER = [
    "direct_id", "one_to_one_strict", "one_to_one_relaxed",
    "split", "merge", "ambiguous", "unmatched",
]


def poisson_binomial_pmf(probabilities: Iterable[float]) -> np.ndarray:
    """PMF of sum of independent Bernoulli variables with unequal p."""
    pmf = np.array([1.0], dtype=float)
    for p in probabilities:
        p = float(p)
        if not 0.0 <= p <= 1.0:
            raise ValueError(f"Probability outside [0,1]: {p}")
        nxt = np.zeros(len(pmf) + 1, dtype=float)
        nxt[:-1] += pmf * (1.0 - p)
        nxt[1:] += pmf * p
        pmf = nxt
    return pmf


def recent_true_streak(matrix: np.ndarray) -> np.ndarray:
    """Consecutive True count from the final column backwards."""
    a = np.asarray(matrix, dtype=bool)
    if a.ndim != 2:
        raise ValueError("matrix must be 2D")
    if a.shape[1] == 0:
        return np.zeros(a.shape[0], dtype=int)
    return np.cumprod(a[:, ::-1].astype(np.int8), axis=1).sum(axis=1).astype(int)


def wilson_interval(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n <= 0:
        return (float("nan"), float("nan"))
    phat = successes / n
    den = 1.0 + z * z / n
    center = (phat + z * z / (2.0 * n)) / den
    half = z * math.sqrt(phat * (1.0 - phat) / n + z * z / (4.0 * n * n)) / den
    return max(0.0, center - half), min(1.0, center + half)


def _read_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _municipality_files(root: Path) -> list[Path]:
    return sorted((root / "municipalities").glob("*/akerminne_year_summary_classified.parquet"))


def load_frozen_history(root: Path, cfg: dict) -> pd.DataFrame:
    files = _municipality_files(root)
    expected_m = int(cfg["expected_municipalities"])
    if len(files) != expected_m:
        raise RuntimeError(f"Expected {expected_m} municipality summaries under {root}, found {len(files)}")

    cols = [
        "municipality", "history_year", "current_field_id", "current_block_id",
        "current_skiftesbeteckning", "current_area_m2", "identity_match_confidence",
        "primary_f_current", "primary_f_historical",
    ]
    parts: list[pd.DataFrame] = []
    for path in files:
        x = pd.read_parquet(path, columns=cols)
        code = path.parent.name.split("_", 1)[0]
        x["municipality_code"] = str(code)
        x["field_uid"] = x["municipality_code"].astype(str) + "|" + x["current_field_id"].astype(str)
        parts.append(x)
    all_rows = pd.concat(parts, ignore_index=True)

    expected_rows = int(cfg["expected_field_years_including_reference"])
    expected_fields = int(cfg["expected_current_fields"])
    if len(all_rows) != expected_rows:
        raise RuntimeError(f"Expected {expected_rows:,} frozen field-years, got {len(all_rows):,}")
    if all_rows["field_uid"].nunique() != expected_fields:
        raise RuntimeError(
            f"Expected {expected_fields:,} unique current fields, got {all_rows['field_uid'].nunique():,}"
        )
    expected_years = set(cfg["history_years"] + [cfg["reference_year"]])
    actual_years = set(map(int, all_rows["history_year"].unique()))
    if actual_years != expected_years:
        raise RuntimeError(f"Year contract mismatch: expected {sorted(expected_years)}, got {sorted(actual_years)}")
    per_field = all_rows.groupby("field_uid")["history_year"].nunique()
    if not (per_field == len(expected_years)).all():
        raise RuntimeError("Every field must have exactly one row for each 2015-2025 year")
    return all_rows


def annual_summary(hist: pd.DataFrame, years: list[int], strict: set[str], practical: set[str], splitmerge: set[str], structural: set[str]) -> pd.DataFrame:
    rows = []
    for y in years:
        x = hist[hist["history_year"] == y]
        ids = x["identity_match_confidence"].astype(str)
        rec = {"history_year": y, "fields": int(len(x))}
        vc = ids.value_counts()
        for name in IDENTITY_ORDER:
            rec[name + "_count"] = int(vc.get(name, 0))
            rec[name + "_rate"] = float(vc.get(name, 0) / len(x)) if len(x) else float("nan")
        rec["strict_same_count"] = int(ids.isin(strict).sum())
        rec["strict_same_rate"] = float(ids.isin(strict).mean())
        rec["practical_same_count"] = int(ids.isin(practical).sum())
        rec["practical_same_rate"] = float(ids.isin(practical).mean())
        rec["split_merge_count"] = int(ids.isin(splitmerge).sum())
        rec["split_merge_rate"] = float(ids.isin(splitmerge).mean())
        rec["structural_or_unresolved_change_count"] = int(ids.isin(structural).sum())
        rec["structural_or_unresolved_change_rate"] = float(ids.isin(structural).mean())
        rows.append(rec)
    return pd.DataFrame(rows)


def _binary_pivot(hist: pd.DataFrame, years: list[int], classes: set[str]) -> pd.DataFrame:
    x = hist[["field_uid", "history_year", "identity_match_confidence"]].copy()
    x["flag"] = x["identity_match_confidence"].astype(str).isin(classes)
    p = x.pivot(index="field_uid", columns="history_year", values="flag")
    return p.reindex(columns=years).astype(bool)


def _identity_pivot(hist: pd.DataFrame, years: list[int]) -> pd.DataFrame:
    p = hist.pivot(index="field_uid", columns="history_year", values="identity_match_confidence")
    return p.reindex(columns=years).astype(str)


def field_summary(hist: pd.DataFrame, years: list[int], strict: set[str], practical: set[str], splitmerge: set[str], structural: set[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    strict_p = _binary_pivot(hist, years, strict)
    practical_p = _binary_pivot(hist, years, practical)
    splitmerge_p = _binary_pivot(hist, years, splitmerge)
    structural_p = _binary_pivot(hist, years, structural)
    identity_p = _identity_pivot(hist, years)

    arr_s = strict_p.to_numpy(dtype=bool)
    arr_p = practical_p.to_numpy(dtype=bool)
    arr_sm = splitmerge_p.to_numpy(dtype=bool)
    arr_ch = structural_p.to_numpy(dtype=bool)

    meta = (
        hist.sort_values(["field_uid", "history_year"], kind="mergesort")
        .drop_duplicates("field_uid")[[
            "field_uid", "municipality_code", "municipality", "current_field_id",
            "current_block_id", "current_skiftesbeteckning", "current_area_m2",
        ]]
        .set_index("field_uid")
        .reindex(strict_p.index)
    )
    out = meta.copy()
    out["strict_same_count_10y"] = arr_s.sum(axis=1)
    out["strict_same_rate_10y"] = out["strict_same_count_10y"] / len(years)
    out["practical_same_count_10y"] = arr_p.sum(axis=1)
    out["practical_same_rate_10y"] = out["practical_same_count_10y"] / len(years)
    out["split_merge_count_10y"] = arr_sm.sum(axis=1)
    out["structural_or_unresolved_change_count_10y"] = arr_ch.sum(axis=1)
    out["strict_recent_streak_to_2024"] = recent_true_streak(arr_s)
    out["practical_recent_streak_to_2024"] = recent_true_streak(arr_p)
    out["strict_status_switches_2015_2024"] = (arr_s[:, 1:] != arr_s[:, :-1]).sum(axis=1)

    for cls in ["direct_id", "one_to_one_strict", "one_to_one_relaxed", "split", "merge", "ambiguous", "unmatched"]:
        out[f"{cls}_count_10y"] = (identity_p.to_numpy() == cls).sum(axis=1)

    pre = years[:-1]
    out["strict_same_count_2015_2023"] = strict_p[pre].sum(axis=1).astype(int)
    out["strict_recent_streak_to_2023"] = recent_true_streak(strict_p[pre].to_numpy(dtype=bool))
    out["split_merge_count_2015_2023"] = splitmerge_p[pre].sum(axis=1).astype(int)
    out["structural_or_unresolved_change_count_2015_2023"] = structural_p[pre].sum(axis=1).astype(int)
    out["strict_same_2024"] = strict_p[2024].astype(bool)
    out["practical_same_2024"] = practical_p[2024].astype(bool)
    out["split_merge_2024"] = splitmerge_p[2024].astype(bool)
    out["structural_or_unresolved_change_2024"] = structural_p[2024].astype(bool)
    out["identity_2024"] = identity_p[2024].astype(str)
    out = out.reset_index()

    # Pairwise binary association between years: Pearson(phi) and Jaccard.
    pair_rows = []
    for i, y1 in enumerate(years):
        a = strict_p[y1].to_numpy(dtype=bool)
        for y2 in years[i + 1:]:
            b = strict_p[y2].to_numpy(dtype=bool)
            if a.std() == 0 or b.std() == 0:
                phi = float("nan")
            else:
                phi = float(np.corrcoef(a.astype(float), b.astype(float))[0, 1])
            union = int(np.logical_or(a, b).sum())
            inter = int(np.logical_and(a, b).sum())
            pair_rows.append({
                "year_1": y1, "year_2": y2, "gap_years": y2 - y1,
                "phi_strict_same": phi,
                "jaccard_strict_same": (inter / union if union else float("nan")),
                "both_strict_count": inter,
            })
    pairs = pd.DataFrame(pair_rows)

    # Adjacent-year conditional persistence, still with 2025-reference labels.
    adj_rows = []
    for y1, y2 in zip(years[:-1], years[1:]):
        a = strict_p[y1].to_numpy(dtype=bool)
        b = strict_p[y2].to_numpy(dtype=bool)
        n1 = int(a.sum()); n0 = int((~a).sum())
        p1 = float(b[a].mean()) if n1 else float("nan")
        p0 = float(b[~a].mean()) if n0 else float("nan")
        adj_rows.append({
            "year_1": y1, "year_2": y2,
            "p_strict_y2_given_strict_y1": p1,
            "p_strict_y2_given_not_strict_y1": p0,
            "risk_difference": p1 - p0,
            "n_strict_y1": n1, "n_not_strict_y1": n0,
        })
    adjacent = pd.DataFrame(adj_rows)
    return out, strict_p, pairs, adjacent


def calibration_by_integer(field: pd.DataFrame, feature: str) -> pd.DataFrame:
    rows = []
    for value, x in field.groupby(feature, sort=True):
        n = len(x)
        s = int(x["strict_same_2024"].sum())
        sm = int(x["split_merge_2024"].sum())
        ch = int(x["structural_or_unresolved_change_2024"].sum())
        lo, hi = wilson_interval(s, n)
        rows.append({
            feature: int(value), "fields": int(n),
            "strict_same_2024_count": s, "strict_same_2024_rate": s / n,
            "strict_same_2024_wilson95_lo": lo, "strict_same_2024_wilson95_hi": hi,
            "split_merge_2024_count": sm, "split_merge_2024_rate": sm / n,
            "structural_or_unresolved_change_2024_count": ch,
            "structural_or_unresolved_change_2024_rate": ch / n,
        })
    return pd.DataFrame(rows)


def _rate_for(df: pd.DataFrame, mask: pd.Series, col: str) -> tuple[int, float]:
    x = df.loc[mask, col]
    return int(len(x)), (float(x.mean()) if len(x) else float("nan"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--akerminne-root")
    ap.add_argument("--output-dir")
    args = ap.parse_args()

    cfg = _read_config(Path(args.config))
    root = Path(args.akerminne_root or cfg["akerminne_root"])
    out_dir = Path(args.output_dir or cfg["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    strict = set(cfg["identity_classes"]["strict_same"])
    practical = set(cfg["identity_classes"]["practical_same"])
    splitmerge = set(cfg["identity_classes"]["split_merge"])
    structural = set(cfg["identity_classes"]["structural_or_unresolved_change"])
    years = list(map(int, cfg["history_years"]))

    all_rows = load_frozen_history(root, cfg)
    hist = all_rows[all_rows["history_year"].isin(years)].copy()
    ann = annual_summary(hist, years, strict, practical, splitmerge, structural)
    fields, strict_p, pairs, adjacent = field_summary(hist, years, strict, practical, splitmerge, structural)

    # Observed per-field count distribution versus independence with year-specific marginals.
    p_year = ann.set_index("history_year").loc[years, "strict_same_rate"].to_numpy(dtype=float)
    indep_pmf = poisson_binomial_pmf(p_year)
    n_fields = len(fields)
    vc = fields["strict_same_count_10y"].value_counts().to_dict()
    dist_rows = []
    for k in range(len(years) + 1):
        actual = int(vc.get(k, 0))
        exp_share = float(indep_pmf[k])
        dist_rows.append({
            "strict_same_years": k,
            "observed_count": actual,
            "observed_share": actual / n_fields,
            "independent_expected_count": n_fields * exp_share,
            "independent_expected_share": exp_share,
            "observed_to_independent_ratio": (actual / (n_fields * exp_share) if exp_share > 0 else float("nan")),
        })
    dist = pd.DataFrame(dist_rows)

    count_cal = calibration_by_integer(fields, "strict_same_count_2015_2023")
    streak_cal = calibration_by_integer(fields, "strict_recent_streak_to_2023")
    splitmerge_cal = calibration_by_integer(fields, "split_merge_count_2015_2023")

    # Municipality-specific 2024->2025 baseline.
    muni_rows = []
    for (code, name), x in fields.groupby(["municipality_code", "municipality"], sort=True):
        muni_rows.append({
            "municipality_code": code, "municipality": name, "fields": len(x),
            "strict_same_2024_rate": float(x["strict_same_2024"].mean()),
            "practical_same_2024_rate": float(x["practical_same_2024"].mean()),
            "split_merge_2024_rate": float(x["split_merge_2024"].mean()),
            "structural_or_unresolved_change_2024_rate": float(x["structural_or_unresolved_change_2024"].mean()),
        })
    muni = pd.DataFrame(muni_rows)

    # Headline concentration metrics.
    observed_all10 = float((fields["strict_same_count_10y"] == 10).mean())
    expected_all10 = float(indep_pmf[10])
    observed_9plus = float((fields["strict_same_count_10y"] >= 9).mean())
    expected_9plus = float(indep_pmf[9:].sum())
    observed_5less = float((fields["strict_same_count_10y"] <= 5).mean())
    expected_5less = float(indep_pmf[:6].sum())
    actual_var = float(fields["strict_same_count_10y"].var(ddof=0))
    independent_var = float(np.sum(p_year * (1.0 - p_year)))
    overdispersion = actual_var / independent_var if independent_var > 0 else float("nan")

    n_9of9, p_9of9 = _rate_for(fields, fields["strict_same_count_2015_2023"] == 9, "strict_same_2024")
    n_le5, p_le5 = _rate_for(fields, fields["strict_same_count_2015_2023"] <= 5, "strict_same_2024")
    n_sm_any, p_sm_any = _rate_for(fields, fields["split_merge_count_2015_2023"] > 0, "split_merge_2024")
    n_sm_none, p_sm_none = _rate_for(fields, fields["split_merge_count_2015_2023"] == 0, "split_merge_2024")

    strict_2024 = float(ann.loc[ann.history_year == 2024, "strict_same_rate"].iloc[0])
    practical_2024 = float(ann.loc[ann.history_year == 2024, "practical_same_rate"].iloc[0])
    splitmerge_2024 = float(ann.loc[ann.history_year == 2024, "split_merge_rate"].iloc[0])
    adjacent_phi = pairs[pairs["gap_years"] == 1]["phi_strict_same"].dropna()

    summary = {
        "schema_version": cfg["schema_version"],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source_contract": "AKERMINNE_V1_FROZEN_2025_REFERENCE",
        "akerminne_root": str(root),
        "current_fields": int(n_fields),
        "history_years": years,
        "strict_same_2024_rate": strict_2024,
        "practical_same_2024_rate": practical_2024,
        "split_merge_2024_rate": splitmerge_2024,
        "concentration": {
            "observed_all10_strict_share": observed_all10,
            "independent_expected_all10_strict_share": expected_all10,
            "all10_observed_to_independent_ratio": observed_all10 / expected_all10 if expected_all10 else None,
            "observed_9plus_strict_share": observed_9plus,
            "independent_expected_9plus_strict_share": expected_9plus,
            "nineplus_observed_to_independent_ratio": observed_9plus / expected_9plus if expected_9plus else None,
            "observed_5orless_strict_share": observed_5less,
            "independent_expected_5orless_strict_share": expected_5less,
            "fiveorless_observed_to_independent_ratio": observed_5less / expected_5less if expected_5less else None,
            "strict_count_variance_observed": actual_var,
            "strict_count_variance_independent": independent_var,
            "overdispersion_factor": overdispersion,
            "median_adjacent_year_phi": float(adjacent_phi.median()) if len(adjacent_phi) else None,
        },
        "latest_year_descriptive_calibration": {
            "p_strict_2024_given_strict_2015_2023_all9": p_9of9,
            "n_strict_2015_2023_all9": n_9of9,
            "p_strict_2024_given_strict_count_2015_2023_le5": p_le5,
            "n_strict_count_2015_2023_le5": n_le5,
            "p_splitmerge_2024_given_prior_splitmerge_any": p_sm_any,
            "n_prior_splitmerge_any": n_sm_any,
            "p_splitmerge_2024_given_no_prior_splitmerge": p_sm_none,
            "n_no_prior_splitmerge": n_sm_none,
            "interpretation": cfg["latest_year_pseudo_backtest"]["interpretation"],
        },
        "guards": cfg["guards"],
    }

    ann.to_csv(out_dir / "annual_identity_summary.csv", index=False)
    fields.to_parquet(out_dir / "field_geometry_persistence.parquet", index=False)
    fields.to_csv(out_dir / "field_geometry_persistence.csv", index=False, encoding="utf-8-sig")
    dist.to_csv(out_dir / "strict_count_observed_vs_independent.csv", index=False)
    count_cal.to_csv(out_dir / "latest_year_calibration_by_prior_strict_count.csv", index=False)
    streak_cal.to_csv(out_dir / "latest_year_calibration_by_prior_recent_streak.csv", index=False)
    splitmerge_cal.to_csv(out_dir / "latest_year_calibration_by_prior_splitmerge_count.csv", index=False)
    pairs.to_csv(out_dir / "strict_same_year_pair_association.csv", index=False)
    adjacent.to_csv(out_dir / "adjacent_year_strict_persistence.csv", index=False)
    muni.to_csv(out_dir / "municipality_2024_2025_geometry_baseline.csv", index=False, encoding="utf-8-sig")
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("AKERPULS GEOMETRY PERSISTENCE PRIOR STUDY")
    print(f"FIELDS={n_fields} HISTORY_ROWS={len(hist)} MUNICIPALITIES={hist['municipality_code'].nunique()}")
    print(f"STRICT_SAME_2024_2025={strict_2024:.4f}")
    print(f"PRACTICAL_SAME_2024_2025={practical_2024:.4f}")
    print(f"SPLIT_MERGE_2024_2025={splitmerge_2024:.4f}")
    print(f"ALL10_STRICT OBS={observed_all10:.4f} INDEP={expected_all10:.4f} RATIO={(observed_all10/expected_all10 if expected_all10 else float('nan')):.3f}")
    print(f"NINEPLUS_STRICT OBS={observed_9plus:.4f} INDEP={expected_9plus:.4f} RATIO={(observed_9plus/expected_9plus if expected_9plus else float('nan')):.3f}")
    print(f"FIVEORLESS_STRICT OBS={observed_5less:.4f} INDEP={expected_5less:.4f} RATIO={(observed_5less/expected_5less if expected_5less else float('nan')):.3f}")
    print(f"STRICT_COUNT_OVERDISPERSION={overdispersion:.3f}")
    print(f"MEDIAN_ADJACENT_YEAR_PHI={(float(adjacent_phi.median()) if len(adjacent_phi) else float('nan')):.3f}")
    print(f"P_STRICT_2024_GIVEN_9OF9_PRIOR={p_9of9:.4f} N={n_9of9}")
    print(f"P_STRICT_2024_GIVEN_LE5OF9_PRIOR={p_le5:.4f} N={n_le5}")
    print(f"P_SPLITMERGE_2024_GIVEN_PRIOR_SPLITMERGE={p_sm_any:.4f} N={n_sm_any}")
    print(f"P_SPLITMERGE_2024_GIVEN_NO_PRIOR_SPLITMERGE={p_sm_none:.4f} N={n_sm_none}")
    print("SOURCE_CONTRACT=AKERMINNE_V1_FROZEN_2025_REFERENCE")
    print("FROZEN_AKERMINNE_MODIFIED=FALSE")
    print("PRODUCT_PRIOR_FROZEN=FALSE")
    print("SENTINEL_HUB_PU_USED=0")
    print("PERSISTENCE_STUDY_STATUS=PASS")
    print(f"OUTPUT={out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
