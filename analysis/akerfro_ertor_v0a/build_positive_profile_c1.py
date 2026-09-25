#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerFrö – Ärter MVP v0a · C1 raw positive fingerprint.

Read-only discovery and join of existing frozen/static ÅkerSync feature outputs,
followed by descriptive comparison of clean historical CONSERVART-positive
current fields versus the remaining unlabeled current-field universe.

This is positive-unlabeled descriptive analysis, not causal inference and not a
binary suitability classifier.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HISTORY = ROOT / "data" / "derived" / "akerfro_ertor_v0a" / "pea_history_by_field.parquet"
DEFAULT_OUT = ROOT / "work" / "akerfro_ertor_v0a" / "positive_profile_c1"

ROOT_NAMES = [
    "AkerSyncRepo",
    "AkerSync-Minne",
    "AkerSync-Prestation",
    "AkerSync-AkerNorm",
    "AkerSync-NormYield",
    "AkerSync-Prelim2026",
    "AkerSync-Rapskartan",
    "AkerSyncClass910",
    "AkerSyncRegression",
    "AkerSync-AkerFro",
]

SOURCE_SPECS = {
    "static": {
        "grain": "field",
        "patterns": ["akerprestation_phase0/skane/field_static_context.parquet"],
    },
    "soil": {
        "grain": "field",
        "patterns": ["soil_features_skiften.csv"],
    },
    "geometry": {
        "grain": "field",
        "patterns": ["geometry_v1a_skiften.csv"],
    },
    "akerscore": {
        "grain": "field",
        "patterns": ["**/akerscore_soil_skiften.csv"],
    },
    "akerdrift": {
        "grain": "field",
        "patterns": ["**/akerdrift_fast_v1_skane.parquet"],
    },
    "topography": {
        "grain": "block",
        "patterns": ["topography_features_blocks.csv", "**/topography_features_blocks.csv"],
    },
    "hydrology": {
        "grain": "block",
        "patterns": ["hydrology_features_blocks.csv", "**/hydrology_features_blocks.csv"],
    },
}

CURATED = {
    "static": [
        "field_area_m2",
        "dominant_sko_share",
        "sko_count",
        "dominant_soil_class",
        "dominant_soil_class_share",
        "soil_class_count",
        "unclassified_soil_share",
        "mixed_soil_class",
        "crosses_sko_boundary",
    ],
    "soil": [
        "clay_mean", "clay_p10", "clay_p50", "clay_p90", "clay_coverage_pct",
        "silt_mean", "silt_p10", "silt_p50", "silt_p90", "silt_coverage_pct",
        "sand_mean", "sand_p10", "sand_p50", "sand_p90", "sand_coverage_pct",
        "organic_ge20_share_pct", "organic_coverage_pct",
        "texture_sum_mean_pct",
    ],
    "geometry": [
        "area_ha", "perimeter_per_ha_m", "mbr_aspect_ratio", "rectangularity",
        "convexity", "erl_proxy_m", "compactness_4piA_P2",
        "largest_component_share_pct", "hole_count",
    ],
    "akerscore": [
        "akerscore_soil_p10", "akerscore_soil_p50", "akerscore_soil_p90",
        "akerscore_soil_mean", "akerscore_soil_sd",
        "akerscore_soil_spread_p90_p10", "raw_score_p50", "soil_coverage_pct",
    ],
    "akerdrift": [
        "akerdrift_score", "geometry_score", "pa_ratio",
        "drift_slope_difficulty", "drift_terrain_factor",
        "drift_slope_mean_deg", "drift_slope_p90_deg", "drift_slope_p95_deg",
        "drift_slope_gt5_share", "drift_slope_gt10_share",
        "drift_slope_coverage", "drift_twi_mean",
        "drift_twi_p90_share", "drift_twi_p95_share", "drift_twi_coverage",
        "rectangularity", "convexity", "compactness", "mbr_aspect", "erl",
    ],
    "topography": [
        "elev_mean_m", "elev_p05_m", "elev_p50_m", "elev_p95_m",
        "relief_p95_p05_m", "slope_mean_deg", "slope_p50_deg",
        "slope_p90_deg", "slope_p95_deg", "slope_gt_3_pct", "slope_gt_5_pct",
        "slope_lt_1_pct", "dem_coverage_pct", "slope_coverage_pct",
    ],
    "hydrology": [
        "twi_mean", "twi_sd", "twi_p10", "twi_p50", "twi_p90", "twi_p95",
        "twi_ge_global_p90_pct", "twi_ge_global_p95_pct", "twi_coverage_pct",
        "hydro_slope_mean_deg", "hydro_slope_p90_deg", "hydro_slope_p95_deg",
        "hydro_slope_coverage_pct",
    ],
}


def text_id(v: Any) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False, encoding="utf-8-sig")


def roots() -> list[Path]:
    out = []
    for name in ROOT_NAMES:
        path = Path("C:/") / name
        if path.exists():
            out.append(path)
    return out


def discover_candidates(source: str) -> list[Path]:
    spec = SOURCE_SPECS[source]
    found: list[Path] = []
    seen: set[str] = set()
    for root in roots():
        derived = root / "data" / "derived"
        if not derived.exists():
            continue
        for pattern in spec["patterns"]:
            for path in derived.glob(pattern):
                if path.is_file():
                    key = str(path.resolve()).lower()
                    if key not in seen:
                        seen.add(key)
                        found.append(path)
    return sorted(found, key=lambda p: str(p).lower())


def field_key(frame: pd.DataFrame) -> pd.Series | None:
    for col in ("current_field_id", "field_id", "field_key"):
        if col in frame.columns:
            return frame[col].map(text_id)
    pairs = [
        ("blockid", "skiftesbeteckning"),
        ("block_id", "skifte_id"),
        ("current_block_id", "current_skiftesbeteckning"),
    ]
    for block, skifte in pairs:
        if block in frame.columns and skifte in frame.columns:
            return frame[block].map(text_id) + "|" + frame[skifte].map(text_id)
    return None


def block_key(frame: pd.DataFrame) -> pd.Series | None:
    for col in ("blockid", "block_id", "current_block_id"):
        if col in frame.columns:
            return frame[col].map(text_id)
    return None


def assess_candidate(path: Path, grain: str, field_ids: set[str], block_ids: set[str]) -> dict[str, Any]:
    try:
        frame = read_table(path)
    except Exception as exc:
        return {"path": str(path), "read_ok": False, "error": repr(exc)}
    key = field_key(frame) if grain == "field" else block_key(frame)
    if key is None:
        return {
            "path": str(path), "read_ok": True, "rows": len(frame), "columns": len(frame.columns),
            "unique_keys": 0, "duplicate_key_rows": None, "join_hits": 0, "join_coverage_pct": 0.0,
        }
    key = key.astype(str)
    key = key[key.ne("")]
    unique = set(key.unique())
    universe = field_ids if grain == "field" else block_ids
    hits = len(unique & universe)
    return {
        "path": str(path),
        "read_ok": True,
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "unique_keys": int(len(unique)),
        "duplicate_key_rows": int(key.duplicated(keep=False).sum()),
        "join_hits": int(hits),
        "join_coverage_pct": 100.0 * hits / len(universe) if universe else 0.0,
    }


def choose_source(source: str, field_ids: set[str], block_ids: set[str]) -> tuple[Path | None, list[dict[str, Any]]]:
    grain = SOURCE_SPECS[source]["grain"]
    reports = [
        assess_candidate(path, grain, field_ids, block_ids)
        for path in discover_candidates(source)
    ]
    good = [r for r in reports if r.get("read_ok") and r.get("join_hits", 0) > 0]
    if not good:
        return None, reports
    good.sort(
        key=lambda r: (
            float(r.get("join_coverage_pct", 0.0)),
            int(r.get("join_hits", 0)),
            -int(r.get("duplicate_key_rows") or 0),
            str(r["path"]),
        ),
        reverse=True,
    )
    return Path(good[0]["path"]), reports


def source_features(source: str, frame: pd.DataFrame) -> list[str]:
    wanted = CURATED[source]
    return [
        col for col in wanted
        if col in frame.columns and (
            pd.api.types.is_numeric_dtype(frame[col]) or pd.api.types.is_bool_dtype(frame[col])
        )
    ]


def merge_source(base: pd.DataFrame, source: str, path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    grain = SOURCE_SPECS[source]["grain"]
    frame = read_table(path).copy()
    features = source_features(source, frame)
    if not features:
        return base, {"source": source, "path": str(path), "features": [], "joined": False}

    if grain == "field":
        key = field_key(frame)
        if key is None:
            raise RuntimeError(f"{source}: no field key in {path}")
        frame["_join_key"] = key
        # Full-field source tables should be one row per field. If duplicate keys
        # exist, deterministic first row is allowed only when all curated numeric
        # feature values are identical within the duplicate key.
        dup = frame[frame["_join_key"].duplicated(keep=False) & frame["_join_key"].ne("")]
        if len(dup):
            for col in features:
                bad = dup.groupby("_join_key")[col].nunique(dropna=False)
                if (bad > 1).any():
                    raise RuntimeError(
                        f"{source}: conflicting duplicate field keys for feature {col} in {path}"
                    )
            frame = frame.drop_duplicates("_join_key", keep="first")
        lookup = frame[["_join_key", *features]].copy()
        rename = {col: f"{source}__{col}" for col in features}
        lookup = lookup.rename(columns=rename)
        out = base.merge(
            lookup,
            left_on="current_field_id",
            right_on="_join_key",
            how="left",
            validate="one_to_one",
        ).drop(columns=["_join_key"])
    else:
        key = block_key(frame)
        if key is None:
            raise RuntimeError(f"{source}: no block key in {path}")
        frame["_join_key"] = key
        dup = frame[frame["_join_key"].duplicated(keep=False) & frame["_join_key"].ne("")]
        if len(dup):
            for col in features:
                bad = dup.groupby("_join_key")[col].nunique(dropna=False)
                if (bad > 1).any():
                    raise RuntimeError(
                        f"{source}: conflicting duplicate block keys for feature {col} in {path}"
                    )
            frame = frame.drop_duplicates("_join_key", keep="first")
        lookup = frame[["_join_key", *features]].copy()
        rename = {col: f"{source}__{col}" for col in features}
        lookup = lookup.rename(columns=rename)
        out = base.merge(
            lookup,
            left_on="current_block_id",
            right_on="_join_key",
            how="left",
            validate="many_to_one",
        ).drop(columns=["_join_key"])

    return out, {
        "source": source,
        "grain": grain,
        "path": str(path),
        "features": [f"{source}__{col}" for col in features],
        "joined": True,
    }


def rank_auc(pos: np.ndarray, unl: np.ndarray) -> float | None:
    pos = pos[np.isfinite(pos)]
    unl = unl[np.isfinite(unl)]
    if len(pos) == 0 or len(unl) == 0:
        return None
    values = np.concatenate([pos, unl])
    ranks = pd.Series(values).rank(method="average").to_numpy(float)
    n1 = len(pos)
    n0 = len(unl)
    u = ranks[:n1].sum() - n1 * (n1 + 1) / 2.0
    return float(u / (n1 * n0))


def describe_feature(frame: pd.DataFrame, col: str) -> dict[str, Any]:
    values = pd.to_numeric(frame[col], errors="coerce")
    pos = values[frame["is_positive"]].dropna().to_numpy(float)
    unl = values[~frame["is_positive"]].dropna().to_numpy(float)
    allv = values.dropna().to_numpy(float)
    if len(pos) == 0 or len(unl) == 0:
        return {}

    def q(v: np.ndarray, p: float) -> float:
        return float(np.quantile(v, p)) if len(v) else math.nan

    mean_pos = float(np.mean(pos))
    mean_unl = float(np.mean(unl))
    sd_pos = float(np.std(pos, ddof=1)) if len(pos) > 1 else math.nan
    sd_unl = float(np.std(unl, ddof=1)) if len(unl) > 1 else math.nan
    denom = math.sqrt((sd_pos ** 2 + sd_unl ** 2) / 2.0) if np.isfinite(sd_pos) and np.isfinite(sd_unl) else math.nan
    smd = (mean_pos - mean_unl) / denom if denom and np.isfinite(denom) else math.nan
    auc = rank_auc(pos, unl)

    source, feature = col.split("__", 1)
    return {
        "source": source,
        "feature": feature,
        "column": col,
        "n_positive": int(len(pos)),
        "coverage_positive_pct": 100.0 * len(pos) / int(frame["is_positive"].sum()),
        "n_unlabeled": int(len(unl)),
        "coverage_unlabeled_pct": 100.0 * len(unl) / int((~frame["is_positive"]).sum()),
        "n_all": int(len(allv)),
        "coverage_all_pct": 100.0 * len(allv) / len(frame),
        "positive_mean": mean_pos,
        "positive_sd": sd_pos,
        "positive_p10": q(pos, .10),
        "positive_p25": q(pos, .25),
        "positive_p50": q(pos, .50),
        "positive_p75": q(pos, .75),
        "positive_p90": q(pos, .90),
        "unlabeled_mean": mean_unl,
        "unlabeled_sd": sd_unl,
        "unlabeled_p10": q(unl, .10),
        "unlabeled_p25": q(unl, .25),
        "unlabeled_p50": q(unl, .50),
        "unlabeled_p75": q(unl, .75),
        "unlabeled_p90": q(unl, .90),
        "all_p50": q(allv, .50),
        "median_difference": q(pos, .50) - q(unl, .50),
        "standardized_mean_difference": smd,
        "rank_auc_positive_gt_unlabeled": auc,
        "rank_shift_from_half": (auc - .5) if auc is not None else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", default=str(DEFAULT_HISTORY))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    hist = pd.read_parquet(Path(args.history))
    needed = {
        "current_field_id", "current_block_id", "current_skiftesbeteckning",
        "n_target_pea_years_2015_2025",
    }
    missing = sorted(needed - set(hist.columns))
    if missing:
        raise RuntimeError(f"ÅkerFrö history missing {missing}")

    base = hist[[
        "current_field_id", "current_block_id", "current_skiftesbeteckning",
        "municipality", "n_target_pea_years_2015_2025",
    ]].copy()
    base["current_field_id"] = base["current_field_id"].map(text_id)
    base["current_block_id"] = base["current_block_id"].map(text_id)
    base["is_positive"] = base["n_target_pea_years_2015_2025"].gt(0)
    if len(base) != 128636 or base["current_field_id"].nunique() != 128636:
        raise RuntimeError("C1 requires exactly 128,636 unique current fields")
    if int(base["is_positive"].sum()) != 3079:
        raise RuntimeError("C1 positive anchor must remain 3,079 fields")

    field_ids = set(base["current_field_id"])
    block_ids = set(base["current_block_id"])

    discovery_rows = []
    joined_meta = []
    merged = base.copy()

    for source in SOURCE_SPECS:
        chosen, reports = choose_source(source, field_ids, block_ids)
        for r in reports:
            discovery_rows.append({"source": source, **r, "chosen": chosen is not None and Path(r["path"]) == chosen})
        if chosen is None:
            joined_meta.append({"source": source, "joined": False, "path": None, "features": []})
            continue
        merged, meta = merge_source(merged, source, chosen)
        joined_meta.append(meta)

    feature_cols = [c for c in merged.columns if "__" in c]
    rows = []
    for col in feature_cols:
        row = describe_feature(merged, col)
        if row:
            rows.append(row)
    stats = pd.DataFrame(rows)
    if stats.empty:
        raise RuntimeError("No numeric C1 features available after discovery/join")

    stats["abs_smd"] = stats["standardized_mean_difference"].abs()
    stats["abs_rank_shift"] = stats["rank_shift_from_half"].abs()
    stats = stats.sort_values(
        ["abs_smd", "abs_rank_shift", "coverage_all_pct"],
        ascending=[False, False, False],
        kind="mergesort",
    ).reset_index(drop=True)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    discovery = pd.DataFrame(discovery_rows)
    discovery_path = out / "source_discovery.csv"
    stats_path = out / "raw_positive_profile.csv"
    merged_path = out / "field_feature_matrix.parquet"
    discovery.to_csv(discovery_path, index=False, encoding="utf-8-sig")
    stats.to_csv(stats_path, index=False, encoding="utf-8-sig")
    merged.to_parquet(merged_path, index=False)

    report = {
        "schema_version": "akerfro-ertor-positive-profile-c1-v0a",
        "analysis_type": "positive-unlabeled descriptive raw comparison",
        "current_fields": int(len(merged)),
        "clean_positive_fields": int(merged["is_positive"].sum()),
        "unlabeled_fields": int((~merged["is_positive"]).sum()),
        "sources_joined": joined_meta,
        "feature_count": int(len(stats)),
        "features_ge_95pct_positive_coverage": int((stats["coverage_positive_pct"] >= 95).sum()),
        "features_ge_95pct_all_coverage": int((stats["coverage_all_pct"] >= 95).sum()),
        "interpretation_guardrail": (
            "Raw positive-vs-unlabeled differences can reflect geography, processor logistics, "
            "contracts and historical selection as well as agronomy. No causal or suitability "
            "claim is made at C1. Geography-controlled comparisons are required next."
        ),
        "outputs": {
            "source_discovery": str(discovery_path),
            "raw_positive_profile": str(stats_path),
            "field_feature_matrix": str(merged_path),
        },
    }
    json_path = out / "raw_positive_profile_summary.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 118)
    print("ÅkerFrö – Ärter MVP v0a · C1 RAW POSITIVE FINGERPRINT")
    print("=" * 118)
    print(f"Fields: {len(merged):,} · positives: {int(merged['is_positive'].sum()):,} · unlabeled: {int((~merged['is_positive']).sum()):,}")
    print("\nCHOSEN SOURCES")
    for meta in joined_meta:
        if meta["joined"]:
            print(f"  {meta['source']:10s}: {meta['path']} · {len(meta['features'])} curated features")
        else:
            print(f"  {meta['source']:10s}: NOT FOUND / NOT JOINED")

    print(
        f"\nFeatures analysed: {len(stats)} · >=95% positive coverage: "
        f"{int((stats['coverage_positive_pct'] >= 95).sum())} · >=95% all-field coverage: "
        f"{int((stats['coverage_all_pct'] >= 95).sum())}"
    )

    show = stats.head(30).copy()
    print("\nTOP RAW DIFFERENCES BY |STANDARDIZED MEAN DIFFERENCE|")
    cols = [
        "source", "feature", "coverage_positive_pct", "positive_p10", "positive_p50",
        "positive_p90", "unlabeled_p10", "unlabeled_p50", "unlabeled_p90",
        "standardized_mean_difference", "rank_auc_positive_gt_unlabeled",
    ]
    print(show[cols].to_string(index=False, formatters={
        "coverage_positive_pct": lambda v: f"{v:5.1f}%",
        "positive_p10": lambda v: f"{v:9.3f}",
        "positive_p50": lambda v: f"{v:9.3f}",
        "positive_p90": lambda v: f"{v:9.3f}",
        "unlabeled_p10": lambda v: f"{v:9.3f}",
        "unlabeled_p50": lambda v: f"{v:9.3f}",
        "unlabeled_p90": lambda v: f"{v:9.3f}",
        "standardized_mean_difference": lambda v: f"{v:+7.3f}",
        "rank_auc_positive_gt_unlabeled": lambda v: f"{v:6.3f}",
    }))

    print("\nINTERPRETATION GUARDRAIL")
    print(report["interpretation_guardrail"])
    print(f"\nDiscovery: {discovery_path}")
    print(f"Full profile: {stats_path}")
    print(f"Field matrix: {merged_path}")
    print(f"Summary: {json_path}")
    print("=" * 118)
    print("C1 RAW POSITIVE FINGERPRINT: PASS")
    print("=" * 118)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
