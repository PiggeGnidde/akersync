#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Apply frozen ÅkerDrift Fast V2 Hybrid RC1 to all-Skåne Fast V1 output.

V2 is used only inside the route-calibration support.  Fields outside support
keep their Fast V1 score; the clipped V2 value is retained as diagnostics.
The run writes to a new directory and never updates ÅkerPass web data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from akerdrift_fast_v2_core import geometry_scores, load_model_config


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FAST_V1 = ROOT / "data" / "derived" / "akerdrift_fast_v1" / "akerdrift_fast_v1_skane.parquet"
DEFAULT_GEOMETRY = ROOT / "data" / "derived" / "geometry_v1a_skiften.csv"
DEFAULT_MODEL = ROOT / "config" / "akerdrift_fast_v2_routecal_rc0.json"
DEFAULT_OUTPUT = ROOT / "data" / "derived" / "akerdrift_fast_v2_hybrid_rc1"
OUTPUT_NAME = "akerdrift_fast_v2_hybrid_rc1_skane.parquet"
APPLICATION_VERSION = "akerdrift-fast-v2-hybrid-rc1"
SCORED_STATUSES = {"OK", "LIMITED_SLOPE_COVERAGE"}
PERCENTILES = (1, 5, 10, 25, 50, 75, 90, 95, 99)


def text_id(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value)
    return text[:-2] if text.endswith(".0") else text


def field_keys(block: pd.Series, field: pd.Series) -> pd.Series:
    return pd.Series(
        [f"{text_id(left)}|{text_id(right)}" for left, right in zip(block, field)],
        index=block.index,
        dtype="string",
    )


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def prepare_geometry(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "blockid", "skiftesbeteckning", "area_ha", "rectangularity",
        "compactness_4piA_P2", "erl_proxy_m", "hole_count",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("Geometry V1a saknar kolumner: " + ", ".join(missing))
    geometry = frame.copy()
    geometry["field_key"] = field_keys(geometry["blockid"], geometry["skiftesbeteckning"])
    if geometry["field_key"].duplicated().any():
        raise ValueError("Geometry V1a innehåller dubbla skiftesnycklar")
    return geometry[[
        "field_key", "area_ha", "rectangularity", "compactness_4piA_P2",
        "erl_proxy_m", "hole_count",
    ]].rename(columns={
        "area_ha": "geometry_area_ha",
        "rectangularity": "geometry_rectangularity",
        "compactness_4piA_P2": "geometry_compactness",
        "erl_proxy_m": "geometry_erl_m",
        "hole_count": "geometry_hole_count",
    })


def feature_frame(joined: pd.DataFrame) -> pd.DataFrame:
    area = _numeric(joined, "area_ha").fillna(_numeric(joined, "geometry_area_ha"))
    rectangularity = _numeric(joined, "rectangularity").fillna(_numeric(joined, "geometry_rectangularity"))
    compactness = _numeric(joined, "compactness").fillna(_numeric(joined, "geometry_compactness"))
    erl = _numeric(joined, "erl").fillna(_numeric(joined, "geometry_erl_m"))
    holes = _numeric(joined, "geometry_hole_count")
    features = pd.DataFrame(index=joined.index)
    features["fast_geometry_score"] = _numeric(joined, "geometry_score")
    features["log_area_ha"] = np.log(area.where(area > 0))
    features["rectangularity"] = rectangularity
    features["compactness"] = compactness
    features["log_erl_m"] = np.log(erl.where(erl > 0))
    features["has_holes"] = holes.gt(0).astype(float)
    features["holes_capped_5"] = holes.clip(lower=0, upper=5)
    return features


def rescore_frame(
    fast_v1: pd.DataFrame,
    geometry: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    required = {
        "block_id", "skifte_id", "kommun", "akerdrift_score", "geometry_score",
        "drift_terrain_factor", "drift_status", "drift_model_version",
    }
    missing = sorted(required - set(fast_v1.columns))
    if missing:
        raise ValueError("Fast V1 saknar kolumner: " + ", ".join(missing))
    output = fast_v1.copy()
    output["field_key"] = field_keys(output["block_id"], output["skifte_id"])
    if output["field_key"].duplicated().any():
        raise ValueError("Fast V1 innehåller dubbla skiftesnycklar")
    joined = output.merge(prepare_geometry(geometry), on="field_key", how="left", validate="one_to_one")
    features = feature_frame(joined)
    finite = np.isfinite(features.to_numpy(dtype=float)).all(axis=1)
    terrain = _numeric(joined, "drift_terrain_factor")
    base_scored = joined["drift_status"].astype(str).isin(SCORED_STATUSES) & _numeric(joined, "akerdrift_score").notna()
    valid = base_scored & finite & terrain.notna() & np.isfinite(terrain)

    geometry_prediction = np.full(len(joined), np.nan, dtype=float)
    score_prediction = np.full(len(joined), np.nan, dtype=float)
    if valid.any():
        arrays = {name: features.loc[valid, name].to_numpy(dtype=float) for name in features.columns}
        geometry_prediction[valid] = geometry_scores(arrays, config)
        score_prediction[valid] = np.clip(geometry_prediction[valid] * terrain.loc[valid].to_numpy(float), 0, 100)

    model = config["geometry_model"]
    outside = pd.DataFrame(False, index=joined.index, columns=model["continuous_features"])
    clip_rows = []
    for name in model["continuous_features"]:
        low, high = (float(value) for value in model["clip_ranges"][name])
        values = features[name]
        below = valid & values.lt(low)
        above = valid & values.gt(high)
        outside[name] = below | above
        clip_rows.append({
            "feature": name,
            "calibration_min": low,
            "calibration_max": high,
            "n_below": int(below.sum()),
            "n_above": int(above.sum()),
            "n_outside": int((below | above).sum()),
            "share_of_scored": float((below | above).sum() / valid.sum()) if valid.sum() else math.nan,
        })
    clipped_count = outside.sum(axis=1)
    support = pd.Series("NOT_SCORED_FAST_V1", index=joined.index, dtype="string")
    support.loc[base_scored & ~valid] = "MISSING_GEOMETRY_FEATURES"
    support.loc[valid & clipped_count.eq(0)] = "IN_CALIBRATION_RANGE"
    support.loc[valid & clipped_count.gt(0)] = "CLIPPED_TO_CALIBRATION_RANGE"

    v1_score = _numeric(joined, "akerdrift_score")
    v1_geometry = _numeric(joined, "geometry_score")
    use_v2 = valid & clipped_count.eq(0)
    fallback_outside = valid & clipped_count.gt(0)
    fallback_missing = base_scored & ~valid
    official_score = v1_score.copy()
    official_geometry = v1_geometry.copy()
    official_score.loc[use_v2] = score_prediction[use_v2]
    official_geometry.loc[use_v2] = geometry_prediction[use_v2]
    score_source = pd.Series("NOT_SCORED", index=joined.index, dtype="string")
    score_source.loc[use_v2] = "FAST_V2_ROUTECAL"
    score_source.loc[fallback_outside] = "FAST_V1_FALLBACK_OUTSIDE_CALIBRATION"
    score_source.loc[fallback_missing] = "FAST_V1_FALLBACK_MISSING_FEATURES"

    joined["fast_v1_akerdrift_score"] = v1_score
    joined["fast_v1_geometry_score"] = v1_geometry
    joined["fast_v1_drift_model_version"] = joined["drift_model_version"].astype("string")
    joined["routecal_geometry_score_diagnostic"] = geometry_prediction
    joined["routecal_akerdrift_score_diagnostic"] = score_prediction
    joined["geometry_score"] = official_geometry
    joined["akerdrift_score"] = official_score
    joined["drift_model_version"] = APPLICATION_VERSION
    joined["drift_score_source"] = score_source
    joined["drift_routecal_support"] = support
    joined["drift_routecal_clipped_feature_count"] = clipped_count.astype(int)
    joined["score_delta_hybrid_minus_v1"] = joined["akerdrift_score"] - joined["fast_v1_akerdrift_score"]
    joined["routecal_score_delta_diagnostic"] = (
        joined["routecal_akerdrift_score_diagnostic"] - joined["fast_v1_akerdrift_score"]
    )

    drop = [
        "geometry_area_ha", "geometry_rectangularity", "geometry_compactness",
        "geometry_erl_m", "geometry_hole_count",
    ]
    joined["hole_count"] = _numeric(joined, "geometry_hole_count")
    joined = joined.drop(columns=drop)
    return joined, pd.DataFrame(clip_rows), features


def percentile_dict(values: pd.Series) -> dict[str, float | None]:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return {f"P{value}": None for value in PERCENTILES}
    return {f"P{value}": float(np.percentile(numeric, value)) for value in PERCENTILES}


def qa_outputs(frame: pd.DataFrame, clip: pd.DataFrame, output_dir: Path, model_hash: str) -> None:
    qa = output_dir / "qa"
    qa.mkdir(parents=True, exist_ok=True)
    paired = frame.dropna(subset=["akerdrift_score", "fast_v1_akerdrift_score"]).copy()
    delta = paired["score_delta_hybrid_minus_v1"]
    summary = {
        "model_version": str(frame["drift_model_version"].iloc[0]) if len(frame) else None,
        "model_config_sha256": model_hash,
        "n_total": int(len(frame)),
        "n_hybrid_scored": int(frame["akerdrift_score"].notna().sum()),
        "n_paired_v1_hybrid": int(len(paired)),
        "support_counts": {str(key): int(value) for key, value in frame["drift_routecal_support"].value_counts(dropna=False).items()},
        "score_source_counts": {str(key): int(value) for key, value in frame["drift_score_source"].value_counts(dropna=False).items()},
        "status_counts": {str(key): int(value) for key, value in frame["drift_status"].value_counts(dropna=False).items()},
        "v1_percentiles": percentile_dict(paired["fast_v1_akerdrift_score"]),
        "hybrid_percentiles": percentile_dict(paired["akerdrift_score"]),
        "hybrid_delta_percentiles": percentile_dict(delta),
        "median_absolute_delta": float(delta.abs().median()) if len(delta) else None,
        "p95_absolute_delta": float(delta.abs().quantile(0.95)) if len(delta) else None,
        "spearman_v1_hybrid": float(spearmanr(paired["fast_v1_akerdrift_score"], paired["akerdrift_score"]).statistic) if len(paired) > 1 else None,
    }
    (qa / "qa_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    clip.to_csv(qa / "calibration_range_extrapolation.csv", index=False, encoding="utf-8-sig")

    distribution = []
    for name, column in (("Fast V1", "fast_v1_akerdrift_score"), ("Fast V2 Hybrid RC1", "akerdrift_score"), ("Hybrid minus V1", "score_delta_hybrid_minus_v1")):
        values = pd.to_numeric(paired[column], errors="coerce").dropna()
        row = {"measure": name, "n": len(values), "mean": float(values.mean()), "min": float(values.min()), "max": float(values.max())}
        row.update(percentile_dict(values))
        distribution.append(row)
    pd.DataFrame(distribution).to_csv(qa / "score_distributions.csv", index=False, encoding="utf-8-sig")

    municipality_rows = []
    for municipality, part in paired.groupby("kommun", sort=True):
        municipal_delta = part["score_delta_hybrid_minus_v1"]
        municipality_rows.append({
            "kommun": municipality,
            "n": len(part),
            "v1_median": float(part["fast_v1_akerdrift_score"].median()),
            "v2_median": float(part["akerdrift_score"].median()),
            "median_delta": float(municipal_delta.median()),
            "median_absolute_delta": float(municipal_delta.abs().median()),
            "p95_absolute_delta": float(municipal_delta.abs().quantile(0.95)),
            "spearman_v1_hybrid": float(spearmanr(part["fast_v1_akerdrift_score"], part["akerdrift_score"]).statistic) if len(part) > 1 else math.nan,
            "share_v1_fallback": float(part["drift_score_source"].str.startswith("FAST_V1_FALLBACK").mean()),
        })
    pd.DataFrame(municipality_rows).to_csv(qa / "municipality_comparison.csv", index=False, encoding="utf-8-sig")

    hole_rows = []
    for has_holes, part in paired.assign(has_holes=paired["hole_count"].gt(0)).groupby("has_holes"):
        hole_delta = part["score_delta_hybrid_minus_v1"]
        hole_diagnostic_delta = part["routecal_score_delta_diagnostic"]
        hole_rows.append({
            "has_holes": bool(has_holes), "n": len(part),
            "median_delta": float(hole_delta.median()),
            "median_absolute_delta": float(hole_delta.abs().median()),
            "p95_absolute_delta": float(hole_delta.abs().quantile(0.95)),
            "diagnostic_median_delta": float(hole_diagnostic_delta.median()),
        })
    pd.DataFrame(hole_rows).to_csv(qa / "holes_comparison.csv", index=False, encoding="utf-8-sig")

    largest_columns = [
        "kommun", "block_id", "skifte_id", "area_ha", "hole_count",
        "fast_v1_akerdrift_score", "akerdrift_score", "score_delta_hybrid_minus_v1",
        "fast_v1_geometry_score", "geometry_score", "drift_terrain_factor",
        "rectangularity", "compactness", "erl", "drift_routecal_support",
        "drift_routecal_clipped_feature_count", "drift_score_source",
    ]
    largest_columns = [column for column in largest_columns if column in paired]
    paired.assign(absolute_delta=delta.abs()).sort_values("absolute_delta", ascending=False).head(250)[
        largest_columns
    ].to_csv(qa / "largest_score_changes.csv", index=False, encoding="utf-8-sig")

    support_rows = []
    for source, part in paired.groupby("drift_score_source", sort=True):
        source_delta = part["score_delta_hybrid_minus_v1"]
        source_diagnostic = part["routecal_score_delta_diagnostic"]
        support_rows.append({
            "drift_score_source": source,
            "n": len(part),
            "v1_median": float(part["fast_v1_akerdrift_score"].median()),
            "hybrid_median": float(part["akerdrift_score"].median()),
            "median_delta": float(source_delta.median()),
            "p95_absolute_delta": float(source_delta.abs().quantile(.95)),
            "diagnostic_routecal_median": float(part["routecal_akerdrift_score_diagnostic"].median()),
            "diagnostic_median_delta": float(source_diagnostic.median()),
            "diagnostic_p95_absolute_delta": float(source_diagnostic.abs().quantile(.95)),
        })
    pd.DataFrame(support_rows).to_csv(qa / "support_comparison.csv", index=False, encoding="utf-8-sig")

    area_bins = [0, .05, .10, .25, .36393953, .5, 1, 2, 5, 10, 25, 100, math.inf]
    area_labels = ["0-.05", ".05-.10", ".10-.25", ".25-.364", ".364-.5", ".5-1", "1-2", "2-5", "5-10", "10-25", "25-100", "100+"]
    area_rows = []
    area_group = pd.cut(pd.to_numeric(paired["area_ha"], errors="coerce"), bins=area_bins, labels=area_labels, include_lowest=True)
    for band, part in paired.assign(area_band=area_group).groupby("area_band", observed=True, sort=False):
        band_delta = part["score_delta_hybrid_minus_v1"]
        area_rows.append({
            "area_band_ha": str(band), "n": len(part),
            "share_v1_fallback": float(part["drift_score_source"].str.startswith("FAST_V1_FALLBACK").mean()),
            "v1_median": float(part["fast_v1_akerdrift_score"].median()),
            "hybrid_median": float(part["akerdrift_score"].median()),
            "median_delta": float(band_delta.median()),
            "p95_absolute_delta": float(band_delta.abs().quantile(.95)),
        })
    pd.DataFrame(area_rows).to_csv(qa / "area_band_comparison.csv", index=False, encoding="utf-8-sig")

    fallback = paired[paired["drift_score_source"].str.startswith("FAST_V1_FALLBACK")].copy()
    fallback_columns = [
        "kommun", "block_id", "skifte_id", "area_ha", "hole_count",
        "fast_v1_akerdrift_score", "akerdrift_score",
        "routecal_akerdrift_score_diagnostic", "routecal_score_delta_diagnostic",
        "drift_routecal_support", "drift_routecal_clipped_feature_count", "drift_score_source",
    ]
    fallback.assign(absolute_diagnostic_delta=fallback["routecal_score_delta_diagnostic"].abs()).sort_values(
        "absolute_diagnostic_delta", ascending=False
    ).head(250)[fallback_columns].to_csv(qa / "fallback_fields_largest_diagnostic_changes.csv", index=False, encoding="utf-8-sig")


def atomic_parquet(frame: pd.DataFrame, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp.parquet")
    try:
        frame.to_parquet(temporary, index=False)
        check = pd.read_parquet(temporary)
    except ImportError as exc:
        raise RuntimeError("Parquet kräver pyarrow. Kör INSTALL_REQUIREMENTS.bat.") from exc
    if len(check) != len(frame) or check["field_key"].duplicated().any():
        raise RuntimeError("Den skrivna V2-parquetfilen klarade inte valideringen")
    os.replace(temporary, destination)


def run(args: argparse.Namespace) -> int:
    fast_path = Path(args.fast_v1)
    geometry_path = Path(args.geometry)
    model_path = Path(args.model_config)
    output_dir = Path(args.output_dir)
    for label, path in (("Fast V1", fast_path), ("Geometry V1a", geometry_path), ("modellconfig", model_path)):
        if not path.exists():
            raise FileNotFoundError(f"Saknar {label}: {path}")
    try:
        fast = pd.read_parquet(fast_path)
    except ImportError as exc:
        raise RuntimeError("Parquet kräver pyarrow. Kör INSTALL_REQUIREMENTS.bat.") from exc
    geometry = pd.read_csv(
        geometry_path, encoding="utf-8-sig",
        dtype={"blockid": str, "skiftesbeteckning": str},
    )
    config = load_model_config(model_path)
    result, clip, _ = rescore_frame(fast, geometry, config)
    destination = output_dir / OUTPUT_NAME
    atomic_parquet(result, destination)
    qa_outputs(result, clip, output_dir, canonical_hash(config))
    print(
        f"HYBRID RC1: {result['akerdrift_score'].notna().sum():,}/{len(result):,} score · "
        f"V2 {result['drift_score_source'].eq('FAST_V2_ROUTECAL').sum():,} · "
        f"V1 fallback {result['drift_score_source'].str.startswith('FAST_V1_FALLBACK').sum():,}"
    )
    paired = result.dropna(subset=["akerdrift_score", "fast_v1_akerdrift_score"])
    delta = paired["score_delta_hybrid_minus_v1"].abs()
    print(
        f"V1↔Hybrid: Spearman {spearmanr(paired['fast_v1_akerdrift_score'], paired['akerdrift_score']).statistic:.3f} · "
        f"median |Δ| {delta.median():.2f} · P95 |Δ| {delta.quantile(.95):.2f}"
    )
    print(f"KLART: {destination}")
    print(f"QA: {output_dir / 'qa'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fast-v1", default=str(DEFAULT_FAST_V1))
    parser.add_argument("--geometry", default=str(DEFAULT_GEOMETRY))
    parser.add_argument("--model-config", default=str(DEFAULT_MODEL))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
