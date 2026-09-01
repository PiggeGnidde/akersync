#!/usr/bin/env python3
"""Frozen ÅkerNorm V1 model primitives.

This module contains deterministic, side-effect-free model calculations.  It
does not fetch live data, alter any upstream product, or run a full Skåne job.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


FIELD_SCHEMA_VERSION = "akernorm-field-v1"
MODEL_CONTRACT_SCHEMA = "akernorm-model-contract-v1"
SOURCE_MANIFEST_SCHEMA = "akernorm-source-manifest-v1"
MODEL_MANIFEST_SCHEMA = "akernorm-model-manifest-v1"


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_json(document: Any) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def atomic_json(document: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(stable_json(document), encoding="utf-8")
    json.loads(temporary.read_text(encoding="utf-8"))
    os.replace(temporary, path)


def atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False, encoding="utf-8-sig", lineterminator="\n")
    check = pd.read_csv(temporary, low_memory=False)
    if len(check) != len(frame) or list(check.columns) != list(frame.columns):
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"CSV verification failed: {path}")
    os.replace(temporary, path)


def atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.stem + ".tmp.parquet")
    temporary.unlink(missing_ok=True)
    frame.to_parquet(temporary, index=False)
    check = pd.read_parquet(temporary)
    if len(check) != len(frame) or list(check.columns) != list(frame.columns):
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Parquet verification failed: {path}")
    os.replace(temporary, path)


def normalized_id(value: Any, width: int = 0) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text.zfill(width) if width and text else text


def joined_flags(flags: Iterable[str]) -> str:
    return ";".join(sorted({str(flag).strip() for flag in flags if str(flag).strip()}))


def display_round(value: Any, decimals: int = 1) -> float | None:
    if value is None or pd.isna(value):
        return None
    quantum = Decimal("1").scaleb(-decimals)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def weighted_mean(values: Any, weights: Any) -> float:
    x = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    valid = np.isfinite(x) & np.isfinite(w) & (w > 0)
    if not valid.any():
        return float("nan")
    return float(np.sum(x[valid] * w[valid]) / np.sum(w[valid]))


def weighted_sd(values: Any, weights: Any) -> float:
    x = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    valid = np.isfinite(x) & np.isfinite(w) & (w > 0)
    if valid.sum() < 2:
        return float("nan")
    mean = float(np.sum(x[valid] * w[valid]) / np.sum(w[valid]))
    return float(np.sqrt(np.sum(w[valid] * (x[valid] - mean) ** 2) / np.sum(w[valid])))


def weighted_quantile(values: Any, weights: Any, probabilities: Iterable[float]) -> list[float]:
    """Return deterministic left-continuous weighted empirical quantiles."""
    x = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    valid = np.isfinite(x) & np.isfinite(w) & (w > 0)
    x, w = x[valid], w[valid]
    if not len(x):
        return [float("nan") for _ in probabilities]
    order = np.argsort(x, kind="mergesort")
    x, w = x[order], w[order]
    cumulative = np.cumsum(w)
    total = cumulative[-1]
    output = []
    for probability in probabilities:
        if not 0 <= probability <= 1:
            raise ValueError(f"Invalid quantile probability: {probability}")
        position = int(np.searchsorted(cumulative, probability * total, side="left"))
        output.append(float(x[min(position, len(x) - 1)]))
    return output


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    if config.get("schema_version") != "akernorm-model-config-v1":
        raise ValueError("Unexpected ÅkerNorm config schema")
    if float(config.get("minimum_dominant_sko_share", -1)) != 0.95:
        raise ValueError("V1 requires minimum_dominant_sko_share=0.95")
    if bool(config.get("display", {}).get("prediction_interval")):
        raise ValueError("V1 forbids individual numeric prediction intervals")
    codes: set[int] = set()
    keys: set[str] = set()
    for crop in config.get("crops", []):
        code, key = int(crop["canonical_code"]), str(crop["crop_key"])
        if code in codes or key in keys:
            raise ValueError("Duplicate crop code/key in ÅkerNorm config")
        codes.add(code)
        keys.add(key)
        beta = crop.get("beta_t_ha_per_score")
        mode = str(crop["model_mode"])
        if mode.startswith("FIELD_ADJUSTED"):
            if beta is None or float(beta) < 0:
                raise ValueError(f"Adjusted crop {key} requires a non-negative beta")
            expected = float(beta) * 10.0
            if not math.isclose(expected, float(crop["effect_t_ha_per_10_score"]), abs_tol=1e-12):
                raise ValueError(f"+10 score effect mismatch for {key}")
        elif beta is not None:
            raise ValueError(f"Unsupported crop {key} must not have beta")
    expected_modes = {
        4: "FIELD_ADJUSTED",
        2: "FIELD_ADJUSTED",
        3: "FIELD_ADJUSTED_HIGHER_UNCERTAINTY",
        20: "FIELD_ADJUSTED_WEAK_EFFECT",
        45: "OFFICIAL_SKO_ONLY_UNVALIDATED_CROP",
        46: "OFFICIAL_SKO_ONLY_UNVALIDATED_CROP",
    }
    actual_modes = {int(row["canonical_code"]): row["model_mode"] for row in config["crops"]}
    if actual_modes != expected_modes:
        raise ValueError("Frozen V1 crop modes differ from the binding contract")


def verify_presence_threshold(config: dict[str, Any], akerminne_config_path: Path) -> None:
    upstream = json.loads(akerminne_config_path.read_text(encoding="utf-8-sig"))
    actual = float(upstream["history_status"]["mixed_secondary_crop_min_share"])
    frozen = float(config["crop_presence"]["mixed_component_min_share"])
    if not math.isclose(actual, frozen, abs_tol=1e-15):
        raise RuntimeError(f"ÅkerMinne component threshold changed: expected {frozen}, got {actual}")


def prepare_inputs(
    context: pd.DataFrame,
    history: pd.DataFrame,
    score: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    required = {
        "context": {"current_field_id", "dominant_sko_id", "dominant_sko_share"},
        "history": {
            "current_field_id", "history_year", "current_area_m2",
            "dominant_crop_code_raw", "dominant_crop_name", "status",
        },
        "score": {"current_field_id", "akerscore_soil_p50"},
    }
    for label, frame in (("context", context), ("history", history), ("score", score)):
        missing = sorted(required[label] - set(frame.columns))
        if missing:
            raise RuntimeError(f"{label} missing required columns: {missing}")
    context = context.copy()
    history = history.copy()
    score = score.copy()
    context["current_field_id"] = context["current_field_id"].astype(str)
    history["current_field_id"] = history["current_field_id"].astype(str)
    score["current_field_id"] = score["current_field_id"].astype(str)
    if context["current_field_id"].duplicated().any():
        raise RuntimeError("context has duplicate current_field_id")
    if score["current_field_id"].duplicated().any():
        raise RuntimeError("score has duplicate current_field_id")
    context["dominant_sko_id"] = context["dominant_sko_id"].map(lambda v: normalized_id(v, 4))
    context["dominant_sko_share"] = pd.to_numeric(context["dominant_sko_share"], errors="coerce")
    score["akerscore_soil_p50"] = pd.to_numeric(score["akerscore_soil_p50"], errors="coerce")
    history["history_year"] = pd.to_numeric(history["history_year"], errors="coerce")
    history["current_area_m2"] = pd.to_numeric(history["current_area_m2"], errors="coerce")
    history["crop_code_canonical"] = pd.to_numeric(history["dominant_crop_code_raw"], errors="coerce").astype("Int64")
    return context, history, score


def normalize_official_norms(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"crop_key", "canonical_crop_code", "sko_id", "raw_value", "raw_unit", "norm_t_ha", "value_status"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RuntimeError(f"Normalized official norm table missing: {missing}")
    out = frame.copy()
    out["sko_id"] = out["sko_id"].map(lambda v: normalized_id(v, 4))
    out["canonical_crop_code"] = pd.to_numeric(out["canonical_crop_code"], errors="raise").astype(int)
    out["norm_t_ha"] = pd.to_numeric(out["norm_t_ha"], errors="coerce")
    if out.duplicated(["canonical_crop_code", "sko_id"]).any():
        raise RuntimeError("Official norms contain duplicate crop/SKO rows")
    missing_values = out["norm_t_ha"].isna()
    if (missing_values & out["value_status"].eq("PUBLISHED")).any():
        raise RuntimeError("Published official norm has missing numeric value")
    return out.sort_values(["canonical_crop_code", "sko_id"], kind="mergesort").reset_index(drop=True)


def build_reference_table(
    context: pd.DataFrame,
    history: pd.DataFrame,
    score: pd.DataFrame,
    official_norms: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    context, history, score = prepare_inputs(context, history, score)
    official_norms = normalize_official_norms(official_norms)
    base = context[["current_field_id", "dominant_sko_id", "dominant_sko_share"]].merge(
        score[["current_field_id", "akerscore_soil_p50"]],
        on="current_field_id", how="left", validate="one_to_one",
    )
    adjusted = {
        int(row["canonical_code"]): row
        for row in config["crops"]
        if str(row["model_mode"]).startswith("FIELD_ADJUSTED")
    }
    selected = history[
        history["status"].eq(config["reference_population"]["history_status"])
        & history["crop_code_canonical"].isin(adjusted)
    ].merge(base, on="current_field_id", how="left", validate="many_to_one")
    selected = selected[
        selected["akerscore_soil_p50"].notna()
        & selected["current_area_m2"].gt(0)
        & selected["dominant_sko_share"].ge(float(config["minimum_dominant_sko_share"]))
        & selected["dominant_sko_id"].ne("")
    ].copy()
    selected["weight_m2"] = selected["current_area_m2"].astype(float)

    rows: list[dict[str, Any]] = []
    probabilities = [0.05, 0.10, 0.50, 0.90, 0.95]
    for (code, sko), group in selected.groupby(["crop_code_canonical", "dominant_sko_id"], sort=True):
        quantiles = weighted_quantile(group["akerscore_soil_p50"], group["weight_m2"], probabilities)
        unweighted = group["akerscore_soil_p50"].quantile(probabilities, interpolation="linear").tolist()
        crop = adjusted[int(code)]
        rows.append({
            "schema_version": "akernorm-sko-crop-reference-v1",
            "crop_key": crop["crop_key"],
            "crop_code_canonical": int(code),
            "crop_name": crop["canonical_name"],
            "sko_id": normalized_id(sko, 4),
            "field_years": int(len(group)),
            "unique_fields": int(group["current_field_id"].nunique()),
            "area_year_weight_m2": float(group["weight_m2"].sum()),
            "reference_score": weighted_mean(group["akerscore_soil_p50"], group["weight_m2"]),
            "score_sd_weighted": weighted_sd(group["akerscore_soil_p50"], group["weight_m2"]),
            "score_mean_unweighted": float(group["akerscore_soil_p50"].mean()),
            "score_sd_unweighted": float(group["akerscore_soil_p50"].std(ddof=0)),
            "score_p05_weighted": quantiles[0],
            "score_p10_weighted": quantiles[1],
            "score_p50_weighted": quantiles[2],
            "score_p90_weighted": quantiles[3],
            "score_p95_weighted": quantiles[4],
            "score_p05_unweighted": float(unweighted[0]),
            "score_p10_unweighted": float(unweighted[1]),
            "score_p50_unweighted": float(unweighted[2]),
            "score_p90_unweighted": float(unweighted[3]),
            "score_p95_unweighted": float(unweighted[4]),
            "score_min": float(group["akerscore_soil_p50"].min()),
            "score_max": float(group["akerscore_soil_p50"].max()),
        })
    references = pd.DataFrame(rows)
    norm_columns = official_norms[[
        "crop_key", "canonical_crop_code", "sko_id", "norm_t_ha", "value_status"
    ]].rename(columns={
        "canonical_crop_code": "crop_code_canonical",
        "norm_t_ha": "official_sko_norm_t_ha",
        "value_status": "official_norm_status",
    })
    reference = norm_columns.merge(
        references,
        on=["crop_key", "crop_code_canonical", "sko_id"],
        how="outer", validate="one_to_one",
    )
    if "schema_version" not in reference:
        reference["schema_version"] = "akernorm-sko-crop-reference-v1"
    reference["schema_version"] = reference["schema_version"].fillna("akernorm-sko-crop-reference-v1")
    reference["reference_status"] = np.where(
        reference["reference_score"].notna() & reference["official_sko_norm_t_ha"].notna(),
        "INCLUDED",
        np.where(
            reference["official_sko_norm_t_ha"].isna(),
            "EXCLUDED_NO_OFFICIAL_NORM",
            "EXCLUDED_REFERENCE_UNAVAILABLE",
        ),
    )
    reference["exclusion_reason"] = np.where(
        reference["reference_status"].eq("INCLUDED"), "",
        reference["reference_status"],
    )
    reference = reference.sort_values(["crop_code_canonical", "sko_id"], kind="mergesort").reset_index(drop=True)
    return reference, selected


def conservation_qa(selected: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    beta_by_code = {
        int(row["canonical_code"]): float(row["beta_t_ha_per_score"])
        for row in config["crops"] if row.get("beta_t_ha_per_score") is not None
    }
    rows = []
    for (code, sko), group in selected.groupby(["crop_code_canonical", "dominant_sko_id"], sort=True):
        beta = beta_by_code[int(code)]
        reference = weighted_mean(group["akerscore_soil_p50"], group["weight_m2"])
        adjustments = beta * (group["akerscore_soil_p50"].to_numpy(float) - reference)
        weighted_adjustment = float(np.sum(adjustments * group["weight_m2"].to_numpy(float)))
        denominator = float(group["weight_m2"].sum())
        mean_adjustment = weighted_adjustment / denominator
        rows.append({
            "crop_code_canonical": int(code),
            "sko_id": normalized_id(sko, 4),
            "field_years": int(len(group)),
            "area_year_weight_m2": denominator,
            "weighted_mean_adjustment_t_ha": mean_adjustment,
            "absolute_error_t_ha": abs(mean_adjustment),
            "status": "PASS" if abs(mean_adjustment) <= 1e-12 else "FAIL",
        })
    return pd.DataFrame(rows)


def score_support_status(score: Any, reference: pd.Series | dict[str, Any] | None) -> str:
    if score is None or pd.isna(score):
        return "MISSING_AKERSCORE"
    if reference is None:
        return "REFERENCE_UNAVAILABLE"
    get = reference.get
    limits = {name: get(name) for name in ("score_min", "score_p05_weighted", "score_p95_weighted", "score_max")}
    if any(value is None or pd.isna(value) for value in limits.values()):
        return "REFERENCE_UNAVAILABLE"
    value = float(score)
    if value < float(limits["score_min"]):
        return "BELOW_OBSERVED_MIN"
    if value < float(limits["score_p05_weighted"]):
        return "BELOW_P05_WITHIN_OBSERVED"
    if value <= float(limits["score_p95_weighted"]):
        return "WITHIN_P05_P95"
    if value <= float(limits["score_max"]):
        return "ABOVE_P95_WITHIN_OBSERVED"
    return "ABOVE_OBSERVED_MAX"


def calculate_field_crop(
    field: pd.Series | dict[str, Any],
    presence: pd.Series | dict[str, Any],
    official_norm: pd.Series | dict[str, Any] | None,
    reference: pd.Series | dict[str, Any] | None,
    crop_config: dict[str, Any] | None,
    config: dict[str, Any],
    source_manifest_id: str,
) -> dict[str, Any]:
    fget, pget = field.get, presence.get
    sko_id = normalized_id(fget("dominant_sko_id"), 4)
    sko_share = pd.to_numeric(pd.Series([fget("dominant_sko_share")]), errors="coerce").iloc[0]
    score = pd.to_numeric(pd.Series([fget("akerscore_soil_p50")]), errors="coerce").iloc[0]
    norm = None if official_norm is None else official_norm.get("norm_t_ha")
    norm = None if norm is None or pd.isna(norm) else float(norm)
    reference_score = None if reference is None else reference.get("reference_score")
    reference_score = None if reference_score is None or pd.isna(reference_score) else float(reference_score)
    history_quality = str(pget("history_quality") or "STANDARD")
    reasons: list[str] = []
    if history_quality != "STANDARD":
        reasons.append(history_quality)
    mode = None if crop_config is None else str(crop_config["model_mode"])
    beta = None if crop_config is None else crop_config.get("beta_t_ha_per_score")
    adjustment = None
    value = None
    support = "NOT_APPLICABLE"

    if norm is None:
        status = "UNAVAILABLE_NO_OFFICIAL_NORM"
        reasons.append("NO_PUBLISHED_2026_NORM_FOR_CROP_SKO")
    elif crop_config is None:
        status = "OFFICIAL_SKO_ONLY_UNVALIDATED_CROP"
        reasons.append("CROP_OUTSIDE_V1_FIELD_MODEL")
    elif mode == "OFFICIAL_SKO_ONLY_UNVALIDATED_CROP":
        status = mode
        reasons.append("V1_GUARDRAIL_NO_SCORE_ADJUSTMENT")
    elif pd.isna(sko_share) or float(sko_share) < float(config["minimum_dominant_sko_share"]):
        status = "UNAVAILABLE_LOW_SKO_SHARE"
        reasons.append("DOMINANT_SKO_SHARE_BELOW_0_95")
    elif pd.isna(score):
        status = "UNAVAILABLE_MISSING_AKERSCORE"
        reasons.append("MISSING_AKERSCORE_SOIL_P50")
        support = "MISSING_AKERSCORE"
    elif reference_score is None:
        status = "OFFICIAL_SKO_ONLY_REFERENCE_UNAVAILABLE"
        reasons.append("LOCAL_CROP_SKO_REFERENCE_UNAVAILABLE")
        support = "REFERENCE_UNAVAILABLE"
    elif beta is None or float(beta) < 0:
        status = "UNAVAILABLE_MODEL_SUPPORT"
        reasons.append("INVALID_OR_MISSING_FROZEN_BETA")
    else:
        status = mode
        beta = float(beta)
        support = score_support_status(score, reference)
        adjustment = beta * (float(score) - reference_score)
        value = norm + adjustment
        if support in {"BELOW_OBSERVED_MIN", "ABOVE_OBSERVED_MAX"}:
            reasons.append("SCORE_OUTSIDE_OBSERVED_REFERENCE_RANGE")
        elif support != "WITHIN_P05_P95":
            reasons.append("SCORE_OUTSIDE_P05_P95")

    return {
        "schema_version": FIELD_SCHEMA_VERSION,
        "current_field_id": str(fget("current_field_id")),
        "municipality_code": str(fget("municipality_code") or fget("municipality_kod") or ""),
        "municipality": str(fget("municipality") or ""),
        "crop_code_canonical": int(pget("crop_code_canonical")),
        "crop_name": str(pget("crop_name") or (crop_config or {}).get("canonical_name") or ""),
        "history_year_count": int(pget("history_year_count") or 0),
        "history_component_year_count": int(pget("history_component_year_count") or 0),
        "history_years": str(pget("history_years") or "[]"),
        "history_quality": history_quality,
        "sko_id": sko_id,
        "sko_share": None if pd.isna(sko_share) else float(sko_share),
        "official_norm_year": int(config["official_norm_year"]),
        "official_sko_norm_t_ha": norm,
        "akerscore_value": None if pd.isna(score) else float(score),
        "sko_crop_reference_score": reference_score,
        "beta_t_ha_per_score": None if beta is None else float(beta),
        "adjustment_t_ha": adjustment,
        "field_akernorm_t_ha": value,
        "display_akernorm_t_ha": display_round(value, int(config["display"]["decimals"])),
        "model_status": status,
        "reason_flags": joined_flags(reasons),
        "score_support_status": support,
        "model_version": config["model_version"],
        "source_manifest_id": source_manifest_id,
    }


def build_history_presence(
    history: pd.DataFrame,
    grouped_components: pd.DataFrame | None,
    config: dict[str, Any],
) -> pd.DataFrame:
    required = {"current_field_id", "history_year", "dominant_crop_code_raw", "dominant_crop_name", "status"}
    missing = sorted(required - set(history.columns))
    if missing:
        raise RuntimeError(f"History presence input missing: {missing}")
    h = history.copy()
    h["current_field_id"] = h["current_field_id"].astype(str)
    h["history_year"] = pd.to_numeric(h["history_year"], errors="coerce").astype("Int64")
    h["crop_code_canonical"] = pd.to_numeric(h["dominant_crop_code_raw"], errors="coerce").astype("Int64")
    h = h[h["crop_code_canonical"].notna() & h["history_year"].notna()].copy()
    qualified_statuses = set(config["crop_presence"]["dominant_qualified_statuses"])
    low_statuses = set(config["crop_presence"]["low_coverage_statuses"])
    qualified = h[h["status"].isin(qualified_statuses)].copy()
    qualified["presence_kind"] = "DOMINANT"
    low = h[h["status"].isin(low_statuses)].copy()
    low["presence_kind"] = "LOW_COVERAGE"
    pieces = [qualified[["current_field_id", "history_year", "crop_code_canonical", "dominant_crop_name", "presence_kind"]],
              low[["current_field_id", "history_year", "crop_code_canonical", "dominant_crop_name", "presence_kind"]]]

    if grouped_components is not None:
        required_grouped = {"current_field_id", "history_year", "crop_code_raw", "crop_share_current"}
        missing_grouped = sorted(required_grouped - set(grouped_components.columns))
        if missing_grouped:
            raise RuntimeError(f"Grouped component input missing: {missing_grouped}")
        grouped = grouped_components.copy()
        grouped["current_field_id"] = grouped["current_field_id"].astype(str)
        grouped["history_year"] = pd.to_numeric(grouped["history_year"], errors="coerce").astype("Int64")
        grouped["crop_code_canonical"] = pd.to_numeric(grouped["crop_code_raw"], errors="coerce").astype("Int64")
        grouped["crop_share_current"] = pd.to_numeric(grouped["crop_share_current"], errors="coerce")
        statuses = h[["current_field_id", "history_year", "status"]].drop_duplicates()
        grouped = grouped.merge(statuses, on=["current_field_id", "history_year"], how="left", validate="many_to_one")
        grouped = grouped[
            grouped["status"].eq(config["crop_presence"]["mixed_component_status"])
            & grouped["crop_share_current"].ge(float(config["crop_presence"]["mixed_component_min_share"]))
            & grouped["crop_code_canonical"].notna()
        ].copy()
        dominant_keys = set(zip(qualified["current_field_id"], qualified["history_year"], qualified["crop_code_canonical"].astype(int)))
        grouped = grouped[
            ~grouped.apply(lambda row: (row["current_field_id"], row["history_year"], int(row["crop_code_canonical"])) in dominant_keys, axis=1)
        ]
        grouped["dominant_crop_name"] = ""
        grouped["presence_kind"] = "COMPONENT"
        pieces.append(grouped[["current_field_id", "history_year", "crop_code_canonical", "dominant_crop_name", "presence_kind"]])

    events = pd.concat(pieces, ignore_index=True)
    events["crop_code_canonical"] = events["crop_code_canonical"].astype(int)
    configured_names = {int(row["canonical_code"]): row["canonical_name"] for row in config["crops"]}
    rows: list[dict[str, Any]] = []
    for (field_id, code), group in events.groupby(["current_field_id", "crop_code_canonical"], sort=True):
        dominant_years = sorted(set(group.loc[group["presence_kind"].eq("DOMINANT"), "history_year"].astype(int)))
        component_years = sorted(set(group.loc[group["presence_kind"].eq("COMPONENT"), "history_year"].astype(int)))
        low_years = sorted(set(group.loc[group["presence_kind"].eq("LOW_COVERAGE"), "history_year"].astype(int)))
        qualified_years = sorted(set(dominant_years + component_years))
        if not dominant_years and component_years:
            quality = "HISTORY_COMPONENT_ONLY"
        elif not qualified_years and low_years:
            quality = "HISTORY_LOW_COVERAGE"
        else:
            quality = "STANDARD"
        names = [str(v).strip() for v in group["dominant_crop_name"] if str(v).strip() and str(v) != "nan"]
        rows.append({
            "current_field_id": str(field_id),
            "crop_code_canonical": int(code),
            "crop_name": configured_names.get(int(code), sorted(names)[0] if names else f"Grödkod {code}"),
            "history_year_count": len(qualified_years),
            "history_component_year_count": len(component_years),
            "history_low_coverage_year_count": len(low_years),
            "history_years": json.dumps(qualified_years if qualified_years else low_years, separators=(",", ":")),
            "history_quality": quality,
        })
    return pd.DataFrame(rows).sort_values(["current_field_id", "crop_code_canonical"], kind="mergesort").reset_index(drop=True)


def artifact_records(root: Path, relative_paths: Iterable[Path | str]) -> list[dict[str, Any]]:
    records = []
    for relative in sorted((Path(value) for value in relative_paths), key=lambda p: p.as_posix()):
        path = root / relative
        records.append({
            "path": relative.as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    return records
