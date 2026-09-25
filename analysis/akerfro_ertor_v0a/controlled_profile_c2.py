#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerFrö – Ärter MVP v0a · C2 geography/area-controlled fingerprint.

C2 starts from the C1 field-feature matrix and asks which raw positive-vs-
unlabeled differences remain after within-stratum centering:

  RAW -> within dominant SKO -> within municipality x SKO
      -> within municipality x SKO x field-area decile.

This is descriptive positive-unlabeled analysis. It is not a causal estimate,
not a binary classifier and not a frozen agronomic suitability rule.
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

from analysis.akerfro_ertor_v0a.build_positive_profile_c1 import (  # noqa: E402
    choose_source,
    field_key,
    rank_auc,
    read_table,
    text_id,
)

DEFAULT_MATRIX = ROOT / "work" / "akerfro_ertor_v0a" / "positive_profile_c1" / "field_feature_matrix.parquet"
DEFAULT_C1 = ROOT / "work" / "akerfro_ertor_v0a" / "positive_profile_c1" / "raw_positive_profile.csv"
DEFAULT_OUT = ROOT / "work" / "akerfro_ertor_v0a" / "controlled_profile_c2"

PRIMARY_FEATURES = [
    ("Field area", "geometry__area_ha"),
    ("Effective row length", "geometry__erl_proxy_m"),
    ("ÅkerDrift", "akerdrift__akerdrift_score"),
    ("ÅkerScore P50", "akerscore__akerscore_soil_p50"),
    ("ÅkerScore within-field spread", "akerscore__akerscore_soil_spread_p90_p10"),
    ("Historic soil class", "static__dominant_soil_class"),
    ("Clay mean", "soil__clay_mean"),
    ("Sand mean", "soil__sand_mean"),
    ("Silt mean", "soil__silt_mean"),
    ("Slope P90", "topography__slope_p90_deg"),
    ("Relief P95-P05", "topography__relief_p95_p05_m"),
    ("TWI mean", "hydrology__twi_mean"),
    ("Rectangularity", "geometry__rectangularity"),
    ("Compactness", "geometry__compactness_4piA_P2"),
    ("Organic >=20% share", "soil__organic_ge20_share_pct"),
]

QA_OR_SELECTION_BIASED = {
    "static__unclassified_soil_share",
    "static__dominant_soil_class_share",
    "static__soil_class_count",
    "static__mixed_soil_class",
    "static__crosses_sko_boundary",
    "static__dominant_sko_share",
    "static__sko_count",
}


def pooled_smd(pos: np.ndarray, unl: np.ndarray) -> float | None:
    pos = pos[np.isfinite(pos)]
    unl = unl[np.isfinite(unl)]
    if len(pos) < 2 or len(unl) < 2:
        return None
    sp = float(np.std(pos, ddof=1))
    su = float(np.std(unl, ddof=1))
    denom = math.sqrt((sp * sp + su * su) / 2.0)
    if denom <= 0 or not np.isfinite(denom):
        return None
    return float((np.mean(pos) - np.mean(unl)) / denom)


def common_support_mask(frame: pd.DataFrame, strata: pd.Series) -> pd.Series:
    tmp = pd.DataFrame({
        "_stratum": strata.astype("string"),
        "_positive": frame["is_positive"].astype(bool),
    }, index=frame.index)
    tmp = tmp[tmp["_stratum"].notna()]
    agg = tmp.groupby("_stratum")["_positive"].agg(["sum", "count"])
    keep = set(agg[(agg["sum"] > 0) & (agg["sum"] < agg["count"])].index.astype(str))
    return strata.astype("string").isin(keep)


def stage_stats(
    frame: pd.DataFrame,
    col: str,
    strata: pd.Series | None,
) -> dict[str, Any]:
    x = pd.to_numeric(frame[col], errors="coerce")
    valid = x.notna()
    if strata is not None:
        valid &= strata.notna()
        support = common_support_mask(frame.loc[valid], strata.loc[valid])
        idx = frame.loc[valid].index[support.to_numpy()]
    else:
        idx = frame.index[valid]

    if len(idx) == 0:
        return {
            "n": 0, "n_positive": 0, "n_unlabeled": 0, "n_strata": 0,
            "smd": None, "rank_auc": None,
        }

    sub = frame.loc[idx]
    vals = x.loc[idx].astype(float)
    if strata is None:
        residual = vals - float(vals.mean())
        n_strata = 1
    else:
        s = strata.loc[idx].astype(str)
        residual = vals - vals.groupby(s).transform("mean")
        n_strata = int(s.nunique())

    pos = residual[sub["is_positive"].to_numpy(bool)].to_numpy(float)
    unl = residual[~sub["is_positive"].to_numpy(bool)].to_numpy(float)
    return {
        "n": int(len(sub)),
        "n_positive": int(len(pos)),
        "n_unlabeled": int(len(unl)),
        "n_strata": n_strata,
        "smd": pooled_smd(pos, unl),
        "rank_auc": rank_auc(pos, unl),
    }


def attach_sko(frame: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    field_ids = set(frame["current_field_id"].map(text_id))
    block_ids = set(frame["current_block_id"].map(text_id))
    static_path, _ = choose_source("static", field_ids, block_ids)
    if static_path is None:
        raise RuntimeError("Could not rediscover static field context for C2")
    static = read_table(static_path).copy()
    if "dominant_sko_id" not in static.columns:
        raise RuntimeError(f"{static_path} lacks dominant_sko_id")
    key = field_key(static)
    if key is None:
        raise RuntimeError(f"{static_path} lacks a field join key")
    static["_join_key"] = key
    if static["_join_key"].duplicated().any():
        raise RuntimeError("Static field context has duplicate current field keys")
    lookup = static[["_join_key", "dominant_sko_id"]].rename(
        columns={"dominant_sko_id": "dominant_sko_id_c2"}
    )
    out = frame.merge(
        lookup,
        left_on="current_field_id",
        right_on="_join_key",
        how="left",
        validate="one_to_one",
    ).drop(columns=["_join_key"])
    out["dominant_sko_id_c2"] = out["dominant_sko_id_c2"].astype("string")
    return out, str(static_path)


def area_deciles(frame: pd.DataFrame) -> pd.Series:
    area = pd.to_numeric(frame["static__field_area_m2"], errors="coerce")
    if area.isna().any() or (area <= 0).any():
        raise RuntimeError("C2 area control requires positive, complete static__field_area_m2")
    log_area = np.log(area.to_numpy(float))
    bins = pd.qcut(log_area, q=10, labels=False, duplicates="drop")
    return pd.Series(bins, index=frame.index, dtype="Int64").astype("string")


def analyse_feature(
    frame: pd.DataFrame,
    col: str,
    c1_lookup: dict[str, dict[str, Any]],
    sko: pd.Series,
    local: pd.Series,
    local_area: pd.Series,
) -> dict[str, Any]:
    raw = stage_stats(frame, col, None)
    s1 = stage_stats(frame, col, sko)
    s2 = stage_stats(frame, col, local)
    s3 = stage_stats(frame, col, local_area)

    source, feature = col.split("__", 1)
    c1 = c1_lookup.get(col, {})
    raw_smd_c1 = c1.get("standardized_mean_difference")
    return {
        "source": source,
        "feature": feature,
        "column": col,
        "qa_or_selection_biased": col in QA_OR_SELECTION_BIASED,
        "raw_smd_c1": raw_smd_c1,
        "raw_smd_recomputed": raw["smd"],
        "raw_rank_auc": raw["rank_auc"],
        "sko_smd": s1["smd"],
        "sko_rank_auc": s1["rank_auc"],
        "sko_n_positive": s1["n_positive"],
        "sko_n_unlabeled": s1["n_unlabeled"],
        "sko_n_strata": s1["n_strata"],
        "local_smd": s2["smd"],
        "local_rank_auc": s2["rank_auc"],
        "local_n_positive": s2["n_positive"],
        "local_n_unlabeled": s2["n_unlabeled"],
        "local_n_strata": s2["n_strata"],
        "local_area_smd": s3["smd"],
        "local_area_rank_auc": s3["rank_auc"],
        "local_area_n_positive": s3["n_positive"],
        "local_area_n_unlabeled": s3["n_unlabeled"],
        "local_area_n_strata": s3["n_strata"],
        "abs_local_area_smd": abs(s3["smd"]) if s3["smd"] is not None else None,
        "same_direction_raw_to_local_area": (
            bool(np.sign(raw["smd"]) == np.sign(s3["smd"]))
            if raw["smd"] is not None and s3["smd"] is not None
            else None
        ),
        "local_area_over_raw_abs": (
            abs(s3["smd"]) / abs(raw["smd"])
            if raw["smd"] not in (None, 0) and s3["smd"] is not None
            else None
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", default=str(DEFAULT_MATRIX))
    ap.add_argument("--c1", default=str(DEFAULT_C1))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    matrix_path = Path(args.matrix)
    c1_path = Path(args.c1)
    if not matrix_path.exists() or not c1_path.exists():
        raise FileNotFoundError("Run C1 first; field_feature_matrix/raw_positive_profile missing")

    frame = pd.read_parquet(matrix_path)
    if len(frame) != 128636 or int(frame["is_positive"].sum()) != 3079:
        raise RuntimeError("C2 population anchors require 128,636 fields and 3,079 positives")
    if "static__field_area_m2" not in frame.columns:
        raise RuntimeError("C2 requires static__field_area_m2 from C1")

    frame, static_path = attach_sko(frame)
    sko = frame["dominant_sko_id_c2"]
    municipality = frame["municipality"].astype("string")
    local = municipality + "|" + sko
    area_bin = area_deciles(frame)
    local_area = municipality + "|" + sko + "|A" + area_bin

    c1 = pd.read_csv(c1_path)
    c1_lookup = {
        str(r["column"]): r.to_dict()
        for _, r in c1.iterrows()
        if pd.notna(r.get("column"))
    }

    feature_cols = [c for c in frame.columns if "__" in c]
    rows = [
        analyse_feature(frame, col, c1_lookup, sko, local, local_area)
        for col in feature_cols
    ]
    full = pd.DataFrame(rows)
    full = full.sort_values(
        ["qa_or_selection_biased", "abs_local_area_smd"],
        ascending=[True, False],
        kind="mergesort",
    ).reset_index(drop=True)

    primary_rows = []
    for label, col in PRIMARY_FEATURES:
        q = full[full["column"].eq(col)]
        if len(q):
            row = q.iloc[0].to_dict()
            row["label"] = label
            primary_rows.append(row)
    primary = pd.DataFrame(primary_rows)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    full_path = out / "controlled_profile_all_features.csv"
    primary_path = out / "controlled_profile_primary.csv"
    frame_path = out / "field_control_context.parquet"
    full.to_csv(full_path, index=False, encoding="utf-8-sig")
    primary.to_csv(primary_path, index=False, encoding="utf-8-sig")
    frame[[
        "current_field_id", "municipality", "dominant_sko_id_c2",
        "static__field_area_m2", "is_positive"
    ]].assign(area_decile=area_bin).to_parquet(frame_path, index=False)

    report = {
        "schema_version": "akerfro-ertor-controlled-profile-c2-v0a",
        "analysis_type": "positive-unlabeled residualized within-stratum descriptive contrasts",
        "current_fields": int(len(frame)),
        "positive_fields": int(frame["is_positive"].sum()),
        "dominant_sko_coverage_pct": 100.0 * float(sko.notna().mean()),
        "dominant_sko_count": int(sko.nunique(dropna=True)),
        "municipality_sko_count": int(local.dropna().nunique()),
        "area_bins": int(area_bin.nunique()),
        "static_context_source": static_path,
        "stages": [
            "raw",
            "within dominant SKO",
            "within municipality x SKO",
            "within municipality x SKO x global log-area decile",
        ],
        "interpretation_guardrail": (
            "Attenuation after geography/area control suggests raw selection/geography confounding. "
            "Persistence suggests a within-locality field-level association, but still does not "
            "prove agronomic causality because contracts, access, irrigation and unobserved farm "
            "selection can remain."
        ),
        "outputs": {
            "all_features": str(full_path),
            "primary_features": str(primary_path),
            "control_context": str(frame_path),
        },
    }
    json_path = out / "controlled_profile_summary.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 116)
    print("ÅkerFrö – Ärter MVP v0a · C2 GEOGRAPHY/AREA-CONTROLLED FINGERPRINT")
    print("=" * 116)
    print(
        f"Fields: {len(frame):,} · positives: {int(frame['is_positive'].sum()):,} · "
        f"dominant SKO coverage: {report['dominant_sko_coverage_pct']:.2f}%"
    )
    print(
        f"SKO strata: {report['dominant_sko_count']} · municipality×SKO: "
        f"{report['municipality_sko_count']} · area bins: {report['area_bins']}"
    )

    print("\nPRIMARY DEDUPLICATED SIGNALS")
    cols = [
        "label", "raw_smd_c1", "sko_smd", "local_smd", "local_area_smd",
        "local_area_rank_auc", "local_area_n_positive", "local_area_n_strata",
    ]
    print(primary[cols].to_string(index=False, formatters={
        "raw_smd_c1": lambda v: f"{v:+7.3f}",
        "sko_smd": lambda v: f"{v:+7.3f}",
        "local_smd": lambda v: f"{v:+7.3f}",
        "local_area_smd": lambda v: f"{v:+7.3f}",
        "local_area_rank_auc": lambda v: f"{v:6.3f}",
    }))

    nonqa = full[~full["qa_or_selection_biased"]].head(25)
    print("\nTOP CONTROLLED SIGNALS BY |LOCAL+AREA SMD| (QA/coverage variables excluded)")
    cols2 = [
        "source", "feature", "raw_smd_c1", "sko_smd", "local_smd",
        "local_area_smd", "local_area_rank_auc", "local_area_n_positive",
    ]
    print(nonqa[cols2].to_string(index=False, formatters={
        "raw_smd_c1": lambda v: f"{v:+7.3f}",
        "sko_smd": lambda v: f"{v:+7.3f}",
        "local_smd": lambda v: f"{v:+7.3f}",
        "local_area_smd": lambda v: f"{v:+7.3f}",
        "local_area_rank_auc": lambda v: f"{v:6.3f}",
    }))

    print("\nINTERPRETATION GUARDRAIL")
    print(report["interpretation_guardrail"])
    print(f"\nFull controlled profile: {full_path}")
    print(f"Primary deduplicated profile: {primary_path}")
    print(f"Control context: {frame_path}")
    print(f"Summary: {json_path}")
    print("=" * 116)
    print("C2 CONTROLLED FINGERPRINT: PASS")
    print("=" * 116)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
