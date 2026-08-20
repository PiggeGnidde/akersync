#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Restart-safe municipality runner for ÅkerDrift Fast MVP V1.

Commands:
  python src/44_akerdrift_fast_v1.py run --kommun Lomma
  python src/44_akerdrift_fast_v1.py run --all --resume
  python src/44_akerdrift_fast_v1.py merge
  python src/44_akerdrift_fast_v1.py qa
  python src/44_akerdrift_fast_v1.py sensitivity

The route/Fields2Cover implementation is intentionally not imported here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
import unicodedata
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from akerdrift_fast_core import config_hash, load_model_config, score_field
from common import MUN_CODES, load_config


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_CONFIG = ROOT / "config" / "akerdrift_fast_v1_rc0.json"
OUTPUT_COLUMNS = [
    "skifte_id", "block_id", "kommun", "area_ha", "area_m2", "perimeter_m",
    "akerdrift_score", "drift_model_version", "drift_status",
    "pa_ratio", "fe_geom_raw", "fe_geom", "geometry_score",
    "drift_slope_difficulty", "drift_terrain_factor",
    "drift_slope_mean_deg", "drift_slope_p90_deg", "drift_slope_p95_deg",
    "drift_slope_gt5_share", "drift_slope_gt10_share", "drift_slope_gt16_7_share",
    "drift_slope_coverage", "drift_twi_mean", "drift_twi_p90_share",
    "drift_twi_p95_share", "drift_twi_coverage", "drift_twi_status",
    "rectangularity", "convexity", "compactness", "mbr_aspect", "erl",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def slug(value: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_")


def text_id(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    result = str(value)
    return result[:-2] if result.endswith(".0") else result


def field_key(block_id: Any, skifte_id: Any) -> str:
    return f"{text_id(block_id)}|{text_id(skifte_id)}"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_signature(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    item = Path(path)
    if not item.exists():
        return {"path": str(item.resolve()), "missing": True}
    stat = item.stat()
    return {
        "path": str(item.resolve()),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def resolve_model_paths(args: argparse.Namespace, local: dict[str, Any]) -> dict[str, Path | None]:
    work = Path(local.get("whitebox_work_dir", "")) if local.get("whitebox_work_dir") else None
    slope = args.slope_raster or local.get("akerdrift_slope_raster")
    twi = args.twi_raster or local.get("akerdrift_twi_raster")
    if not slope and work:
        slope = work / "slope_10m_deg.tif"
    if not twi and work:
        twi = work / "twi_10m.tif"
    build_dir = Path(local.get("build_dir", "data/derived"))
    if not build_dir.is_absolute():
        build_dir = ROOT / build_dir
    output = Path(args.output_dir) if args.output_dir else build_dir / "akerdrift_fast_v1"
    if not output.is_absolute():
        output = ROOT / output
    geometry_csv = build_dir / "geometry_v1a_skiften.csv"
    return {
        "blocks": Path(local["blocks"]),
        "skiften": Path(local["skiften"]),
        "slope": Path(slope) if slope else None,
        "twi": Path(twi) if twi else None,
        "geometry_csv": geometry_csv if geometry_csv.exists() else None,
        "output": output,
    }


def resolve_municipalities(values: Iterable[str] | None, run_all: bool) -> list[str]:
    if run_all:
        return list(MUN_CODES)
    requested: list[str] = []
    for value in values or []:
        requested.extend(part.strip() for part in value.split(",") if part.strip())
    if not requested:
        raise ValueError("Ange --kommun Lomma (kan upprepas) eller --all")
    aliases = {slug(name): name for name in MUN_CODES}
    result = []
    for value in requested:
        municipality = aliases.get(slug(value))
        if municipality is None:
            raise ValueError(f"Okänd skånsk kommun: {value}")
        if municipality not in result:
            result.append(municipality)
    return result


def output_paths(output_dir: Path, municipality: str) -> dict[str, Path]:
    name = slug(municipality)
    return {
        "parquet": output_dir / "by_municipality" / f"{name}.parquet",
        "checkpoint": output_dir / "checkpoints" / f"{name}.done.json",
        "failures": output_dir / "failures" / f"{name}.csv",
    }


def write_json_atomic(value: Any, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, destination)


def validate_parquet(path: Path, municipality: str, model_version: str, expected_rows: int | None = None) -> pd.DataFrame:
    try:
        frame = pd.read_parquet(path)
    except ImportError as exc:
        raise RuntimeError("Parquet kräver pyarrow. Kör INSTALL_REQUIREMENTS.bat.") from exc
    missing = [column for column in OUTPUT_COLUMNS if column not in frame.columns]
    if missing:
        raise RuntimeError(f"{path} saknar kolumner: {', '.join(missing)}")
    if expected_rows is not None and len(frame) != expected_rows:
        raise RuntimeError(f"{path}: {len(frame)} rader, förväntade {expected_rows}")
    if len(frame) and set(frame["kommun"].dropna().astype(str)) != {municipality}:
        raise RuntimeError(f"{path}: innehåller fel kommun")
    if len(frame) and set(frame["drift_model_version"].dropna().astype(str)) != {model_version}:
        raise RuntimeError(f"{path}: innehåller fel modellversion")
    if frame.duplicated(["block_id", "skifte_id"]).any():
        raise RuntimeError(f"{path}: dubbla skiftesnycklar")
    score = pd.to_numeric(frame["akerdrift_score"], errors="coerce").dropna()
    if len(score) and not score.between(0, 100).all():
        raise RuntimeError(f"{path}: score utanför 0–100")
    return frame


def checkpoint_valid(
    paths: dict[str, Path], municipality: str, model_version: str,
    cfg_hash: str, input_fingerprint: str,
) -> bool:
    if not paths["parquet"].exists() or not paths["checkpoint"].exists():
        return False
    try:
        done = json.loads(paths["checkpoint"].read_text(encoding="utf-8"))
        expected = {
            "model_version": model_version,
            "kommun": municipality,
            "config_hash": cfg_hash,
            "input_fingerprint": input_fingerprint,
        }
        if any(done.get(key) != value for key, value in expected.items()):
            return False
        validate_parquet(paths["parquet"], municipality, model_version, int(done["n_input"]))
        return True
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError):
        return False


def _polygonal_repair(geometry: Any) -> Any | None:
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
        polygons = [part for part in getattr(candidate, "geoms", []) if part.geom_type in {"Polygon", "MultiPolygon"}]
        if not polygons:
            return None
        from shapely.ops import unary_union
        candidate = unary_union(polygons)
    if candidate.is_empty or not candidate.is_valid or candidate.area <= 0 or candidate.length <= 0:
        return None
    return candidate


def _geometry_for_dataset(geometry: Any, source_crs: Any, target_crs: Any) -> Any:
    if not target_crs or str(source_crs) == str(target_crs):
        return geometry
    from pyproj import Transformer
    from shapely.ops import transform
    transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    return transform(transformer.transform, geometry)


def zonal_values(dataset: Any | None, geometry: Any, geometry_crs: Any) -> tuple[np.ndarray, float]:
    """Pixel-centre zonal values and valid/inside coverage, matching repo convention."""
    if dataset is None:
        return np.asarray([], dtype=np.float64), 0.0
    from rasterio.features import geometry_mask
    from rasterio.mask import mask

    raster_geometry = _geometry_for_dataset(geometry, geometry_crs, dataset.crs)
    try:
        data, transform = mask(
            dataset, [raster_geometry.__geo_interface__], crop=True,
            all_touched=False, filled=False, indexes=1,
        )
    except ValueError:
        return np.asarray([], dtype=np.float64), 0.0
    if data.ndim == 3:
        data = data[0]
    inside = geometry_mask(
        [raster_geometry.__geo_interface__], out_shape=data.shape,
        transform=transform, invert=True, all_touched=False,
    )
    count_inside = int(inside.sum())
    if count_inside == 0:
        return np.asarray([], dtype=np.float64), 0.0
    raw = np.asarray(np.ma.getdata(data), dtype=np.float64)
    data_mask = np.ma.getmaskarray(data)
    valid = inside & ~data_mask & np.isfinite(raw)
    values = raw[valid]
    return values, min(1.0, max(0.0, float(valid.sum()) / count_inside))


def geometry_explanatory_lookup(path: Path | None) -> tuple[dict[str, dict[str, Any]], list[str]]:
    target = ["rectangularity", "convexity", "compactness_4piA_P2", "mbr_aspect_ratio", "erl_proxy_m"]
    if path is None:
        return {}, target
    frame = pd.read_csv(path, encoding="utf-8-sig", dtype={"blockid": str, "skiftesbeteckning": str})
    available = [column for column in target if column in frame.columns]
    missing = [column for column in target if column not in frame.columns]
    lookup = {
        field_key(row.get("blockid"), row.get("skiftesbeteckning")): row.to_dict()
        for _, row in frame.iterrows()
    }
    return lookup, missing


def explanatory_values(row: dict[str, Any] | None) -> dict[str, float | None]:
    row = row or {}
    mapping = {
        "rectangularity": "rectangularity",
        "convexity": "convexity",
        "compactness": "compactness_4piA_P2",
        "mbr_aspect": "mbr_aspect_ratio",
        "erl": "erl_proxy_m",
    }
    result = {}
    for output, source in mapping.items():
        value = pd.to_numeric(row.get(source), errors="coerce")
        result[output] = float(value) if pd.notna(value) else None
    return result


def invalid_row(municipality: str, block_id: str, skifte_id: str, status: str, model_version: str) -> dict[str, Any]:
    row = {column: None for column in OUTPUT_COLUMNS}
    row.update({
        "kommun": municipality,
        "block_id": block_id,
        "skifte_id": skifte_id,
        "drift_status": status,
        "drift_model_version": model_version,
        "drift_twi_status": "MISSING",
        "drift_slope_coverage": 0.0,
        "drift_twi_coverage": 0.0,
    })
    return row


def calculate_municipality(
    fields: Any, municipality: str, slope_dataset: Any, twi_dataset: Any | None,
    model_config: dict[str, Any], explanatory: dict[str, dict[str, Any]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    total = len(fields)
    started = time.perf_counter()
    for index, field in enumerate(fields.itertuples(index=False), 1):
        block_id = text_id(getattr(field, "blockid", ""))
        skifte_id = text_id(getattr(field, "skiftesbeteckning", ""))
        key = field_key(block_id, skifte_id)
        try:
            geometry = _polygonal_repair(field.geometry)
            if geometry is None:
                row = invalid_row(municipality, block_id, skifte_id, "INVALID_GEOMETRY", model_config["model_version"])
            else:
                slope, slope_coverage = zonal_values(slope_dataset, geometry, fields.crs)
                twi, twi_coverage = zonal_values(twi_dataset, geometry, fields.crs)
                row = score_field(
                    area_m2=float(geometry.area), perimeter_m=float(geometry.length),
                    slope_values_deg=slope, slope_coverage=slope_coverage,
                    twi_values=twi, twi_coverage=twi_coverage, config=model_config,
                )
                row.update({
                    "kommun": municipality,
                    "block_id": block_id,
                    "skifte_id": skifte_id,
                    "area_ha": float(geometry.area) / 10_000.0,
                })
            row.update(explanatory_values(explanatory.get(key)))
        except Exception as exc:  # field failure must not abort the municipality
            row = invalid_row(municipality, block_id, skifte_id, "FIELD_ERROR", model_config["model_version"])
            row.update(explanatory_values(explanatory.get(key)))
            failures.append({
                "kommun": municipality, "block_id": block_id, "skifte_id": skifte_id,
                "error_type": type(exc).__name__, "error": str(exc),
            })
        rows.append(row)
        if index == 1 or index % 500 == 0 or index == total:
            elapsed = max(time.perf_counter() - started, 1e-9)
            print(f"\r  {municipality}: {index:,}/{total:,} skiften · {index/elapsed:.1f}/s", end="", flush=True)
    if total:
        print()
    frame = pd.DataFrame(rows).reindex(columns=OUTPUT_COLUMNS)
    failure_frame = pd.DataFrame(failures, columns=["kommun", "block_id", "skifte_id", "error_type", "error"])
    return frame, failure_frame


def prepare_inputs(paths: dict[str, Path | None]) -> tuple[Any, Any, dict[str, set[str]], dict[str, dict[str, Any]], list[str]]:
    try:
        import geopandas as gpd
    except ImportError as exc:
        raise RuntimeError("ÅkerDrift-körning kräver geopandas/rasterio/pyarrow. Kör INSTALL_REQUIREMENTS.bat.") from exc
    for label in ("blocks", "skiften", "slope"):
        path = paths[label]
        if path is None or not path.exists():
            raise FileNotFoundError(f"Saknar {label}-input: {path}")
    blocks = gpd.read_file(paths["blocks"])
    fields = gpd.read_file(paths["skiften"])
    if blocks.crs is None or fields.crs is None:
        raise RuntimeError("Block/skifte saknar CRS")
    blocks = blocks.to_crs(3006)
    fields = fields.to_crs(3006)
    blocks["blockid"] = blocks["blockid"].map(text_id)
    fields["blockid"] = fields["blockid"].map(text_id)
    fields["skiftesbeteckning"] = fields["skiftesbeteckning"].map(text_id)
    municipality_blocks: dict[str, set[str]] = {}
    region = blocks["region_kod"].astype(str)
    for municipality, code in MUN_CODES.items():
        municipality_blocks[municipality] = set(blocks.loc[region.str.startswith(code), "blockid"])
    explanatory, missing = geometry_explanatory_lookup(paths["geometry_csv"])
    return blocks, fields, municipality_blocks, explanatory, missing


def municipality_fingerprint(
    municipality: str, fields: Any, paths: dict[str, Path | None], field_ids: list[str],
) -> str:
    return sha256_json({
        "municipality": municipality,
        "n_fields": len(fields),
        "field_ids_hash": sha256_json(sorted(field_ids)),
        "inputs": {name: file_signature(paths.get(name)) for name in ("blocks", "skiften", "slope", "twi", "geometry_csv")},
    })


def atomic_write_municipality(
    frame: pd.DataFrame, failures: pd.DataFrame, paths: dict[str, Path],
    municipality: str, model_version: str,
) -> None:
    paths["parquet"].parent.mkdir(parents=True, exist_ok=True)
    paths["failures"].parent.mkdir(parents=True, exist_ok=True)
    temp_parquet = paths["parquet"].with_suffix(".tmp.parquet")
    try:
        frame.to_parquet(temp_parquet, index=False)
    except ImportError as exc:
        raise RuntimeError("Parquet kräver pyarrow. Kör INSTALL_REQUIREMENTS.bat.") from exc
    validate_parquet(temp_parquet, municipality, model_version, len(frame))
    os.replace(temp_parquet, paths["parquet"])
    temp_failures = paths["failures"].with_suffix(".tmp.csv")
    failures.to_csv(temp_failures, index=False, encoding="utf-8-sig")
    os.replace(temp_failures, paths["failures"])


def run_command(args: argparse.Namespace) -> int:
    local = load_config(ROOT / args.config)
    model = load_model_config(ROOT / args.model_config)
    cfg_hash = config_hash(model)
    paths = resolve_model_paths(args, local)
    municipalities = resolve_municipalities(args.kommun, args.all)
    _, fields, municipality_blocks, explanatory, missing_explanatory = prepare_inputs(paths)
    if missing_explanatory:
        print("OBS: förklarande Geometry V1a-kolumner saknas men körningen fortsätter: " + ", ".join(missing_explanatory))
    if paths["twi"] is None or not paths["twi"].exists():
        print(f"OBS: TWI saknas ({paths['twi']}); diagnostik blir MISSING men huvudscore beräknas.")

    import rasterio
    completed = skipped = 0
    with ExitStack() as stack:
        slope_dataset = stack.enter_context(rasterio.open(paths["slope"]))
        twi_dataset = stack.enter_context(rasterio.open(paths["twi"])) if paths["twi"] and paths["twi"].exists() else None
        for municipality in municipalities:
            selected = fields[fields["blockid"].isin(municipality_blocks[municipality])].copy()
            selected = selected.sort_values(["blockid", "skiftesbeteckning"]).reset_index(drop=True)
            ids = [field_key(row.blockid, row.skiftesbeteckning) for row in selected.itertuples(index=False)]
            fingerprint = municipality_fingerprint(municipality, selected, paths, ids)
            out = output_paths(paths["output"], municipality)
            if args.resume and not args.force and checkpoint_valid(
                out, municipality, model["model_version"], cfg_hash, fingerprint,
            ):
                skipped += 1
                print(f"SKIP {municipality}: valid checkpoint")
                continue
            print(f"RUN  {municipality}: {len(selected):,} skiften")
            started = time.perf_counter()
            result, failures = calculate_municipality(
                selected, municipality, slope_dataset, twi_dataset, model, explanatory,
            )
            atomic_write_municipality(result, failures, out, municipality, model["model_version"])
            score = pd.to_numeric(result["akerdrift_score"], errors="coerce")
            done = {
                "model_version": model["model_version"],
                "kommun": municipality,
                "n_input": int(len(result)),
                "n_scored": int(score.notna().sum()),
                "n_null": int(score.isna().sum()),
                "n_failed": int(len(failures)),
                "config_hash": cfg_hash,
                "input_fingerprint": fingerprint,
                "score_min": float(score.min()) if score.notna().any() else None,
                "score_median": float(score.median()) if score.notna().any() else None,
                "score_max": float(score.max()) if score.notna().any() else None,
                "runtime_seconds": round(time.perf_counter() - started, 3),
                "completed_utc": utc_now(),
            }
            write_json_atomic(done, out["checkpoint"])
            completed += 1
            print(
                f"DONE {municipality}: score {done['n_scored']:,}/{done['n_input']:,} · "
                f"null {done['n_null']:,} · fel {done['n_failed']:,} · {done['runtime_seconds']:.1f} s"
            )
    print(f"Körning klar: {completed} beräknade · {skipped} återanvända checkpoints")
    if args.all:
        merge_outputs(paths["output"], list(MUN_CODES), model, cfg_hash, allow_partial=False)
    return 0


def merge_outputs(
    output_dir: Path, municipalities: list[str], model: dict[str, Any],
    cfg_hash: str, allow_partial: bool,
) -> Path:
    frames = []
    checkpoints = []
    missing = []
    for municipality in municipalities:
        paths = output_paths(output_dir, municipality)
        if not paths["parquet"].exists() or not paths["checkpoint"].exists():
            missing.append(municipality)
            continue
        done = json.loads(paths["checkpoint"].read_text(encoding="utf-8"))
        if done.get("model_version") != model["model_version"] or done.get("config_hash") != cfg_hash:
            raise RuntimeError(f"{municipality}: checkpoint matchar inte modell/config")
        frames.append(validate_parquet(paths["parquet"], municipality, model["model_version"], int(done["n_input"])))
        checkpoints.append(done)
    if missing and not allow_partial:
        raise RuntimeError("Kan inte bygga Skånefil; checkpoints saknas för: " + ", ".join(missing))
    if not frames:
        raise RuntimeError("Inga färdiga kommunfiler att slå ihop")
    merged = pd.concat(frames, ignore_index=True).sort_values(["kommun", "block_id", "skifte_id"]).reset_index(drop=True)
    destination = output_dir / "akerdrift_fast_v1_skane.parquet"
    temp = destination.with_suffix(".tmp.parquet")
    output_dir.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(temp, index=False)
    check = pd.read_parquet(temp)
    if len(check) != len(merged) or check.duplicated(["block_id", "skifte_id"]).any():
        raise RuntimeError("Global parquet validerades inte")
    os.replace(temp, destination)
    manifest = {
        "model_version": model["model_version"],
        "config_hash": cfg_hash,
        "municipality_count": len(frames),
        "municipalities": [done["kommun"] for done in checkpoints],
        "n_input": int(sum(done["n_input"] for done in checkpoints)),
        "n_scored": int(sum(done["n_scored"] for done in checkpoints)),
        "n_null": int(sum(done["n_null"] for done in checkpoints)),
        "n_failed": int(sum(done["n_failed"] for done in checkpoints)),
        "source_checkpoints": checkpoints,
        "merged_utc": utc_now(),
    }
    write_json_atomic(manifest, output_dir / "run_manifest.json")
    print(f"MERGE: {len(frames)} kommuner · {len(merged):,} skiften · {destination}")
    return destination


def merge_command(args: argparse.Namespace) -> int:
    local = load_config(ROOT / args.config)
    model = load_model_config(ROOT / args.model_config)
    paths = resolve_model_paths(args, local)
    merge_outputs(paths["output"], list(MUN_CODES), model, config_hash(model), args.allow_partial)
    return 0


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce")


def qa_command(args: argparse.Namespace) -> int:
    local = load_config(ROOT / args.config)
    model = load_model_config(ROOT / args.model_config)
    paths = resolve_model_paths(args, local)
    source = paths["output"] / "akerdrift_fast_v1_skane.parquet"
    if not source.exists():
        raise FileNotFoundError(f"Saknar {source}. Kör merge först.")
    frame = pd.read_parquet(source)
    score = _numeric(frame, "akerdrift_score")
    qa_dir = paths["output"] / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    probabilities = [.01, .05, .10, .25, .50, .75, .90, .95, .99]
    percentiles = pd.DataFrame({
        "percentile": [f"P{int(p*100)}" for p in probabilities],
        "akerdrift_score": [float(score.quantile(p)) for p in probabilities],
    })
    percentiles.to_csv(qa_dir / "score_percentiles.csv", index=False, encoding="utf-8-sig")
    municipality_rows = []
    for municipality, part in frame.groupby("kommun", sort=True):
        values = _numeric(part, "akerdrift_score").dropna()
        municipality_rows.append({
            "kommun": municipality, "n": len(part), "n_scored": len(values),
            "median": float(values.median()) if len(values) else None,
            "p10": float(values.quantile(.10)) if len(values) else None,
            "p90": float(values.quantile(.90)) if len(values) else None,
        })
    pd.DataFrame(municipality_rows).to_csv(qa_dir / "municipality_summary.csv", index=False, encoding="utf-8-sig")
    correlation_targets = [
        "area_ha", "pa_ratio", "rectangularity", "convexity", "compactness", "erl", "geometry_score",
    ]
    correlations = []
    for column in correlation_targets:
        if column in frame.columns:
            pair = pd.DataFrame({"score": score, "target": _numeric(frame, column)}).dropna()
            correlations.append({
                "variable": column, "n": len(pair),
                "spearman": float(pair["score"].corr(pair["target"], method="spearman")) if len(pair) >= 2 else None,
            })
    pd.DataFrame(correlations).to_csv(qa_dir / "spearman_correlations.csv", index=False, encoding="utf-8-sig")
    ranked = frame.copy()
    ranked["terrain_adjustment_points"] = _numeric(ranked, "geometry_score") - score
    ranked.nlargest(50, "terrain_adjustment_points").to_csv(qa_dir / "largest_terrain_adjustments.csv", index=False, encoding="utf-8-sig")
    ranked.nlargest(50, "akerdrift_score").to_csv(qa_dir / "highest_scores.csv", index=False, encoding="utf-8-sig")
    ranked.nsmallest(50, "akerdrift_score").to_csv(qa_dir / "lowest_scores.csv", index=False, encoding="utf-8-sig")
    summary = {
        "model_version": model["model_version"],
        "n_total": int(len(frame)), "n_scored": int(score.notna().sum()), "n_null": int(score.isna().sum()),
        "score_min": float(score.min()) if score.notna().any() else None,
        "score_max": float(score.max()) if score.notna().any() else None,
        "score_percentiles": dict(zip(percentiles["percentile"], percentiles["akerdrift_score"])),
        "qa_completed_utc": utc_now(),
    }
    write_json_atomic(summary, qa_dir / "qa_summary.json")
    print(f"QA: {len(frame):,} skiften · {score.notna().sum():,} score · {score.isna().sum():,} null · {qa_dir}")
    return 0


def sensitivity_command(args: argparse.Namespace) -> int:
    local = load_config(ROOT / args.config)
    model = load_model_config(ROOT / args.model_config)
    paths = resolve_model_paths(args, local)
    source = paths["output"] / "akerdrift_fast_v1_skane.parquet"
    if not source.exists():
        raise FileNotFoundError(f"Saknar {source}. Kör merge först.")
    frame = pd.read_parquet(source)
    fe = _numeric(frame, "fe_geom")
    difficulty = _numeric(frame, "drift_slope_difficulty")
    valid = fe.notna() & difficulty.notna()
    result = frame.loc[valid, ["kommun", "block_id", "skifte_id"]].copy()
    for penalty in (0.10, 0.20, 0.30):
        result[f"score_penalty_{int(penalty*100)}"] = (100.0 * fe[valid] * (1.0 - penalty * difficulty[valid])).clip(0, 100)
    baseline = result["score_penalty_20"]
    summary = []
    for penalty in (0.10, 0.30):
        column = f"score_penalty_{int(penalty*100)}"
        delta = (result[column] - baseline).abs()
        summary.append({
            "slope_penalty_max": penalty,
            "spearman_vs_0_20": float(result[column].corr(baseline, method="spearman")),
            "median_absolute_difference": float(delta.median()),
            "p95_absolute_difference": float(delta.quantile(.95)),
        })
    out = paths["output"] / "sensitivity"
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(summary).to_csv(out / "sensitivity_summary.csv", index=False, encoding="utf-8-sig")
    result["max_absolute_change"] = result[["score_penalty_10", "score_penalty_30"]].sub(baseline, axis=0).abs().max(axis=1)
    result.nlargest(50, "max_absolute_change").to_csv(out / "largest_changes.csv", index=False, encoding="utf-8-sig")
    print(f"SENSITIVITET: {len(result):,} skiften · {out}")
    return 0


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default="config/local_paths.json", help="Lokala rådata-/buildsökvägar")
    parser.add_argument("--model-config", default="config/akerdrift_fast_v1_rc0.json")
    parser.add_argument("--output-dir")
    parser.add_argument("--slope-raster")
    parser.add_argument("--twi-raster")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="ÅkerDrift Fast MVP V1")
    commands = root.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Beräkna och checkpointa kommunvis")
    add_common_arguments(run)
    run.add_argument("--kommun", action="append", help="Kommun; flaggan kan upprepas eller innehålla komma")
    run.add_argument("--all", action="store_true", help="Alla 33 kommuner")
    run.add_argument("--resume", action="store_true", default=True, help="Återanvänd giltiga checkpoints (default)")
    run.add_argument("--no-resume", action="store_false", dest="resume")
    run.add_argument("--force", action="store_true", help="Räkna om valda kommuner")
    run.set_defaults(func=run_command)

    merge = commands.add_parser("merge", help="Slå ihop verifierade kommunfiler")
    add_common_arguments(merge)
    merge.add_argument("--allow-partial", action="store_true", help="Endast för utveckling/test")
    merge.set_defaults(func=merge_command)

    qa = commands.add_parser("qa", help="Billig QA på färdig Skånefil; läser inga raster")
    add_common_arguments(qa)
    qa.set_defaults(func=qa_command)

    sensitivity = commands.add_parser("sensitivity", help="0.10/0.20/0.30 utan ny rasterläsning")
    add_common_arguments(sensitivity)
    sensitivity.set_defaults(func=sensitivity_command)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.func(args))
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"FEL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
