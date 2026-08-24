#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run a deliberately bounded ÅkerDrift route validation pilot.

Default command:
  py -3 src\45_akerdrift_route_pilot.py run --kommun Lomma --limit 200

The command never runs a whole municipality by accident: limits above 200 are
rejected.  Each completed field has its own atomic result and checkpoint.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from akerdrift_route_core import (
    ENGINE_VERSION,
    MODEL_VERSION,
    config_hash,
    is_small_or_narrow_field,
    load_route_config,
    simulate_route,
)
from common import MUN_CODES, load_config


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROUTE_CONFIG = ROOT / "config" / "akerdrift_route_pilot_v1a_rc1_1.json"
MAX_PILOT_FIELDS = 200


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def slug(value: Any) -> str:
    ascii_name = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_")


def text_id(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    result = str(value)
    return result[:-2] if result.endswith(".0") else result


def field_key(block_id: Any, skifte_id: Any) -> str:
    return f"{text_id(block_id)}|{text_id(skifte_id)}"


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return stable_hash(payload)


def write_json_atomic(value: Any, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, destination)


def write_csv_atomic(frame: pd.DataFrame, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    frame.to_csv(temporary, index=False, encoding="utf-8-sig")
    os.replace(temporary, destination)


def format_number(value: Any, digits: int = 1) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "null"
    return f"{number:.{digits}f}" if math_isfinite(number) else "null"


def math_isfinite(value: float) -> bool:
    # Kept tiny and local so the CLI does not need a heavyweight formatting
    # dependency merely to print nullable QA metrics.
    return bool(np.isfinite(value))


def _path_from_root(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def resolve_municipality(value: str) -> str:
    aliases = {slug(name): name for name in MUN_CODES}
    municipality = aliases.get(slug(value))
    if municipality is None:
        raise ValueError(f"Okänd skånsk kommun: {value}")
    return municipality


def resolve_paths(args: argparse.Namespace, local: dict[str, Any], municipality: str) -> dict[str, Path]:
    build_dir = _path_from_root(local.get("build_dir", "data/derived"))
    fast = Path(args.fast_results) if args.fast_results else (
        build_dir / "akerdrift_fast_v1" / "by_municipality" / f"{slug(municipality)}.parquet"
    )
    if not fast.is_absolute():
        fast = ROOT / fast
    output = Path(args.output_dir) if args.output_dir else (
        build_dir / "akerdrift_route_pilot_v1a_rc1_1" / f"{slug(municipality)}_{args.limit}"
    )
    if not output.is_absolute():
        output = ROOT / output
    return {
        "blocks": _path_from_root(local["blocks"]),
        "skiften": _path_from_root(local["skiften"]),
        "fast": fast,
        "output": output,
    }


def polygonal_repair(geometry: Any) -> Any | None:
    if geometry is None or geometry.is_empty:
        return None
    candidate = geometry
    if not candidate.is_valid:
        try:
            from shapely import make_valid
            candidate = make_valid(candidate)
        except (ImportError, AttributeError, ValueError):
            candidate = candidate.buffer(0)
    if candidate is None or candidate.is_empty:
        return None
    if candidate.geom_type not in {"Polygon", "MultiPolygon"}:
        from shapely.ops import unary_union
        pieces = [piece for piece in getattr(candidate, "geoms", []) if piece.geom_type in {"Polygon", "MultiPolygon"}]
        candidate = unary_union(pieces) if pieces else None
    if candidate is None or candidate.is_empty or not candidate.is_valid or candidate.area <= 0:
        return None
    return candidate


def hole_count(geometry: Any) -> int:
    if geometry.geom_type == "Polygon":
        return len(geometry.interiors)
    if geometry.geom_type == "MultiPolygon":
        return sum(len(part.interiors) for part in geometry.geoms)
    return 0


def load_candidates(paths: dict[str, Path], municipality: str, route_config: Any) -> Any:
    try:
        import geopandas as gpd
    except ImportError as exc:
        raise RuntimeError("Ruttpiloten kräver geopandas, shapely och pyarrow. Kör INSTALL_REQUIREMENTS.bat.") from exc
    for name in ("blocks", "skiften", "fast"):
        if not paths[name].exists():
            raise FileNotFoundError(f"Saknar {name}-input: {paths[name]}")
    blocks = gpd.read_file(paths["blocks"]).to_crs(3006)
    fields = gpd.read_file(paths["skiften"]).to_crs(3006)
    if "region_kod" not in blocks or "blockid" not in blocks:
        raise RuntimeError("Blockfilen saknar region_kod eller blockid")
    if "blockid" not in fields or "skiftesbeteckning" not in fields:
        raise RuntimeError("Skiftesfilen saknar blockid eller skiftesbeteckning")
    blocks["blockid"] = blocks["blockid"].map(text_id)
    fields["blockid"] = fields["blockid"].map(text_id)
    fields["skiftesbeteckning"] = fields["skiftesbeteckning"].map(text_id)
    code = MUN_CODES[municipality]
    municipality_blocks = set(blocks.loc[blocks["region_kod"].astype(str).str.startswith(code), "blockid"])
    fields = fields[fields["blockid"].isin(municipality_blocks)].copy()
    fields["field_key"] = [field_key(block, field) for block, field in zip(fields["blockid"], fields["skiftesbeteckning"])]

    fast = pd.read_parquet(paths["fast"])
    required = {"block_id", "skifte_id", "akerdrift_score", "geometry_score", "drift_terrain_factor"}
    missing = sorted(required - set(fast.columns))
    if missing:
        raise RuntimeError("Fast-resultatet saknar kolumner: " + ", ".join(missing))
    fast = fast.copy()
    fast["field_key"] = [field_key(block, field) for block, field in zip(fast["block_id"], fast["skifte_id"])]
    keep = [
        "field_key", "akerdrift_score", "geometry_score", "drift_terrain_factor",
        "drift_status", "rectangularity", "compactness", "erl",
    ]
    keep = [column for column in keep if column in fast.columns]
    joined = fields.merge(fast[keep], on="field_key", how="inner", validate="one_to_one")
    if joined.empty:
        raise RuntimeError(f"Inga gemensamma skiften mellan geometri och Fast-resultat för {municipality}")
    joined["geometry"] = joined["geometry"].map(polygonal_repair)
    joined = joined[joined["geometry"].notna()].copy()
    joined["area_ha_route"] = joined["geometry"].map(lambda item: float(item.area) / 10_000.0)
    joined["hole_count"] = joined["geometry"].map(hole_count)
    joined["pa_ratio_route"] = joined["geometry"].map(lambda item: float(item.length / item.area))
    joined["small_or_narrow_field"] = joined["geometry"].map(
        lambda item: is_small_or_narrow_field(item, route_config)
    )
    joined["stable_hash"] = joined["field_key"].map(stable_hash)
    joined["akerdrift_score"] = pd.to_numeric(joined["akerdrift_score"], errors="coerce")
    return joined.sort_values(["blockid", "skiftesbeteckning"]).reset_index(drop=True)


def _stratified_keys(frame: Any, count: int) -> list[str]:
    """Select deterministically across a 5x5 area/Fast-score rank grid."""
    if count <= 0 or frame.empty:
        return []
    pool = frame.copy()
    area_rank = pool["area_ha_route"].rank(method="first", pct=True)
    score_rank = pool["akerdrift_score"].rank(method="first", pct=True)
    pool["sample_stratum"] = (
        np.minimum(4, np.floor(area_rank * 5).astype(int)).astype(str) + "x" +
        np.minimum(4, np.floor(score_rank * 5).astype(int)).astype(str)
    )
    groups = [part.sort_values("stable_hash") for _, part in pool.groupby("sample_stratum", sort=True)]
    offsets = [0] * len(groups)
    selected: list[str] = []
    while len(selected) < count:
        added = False
        for group_index, group in enumerate(groups):
            if offsets[group_index] >= len(group):
                continue
            row = group.iloc[offsets[group_index]]
            offsets[group_index] += 1
            selected.append(str(row["field_key"]))
            added = True
            if len(selected) >= count:
                break
        if not added:
            break
    return selected


def select_pilot(candidates: Any, limit: int) -> Any:
    if not 1 <= limit <= MAX_PILOT_FIELDS:
        raise ValueError(f"--limit måste ligga mellan 1 och {MAX_PILOT_FIELDS}")
    valid = candidates[candidates["akerdrift_score"].notna()].copy()
    if len(valid) < limit:
        raise RuntimeError(f"Endast {len(valid)} skiften har Fast-score; kan inte välja {limit}")

    stress_target = min(limit, max(1, (limit + 3) // 4))
    normal_target = limit - stress_target
    normal_pool = valid[~valid["small_or_narrow_field"].astype(bool)].copy()
    if len(normal_pool) < normal_target:
        raise RuntimeError(
            f"Endast {len(normal_pool)} normala skiften har en fungerande 24-meterskärna; "
            f"kan inte välja {normal_target}"
        )

    stress: dict[str, str] = {}

    def add_stress(frame: Any, count: int, reason: str) -> None:
        for row in frame.itertuples(index=False):
            if len(stress) >= stress_target or count <= 0:
                break
            if row.field_key not in stress:
                stress[row.field_key] = reason
                count -= 1

    small_target = min(stress_target, max(1, stress_target // 2))
    holes_target = min(stress_target - len(stress), max(1, (stress_target * 3) // 10))
    small = valid[valid["small_or_narrow_field"].astype(bool)].sort_values(
        ["area_ha_route", "stable_hash"]
    )
    add_stress(small, small_target, "litet/smalt: tom 24 m-kärna")
    holes = valid[(valid["hole_count"] > 0) & ~valid["small_or_narrow_field"].astype(bool)].sort_values(
        ["hole_count", "pa_ratio_route", "stable_hash"], ascending=[False, False, True]
    )
    add_stress(holes, holes_target, "hål/fragment")
    complex_boundary = valid[
        ~valid["small_or_narrow_field"].astype(bool) & valid["hole_count"].eq(0)
    ].sort_values(["pa_ratio_route", "stable_hash"], ascending=[False, True])
    add_stress(
        complex_boundary,
        stress_target - len(stress),
        "komplex gräns",
    )
    add_stress(valid.sort_values(["akerdrift_score", "stable_hash"]), stress_target - len(stress), "låg Fast-score")
    add_stress(
        valid.sort_values(["akerdrift_score", "stable_hash"], ascending=[False, True]),
        stress_target - len(stress),
        "hög Fast-score",
    )
    add_stress(valid.sort_values("stable_hash"), stress_target - len(stress), "stressreserv")

    normal_candidates = normal_pool[~normal_pool["field_key"].isin(stress)].copy()
    normal_keys = _stratified_keys(normal_candidates, normal_target)
    if len(normal_keys) != normal_target or len(stress) != stress_target:
        raise RuntimeError(
            f"Urvalet kunde inte fyllas: {len(normal_keys)} normalfält och {len(stress)} stressfält"
        )
    selected_order = normal_keys + list(stress)
    reasons = {key: "normal: area/score-stratum" for key in normal_keys}
    reasons.update(stress)
    cohorts = {key: "normal" for key in normal_keys}
    cohorts.update({key: "stress" for key in stress})
    pilot = valid[valid["field_key"].isin(selected_order)].copy()
    pilot["selection_reason"] = pilot["field_key"].map(reasons)
    pilot["validation_cohort"] = pilot["field_key"].map(cohorts)
    pilot["selection_order"] = pilot["field_key"].map(
        {key: index + 1 for index, key in enumerate(selected_order)}
    )
    return pilot.sort_values("selection_order").reset_index(drop=True)


def result_paths(output: Path, key: str) -> tuple[Path, Path]:
    token = f"{slug(key)}_{stable_hash(key)[:10]}"
    return output / "results" / f"{token}.json", output / "checkpoints" / f"{token}.done.json"


def field_fingerprint(row: Any, route_config_hash: str) -> str:
    payload = {
        "field_key": row.field_key,
        "geometry_wkb_sha256": stable_hash(row.geometry.wkb_hex),
        "fast_score": None if pd.isna(row.akerdrift_score) else float(row.akerdrift_score),
        "terrain_factor": None if pd.isna(row.drift_terrain_factor) else float(row.drift_terrain_factor),
        "validation_cohort": row.validation_cohort,
        "small_or_narrow_field": bool(row.small_or_narrow_field),
        "route_config_hash": route_config_hash,
    }
    return json_hash(payload)


def valid_checkpoint(result_path: Path, checkpoint_path: Path, fingerprint: str) -> bool:
    if not result_path.exists() or not checkpoint_path.exists():
        return False
    try:
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        result = json.loads(result_path.read_text(encoding="utf-8"))
        return (
            checkpoint.get("field_fingerprint") == fingerprint
            and checkpoint.get("model_version") == MODEL_VERSION
            and result.get("route_model_version") == MODEL_VERSION
            and result.get("field_key") == checkpoint.get("field_key")
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def calculate_one(row: Any, route_config: Any, municipality: str) -> dict[str, Any]:
    route = simulate_route(row.geometry, route_config)
    terrain = float(row.drift_terrain_factor) if pd.notna(row.drift_terrain_factor) else None
    diagnostic_route_score = route["geometry_score"] * terrain if terrain is not None else None
    diagnostic_route_score = (
        min(100.0, max(0.0, diagnostic_route_score)) if diagnostic_route_score is not None else None
    )
    small_or_narrow = bool(route["small_or_narrow_field"])
    route_score = None if small_or_narrow else diagnostic_route_score
    fast_score = float(row.akerdrift_score) if pd.notna(row.akerdrift_score) else None
    if small_or_narrow:
        route_status = "SMALL_OR_NARROW_FIELD"
    elif route_score is None:
        route_status = "MISSING_FAST_TERRAIN_FACTOR"
    else:
        route_status = "OK"
    result = dict(route)
    result.update({
        "field_key": row.field_key,
        "kommun": municipality,
        "block_id": text_id(row.blockid),
        "skifte_id": text_id(row.skiftesbeteckning),
        "route_status": route_status,
        "route_score": route_score,
        "route_score_diagnostic": diagnostic_route_score,
        "fast_score": fast_score,
        "fast_geometry_score": float(row.geometry_score) if pd.notna(row.geometry_score) else None,
        "fast_terrain_factor": terrain,
        "score_difference_route_minus_fast": route_score - fast_score if route_score is not None and fast_score is not None else None,
        "route_overhead_pct": 100.0 * (route["equivalent_time_s"] / route["ideal_time_s"] - 1.0),
        "perimeter_m": float(row.geometry.length),
        "hole_count": int(row.hole_count),
        "selection_reason": row.selection_reason,
        "validation_cohort": row.validation_cohort,
        "selection_order": int(row.selection_order),
    })
    return result


def merge_results(pilot: Any, output: Path, route_config_hash: str) -> pd.DataFrame:
    rows = []
    missing = []
    for row in pilot.itertuples(index=False):
        result_path, checkpoint_path = result_paths(output, row.field_key)
        fingerprint = field_fingerprint(row, route_config_hash)
        if valid_checkpoint(result_path, checkpoint_path, fingerprint):
            rows.append(json.loads(result_path.read_text(encoding="utf-8")))
        else:
            missing.append(row.field_key)
    if missing:
        print(f"OBS: {len(missing)} valda skiften saknar ännu resultat.")
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values("selection_order").reset_index(drop=True)
        temporary = output / "route_pilot_results.tmp.parquet"
        destination = output / "route_pilot_results.parquet"
        frame.to_parquet(temporary, index=False)
        os.replace(temporary, destination)
    return frame


def build_report(frame: pd.DataFrame, output: Path) -> dict[str, Any]:
    if frame.empty:
        raise RuntimeError("Inga ruttresultat att rapportera")
    route = pd.to_numeric(frame["route_score"], errors="coerce")
    fast = pd.to_numeric(frame["fast_score"], errors="coerce")
    main_mask = (
        frame["validation_cohort"].eq("normal")
        & frame["route_status"].eq("OK")
        & route.notna()
        & fast.notna()
    )
    paired = frame.loc[main_mask].copy()
    paired["absolute_score_difference"] = (
        pd.to_numeric(paired["route_score"], errors="coerce")
        - pd.to_numeric(paired["fast_score"], errors="coerce")
    ).abs()
    paired["fast_rank"] = paired["fast_score"].rank(method="min", ascending=False)
    paired["route_rank"] = paired["route_score"].rank(method="min", ascending=False)
    paired["rank_change_route_minus_fast"] = paired["route_rank"] - paired["fast_rank"]
    paired["absolute_rank_change"] = paired["rank_change_route_minus_fast"].abs()
    write_csv_atomic(
        paired.sort_values(["absolute_rank_change", "absolute_score_difference"], ascending=False),
        output / "qa" / "largest_disagreements.csv",
    )
    paired["turns_per_ha"] = paired["turn_count"] / paired["area_ha"]
    by_holes = paired.assign(has_holes=paired["hole_count"] > 0).groupby("has_holes", dropna=False).agg(
        n=("field_key", "size"),
        area_ha_median=("area_ha", "median"),
        fast_median=("fast_score", "median"),
        route_median=("route_score", "median"),
        median_difference=("score_difference_route_minus_fast", "median"),
        median_absolute_difference=("absolute_score_difference", "median"),
        median_turns=("turn_count", "median"),
        median_turns_per_ha=("turns_per_ha", "median"),
    ).reset_index()
    write_csv_atomic(by_holes, output / "qa" / "holes_comparison.csv")

    stress = frame[frame["validation_cohort"].eq("stress")].copy()
    write_csv_atomic(stress, output / "qa" / "stress_fields.csv")
    small_or_narrow = frame[frame["route_status"].eq("SMALL_OR_NARROW_FIELD")].copy()
    write_csv_atomic(small_or_narrow, output / "qa" / "small_or_narrow_fields.csv")
    if stress.empty:
        stress_summary = pd.DataFrame(columns=[
            "route_status", "n", "fast_median", "diagnostic_route_median",
        ])
    else:
        stress_summary = stress.groupby("route_status", dropna=False).agg(
            n=("field_key", "size"),
            fast_median=("fast_score", "median"),
            diagnostic_route_median=("route_score_diagnostic", "median"),
        ).reset_index()
    write_csv_atomic(stress_summary, output / "qa" / "stress_summary.csv")

    difference = paired["absolute_score_difference"]
    paired_route = pd.to_numeric(paired["route_score"], errors="coerce")
    summary = {
        "model_version": MODEL_VERSION,
        "route_engine": ENGINE_VERSION,
        "n_selected": int(len(frame)),
        "n_normal_selected": int(frame["validation_cohort"].eq("normal").sum()),
        "n_stress_selected": int(frame["validation_cohort"].eq("stress").sum()),
        "n_main_compared": int(len(paired)),
        "n_stress_scored": int(pd.to_numeric(stress["route_score"], errors="coerce").notna().sum()),
        "n_small_or_narrow": int(len(small_or_narrow)),
        "main_spearman_route_vs_fast": float(
            paired["route_score"].corr(paired["fast_score"], method="spearman")
        ) if len(paired) >= 2 else None,
        "main_median_absolute_score_difference": float(difference.median()) if len(difference) else None,
        "main_p95_absolute_score_difference": float(difference.quantile(.95)) if len(difference) else None,
        "main_route_score_min": float(paired_route.min()) if len(paired) else None,
        "main_route_score_median": float(paired_route.median()) if len(paired) else None,
        "main_route_score_max": float(paired_route.max()) if len(paired) else None,
        "completed_utc": utc_now(),
    }
    write_json_atomic(summary, output / "qa" / "comparison_summary.json")
    return summary


def manifest_frame(pilot: Any) -> pd.DataFrame:
    columns = [
        "selection_order", "validation_cohort", "selection_reason", "field_key", "blockid", "skiftesbeteckning",
        "area_ha_route", "hole_count", "pa_ratio_route", "small_or_narrow_field",
        "akerdrift_score", "geometry_score",
        "drift_terrain_factor", "rectangularity", "compactness", "erl",
    ]
    return pd.DataFrame(pilot.drop(columns="geometry", errors="ignore"))[[column for column in columns if column in pilot.columns]]


def run_command(args: argparse.Namespace) -> int:
    if not 1 <= args.limit <= MAX_PILOT_FIELDS:
        raise ValueError(f"--limit måste ligga mellan 1 och {MAX_PILOT_FIELDS}; detta är avsiktligt bara en pilot")
    municipality = resolve_municipality(args.kommun)
    local = load_config(_path_from_root(args.config))
    raw_route_config, route_config = load_route_config(_path_from_root(args.route_config))
    route_config_hash = config_hash(raw_route_config)
    paths = resolve_paths(args, local, municipality)
    paths["output"].mkdir(parents=True, exist_ok=True)
    candidates = load_candidates(paths, municipality, route_config)
    pilot = select_pilot(candidates, args.limit)
    write_csv_atomic(manifest_frame(pilot), paths["output"] / "sample_manifest.csv")
    write_json_atomic({
        "model_version": MODEL_VERSION,
        "route_engine": ENGINE_VERSION,
        "route_config_hash": route_config_hash,
        "kommun": municipality,
        "limit": args.limit,
        "candidate_count": int(len(candidates)),
        "normal_selected": int(pilot["validation_cohort"].eq("normal").sum()),
        "stress_selected": int(pilot["validation_cohort"].eq("stress").sum()),
        "small_or_narrow_selected": int(pilot["small_or_narrow_field"].sum()),
        "selected_field_keys": list(pilot["field_key"]),
        "created_utc": utc_now(),
    }, paths["output"] / "sample_manifest.json")
    print(
        f"URVAL {municipality}: {len(pilot)} av {len(candidates):,} skiften · "
        f"normal {pilot['validation_cohort'].eq('normal').sum()} · "
        f"stress {pilot['validation_cohort'].eq('stress').sum()} · "
        f"små/smala {pilot['small_or_narrow_field'].sum()} · "
        f"hålskiften {(pilot['hole_count'] > 0).sum()} · {paths['output']}"
    )
    if args.sample_only:
        return 0

    completed = skipped = 0
    failure_columns = ["field_key", "block_id", "skifte_id", "error_type", "error"]
    failures: list[dict[str, Any]] = []
    started = time.perf_counter()
    for index, row in enumerate(pilot.itertuples(index=False), 1):
        result_path, checkpoint_path = result_paths(paths["output"], row.field_key)
        fingerprint = field_fingerprint(row, route_config_hash)
        if args.resume and not args.force and valid_checkpoint(result_path, checkpoint_path, fingerprint):
            skipped += 1
            print(f"SKIP {index:02d}/{len(pilot)} {row.field_key}")
            continue
        field_started = time.perf_counter()
        try:
            result = calculate_one(row, route_config, municipality)
            write_json_atomic(result, result_path)
            write_json_atomic({
                "model_version": MODEL_VERSION,
                "field_key": row.field_key,
                "field_fingerprint": fingerprint,
                "runtime_seconds": round(time.perf_counter() - field_started, 3),
                "completed_utc": utc_now(),
            }, checkpoint_path)
            completed += 1
            print(
                f"DONE {index:02d}/{len(pilot)} {row.field_key} · "
                f"Fast {format_number(result['fast_score'])} → rutt {format_number(result['route_score'])} · "
                f"{result['turn_count']} vändningar · {result['route_status']} · "
                f"{time.perf_counter() - field_started:.1f} s"
            )
        except Exception as exc:  # one field must never destroy the pilot
            failures.append({
                "field_key": row.field_key,
                "block_id": text_id(row.blockid),
                "skifte_id": text_id(row.skiftesbeteckning),
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
            print(f"FEL  {index:02d}/{len(pilot)} {row.field_key}: {type(exc).__name__}: {exc}")
        write_csv_atomic(pd.DataFrame(failures, columns=failure_columns), paths["output"] / "failures.csv")

    frame = merge_results(pilot, paths["output"], route_config_hash)
    summary = build_report(frame, paths["output"])
    print(
        f"KLART: {completed} beräknade · {skipped} checkpoints · {len(failures)} fel · "
        f"{time.perf_counter() - started:.1f} s"
    )
    print(
        f"JÄMFÖRELSE NORMAL (n={summary['n_main_compared']}): Spearman "
        f"{format_number(summary['main_spearman_route_vs_fast'], 3)} · median |Δ| "
        f"{format_number(summary['main_median_absolute_score_difference'], 2)} · P95 |Δ| "
        f"{format_number(summary['main_p95_absolute_score_difference'], 2)}"
    )
    print(
        f"STRESS (n={summary['n_stress_selected']}): {summary['n_stress_scored']} jämförbara · "
        f"{summary['n_small_or_narrow']} SMALL_OR_NARROW_FIELD"
    )
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="ÅkerDrift route pilot: högst 200 skiften")
    root.add_argument("command", choices=["run"], nargs="?", default="run")
    root.add_argument("--kommun", default="Lomma")
    root.add_argument("--limit", type=int, default=200)
    root.add_argument("--config", default="config/local_paths.json")
    root.add_argument("--route-config", default=str(DEFAULT_ROUTE_CONFIG.relative_to(ROOT)))
    root.add_argument("--fast-results")
    root.add_argument("--output-dir")
    root.add_argument("--sample-only", action="store_true", help="Skriv bara det deterministiska urvalet")
    root.add_argument("--resume", action="store_true", default=True)
    root.add_argument("--no-resume", action="store_false", dest="resume")
    root.add_argument("--force", action="store_true")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return run_command(args)
    except (FileNotFoundError, RuntimeError, ValueError, KeyError) as exc:
        print(f"FEL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
