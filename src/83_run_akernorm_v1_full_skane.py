#!/usr/bin/env python3
"""Checkpointed ÅkerNorm V1 full-Skåne run for STOPPUNKT C.

This phase only expands the frozen STOPPUNKT B calculation to every frozen
2025 reference field.  It does not build web payloads and never reads
Sentinel-2 data.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import traceback
import unicodedata
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from akernorm_v1_core import (
    artifact_records,
    atomic_csv,
    atomic_json,
    atomic_parquet,
    build_history_presence,
    load_config,
    prepare_inputs,
    sha256_file,
    stable_json,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config/akernorm_v1.json"
EXPECTED_FIELDS = 128_636
EXPECTED_MUNICIPALITIES = 33
FULL_SCHEMA = "akernorm-full-skane-manifest-v1"
CHECKPOINT_SCHEMA = "akernorm-full-skane-municipality-v1"
FIELD_COVERAGE_SCHEMA = "akernorm-field-coverage-v1"


def load_numbered_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PILOT = load_numbered_module("akernorm_v1_pilot_runtime", ROOT / "src/81_run_akernorm_v1_pilot.py")
FREEZE = load_numbered_module("akernorm_v1_freeze_runtime", ROOT / "src/80_freeze_akernorm_v1_model.py")


def stable_hash(document: Any) -> str:
    return hashlib.sha256(stable_json(document).encode("utf-8")).hexdigest()


def git(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()


def slug(value: str) -> str:
    plain = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", plain.lower()).strip("_") or "municipality"


def verify_manifest(document_path: Path, artifact_root: Path) -> dict:
    if not document_path.exists():
        raise RuntimeError(f"Missing required manifest: {document_path}")
    document = json.loads(document_path.read_text(encoding="utf-8-sig"))
    if document.get("status") not in {"PASS", "FROZEN_CANDIDATE_STOPB"}:
        raise RuntimeError(f"Required manifest is not PASS: {document_path}")
    for record in document.get("artifacts", []):
        relative = Path(record["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"Unsafe manifest path: {record['path']}")
        artifact = artifact_root / relative
        if not artifact.exists():
            raise RuntimeError(f"Manifest artifact is missing: {artifact}")
        if artifact.stat().st_size != int(record["bytes"]) or sha256_file(artifact) != record["sha256"]:
            raise RuntimeError(f"Manifest artifact differs: {artifact}")
    return document


def load_frozen_state(
    input_dir: Path,
    akerminne_root: Path,
    output_root: Path,
    config: dict,
    *,
    expected_fields: int = EXPECTED_FIELDS,
    expected_municipalities: int = EXPECTED_MUNICIPALITIES,
) -> dict[str, Any]:
    model_manifest = verify_manifest(output_root / "manifests/model_manifest.json", output_root)
    source_manifest = verify_manifest(output_root / "manifests/source_manifest.json", output_root / "source")
    pilot_manifest_path = output_root / "manifests/pilot_manifest.json"
    pilot_manifest = verify_manifest(pilot_manifest_path, output_root)
    stopb_path = output_root / "qa/stopb_verification.json"
    if not stopb_path.exists():
        raise RuntimeError("Independent STOPPUNKT B verification artifact is missing")
    stopb = json.loads(stopb_path.read_text(encoding="utf-8-sig"))
    if stopb.get("status") != "PASS":
        raise RuntimeError("Independent STOPPUNKT B verification is not PASS")
    if model_manifest.get("source_manifest_id") != source_manifest.get("manifest_id"):
        raise RuntimeError("Model/source manifest IDs do not reconcile")
    for document, label in ((pilot_manifest, "pilot manifest"), (stopb, "STOPPUNKT B verification")):
        if document.get("model_manifest_id") != model_manifest.get("manifest_id"):
            raise RuntimeError(f"{label} model manifest ID differs")
        if document.get("source_manifest_id") != source_manifest.get("manifest_id"):
            raise RuntimeError(f"{label} source manifest ID differs")
    pilot_scope = pilot_manifest.get("scope", {})
    if not pilot_scope.get("pilot_run") or any(pilot_scope.get(name) for name in ("full_skane_run", "web_changed", "sentinel2_changed")):
        raise RuntimeError("Pilot manifest does not contain the accepted STOPPUNKT B scope")
    stopb_scope = stopb.get("scope", {})
    if not stopb_scope.get("pilot_run") or any(stopb_scope.get(name) for name in ("full_skane_run", "web_changed", "sentinel2_changed")):
        raise RuntimeError("Independent STOPPUNKT B scope is not accepted")
    if any(model_manifest.get("scope", {}).get(name) for name in ("full_skane_run", "web_changed", "sentinel2_changed")):
        raise RuntimeError("Frozen model manifest crosses the authorized STOPPUNKT B scope")

    input_records = FREEZE.verify_frozen_inputs(input_dir, config)
    context = pd.read_csv(input_dir / "field_static_context_selected.csv.gz", low_memory=False)
    history = pd.read_csv(input_dir / "akerminne_2015_2025_selected.csv.gz", low_memory=False)
    score = pd.read_csv(input_dir / "akerscore_soil_skiften_selected.csv.gz", low_memory=False)
    context, history, score = prepare_inputs(context, history, score)
    field_ids = set(context["current_field_id"])
    if len(context) != expected_fields or len(field_ids) != expected_fields:
        raise RuntimeError(f"Frozen context expected {expected_fields} unique fields, got {len(field_ids)}")
    if set(score["current_field_id"]) != field_ids or set(history["current_field_id"]) != field_ids:
        raise RuntimeError("Frozen score/history field IDs differ from the context")
    expected_years = set(config["akerminne_years"])
    actual_years = set(history["history_year"].dropna().astype(int))
    if actual_years != expected_years or len(history) != expected_fields * len(expected_years):
        raise RuntimeError("Frozen history does not contain the exact field/year rectangle")

    grouped, component_sources, component_mode, municipalities = PILOT.load_component_source(
        akerminne_root, field_ids, config
    )
    if municipalities["municipality_code"].astype(str).nunique() != expected_municipalities:
        raise RuntimeError(f"Expected {expected_municipalities} municipalities in ÅkerMinne source")
    base = PILOT.build_pilot_base(context, score, municipalities)
    presence = build_history_presence(history, grouped, config)
    official = PILOT.source_norms(output_root)
    references = pd.read_csv(output_root / "model/sko_crop_score_reference.csv", dtype={"sko_id": str})
    references["sko_id"] = references["sko_id"].map(lambda value: PILOT.normalized_id(value, 4))

    component_contract = [{
        key: source.get(key)
        for key in ("source_mode", "municipality_code", "municipality", "rows", "bytes", "sha256", "build_manifest_sha256")
        if key in source
    } for source in component_sources]
    state = {
        "model_manifest": model_manifest,
        "source_manifest": source_manifest,
        "pilot_manifest": pilot_manifest,
        "stopb_verification": stopb,
        "input_records": input_records,
        "context": context,
        "history": history,
        "score": score,
        "base": base,
        "presence": presence,
        "official": official,
        "references": references,
        "component_sources": component_sources,
        "component_mode": component_mode,
        "component_fingerprint": stable_hash(component_contract),
    }
    state["run_key"] = stable_hash({
        "schema": FULL_SCHEMA,
        "model_manifest_id": model_manifest["manifest_id"],
        "source_manifest_id": source_manifest["manifest_id"],
        "pilot_manifest_sha256": sha256_file(pilot_manifest_path),
        "stopb_verification_sha256": sha256_file(stopb_path),
        "frozen_inputs": {name: row["sha256"] for name, row in sorted(input_records.items())},
        "component_fingerprint": state["component_fingerprint"],
        "config_sha256": sha256_file(CONFIG_PATH),
        "calculation_core_sha256": sha256_file(ROOT / "src/akernorm_v1_core.py"),
        "pilot_runtime_sha256": sha256_file(ROOT / "src/81_run_akernorm_v1_pilot.py"),
    })
    return state


def checkpoint_dir(output_root: Path, code: str, name: str) -> Path:
    return output_root / "full_skane/municipalities" / f"{code}_{slug(name)}"


def build_field_coverage(fields: pd.DataFrame, result: pd.DataFrame) -> pd.DataFrame:
    counts = result.groupby("current_field_id", sort=True).agg(
        crop_row_count=("crop_code_canonical", "size"),
        numeric_crop_rows=("field_akernorm_t_ha", lambda values: int(values.notna().sum())),
        unavailable_crop_rows=("model_status", lambda values: int(values.astype(str).str.startswith("UNAVAILABLE").sum())),
    ).reset_index() if len(result) else pd.DataFrame(columns=[
        "current_field_id", "crop_row_count", "numeric_crop_rows", "unavailable_crop_rows"
    ])
    coverage = fields[["current_field_id", "municipality_code", "municipality"]].merge(
        counts, on="current_field_id", how="left", validate="one_to_one"
    )
    for name in ("crop_row_count", "numeric_crop_rows", "unavailable_crop_rows"):
        coverage[name] = coverage[name].fillna(0).astype(int)
    coverage["field_status"] = np.select(
        [coverage["numeric_crop_rows"].gt(0), coverage["crop_row_count"].gt(0)],
        ["HAS_NUMERIC_AKERNORM", "HISTORY_PRESENT_NO_NUMERIC_AKERNORM"],
        default="NO_DISPLAYABLE_CROP_HISTORY",
    )
    coverage.insert(0, "schema_version", FIELD_COVERAGE_SCHEMA)
    return coverage.sort_values("current_field_id", kind="mergesort").reset_index(drop=True)


def checkpoint_artifacts(directory: Path) -> list[dict]:
    rows = []
    for name in ("field_akernorm_v1.parquet", "field_coverage.parquet"):
        path = directory / name
        rows.append({"path": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return rows


def validate_checkpoint(
    directory: Path,
    run_key: str,
    expected_field_ids: set[str],
    municipality_code: str,
) -> dict | None:
    manifest_path = directory / "checkpoint_manifest.json"
    if not manifest_path.exists():
        return None
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if (
            document.get("schema_version") != CHECKPOINT_SCHEMA
            or document.get("status") != "PASS"
            or document.get("run_key") != run_key
            or str(document.get("municipality_code")) != str(municipality_code)
        ):
            return None
        for record in document.get("artifacts", []):
            path = directory / record["path"]
            if not path.exists() or path.stat().st_size != int(record["bytes"]) or sha256_file(path) != record["sha256"]:
                return None
        coverage = pd.read_parquet(directory / "field_coverage.parquet", columns=["current_field_id"])
        if set(coverage["current_field_id"].astype(str)) != expected_field_ids or len(coverage) != len(expected_field_ids):
            return None
        result = pd.read_parquet(directory / "field_akernorm_v1.parquet")
        if int(document["field_crop_rows"]) != len(result):
            return None
        if len(result) and (
            not result["municipality_code"].astype(str).eq(str(municipality_code)).all()
            or result.duplicated(["current_field_id", "crop_code_canonical"]).any()
        ):
            return None
        return document
    except Exception:
        return None


def build_checkpoint(
    output_root: Path,
    municipality_fields: pd.DataFrame,
    state: dict[str, Any],
    config: dict,
) -> tuple[dict, bool]:
    code = str(municipality_fields.iloc[0]["municipality_code"])
    name = str(municipality_fields.iloc[0]["municipality"])
    ids = set(municipality_fields["current_field_id"].astype(str))
    directory = checkpoint_dir(output_root, code, name)
    manifest_path = directory / "checkpoint_manifest.json"
    existing = validate_checkpoint(directory, state["run_key"], ids, code)
    if existing is not None:
        return existing, True
    if manifest_path.exists():
        raise RuntimeError(
            f"Existing checkpoint failed schema/run-key/hash validation: {manifest_path}. "
            "Fail-fast: preserve it for review before moving it aside and rerunning."
        )

    result = PILOT.calculate_pilot(
        sorted(ids), state["presence"], state["base"], state["official"],
        state["references"], config, state["source_manifest"]["manifest_id"],
    )
    if len(result) and set(result["current_field_id"].astype(str)) - ids:
        raise RuntimeError(f"Municipality {code} produced foreign field IDs")
    coverage = build_field_coverage(municipality_fields, result)
    atomic_parquet(result, directory / "field_akernorm_v1.parquet")
    atomic_parquet(coverage, directory / "field_coverage.parquet")
    artifacts = checkpoint_artifacts(directory)
    manifest = {
        "schema_version": CHECKPOINT_SCHEMA,
        "status": "PASS",
        "run_key": state["run_key"],
        "model_manifest_id": state["model_manifest"]["manifest_id"],
        "source_manifest_id": state["source_manifest"]["manifest_id"],
        "municipality_code": code,
        "municipality": name,
        "reference_fields": int(len(municipality_fields)),
        "field_crop_rows": int(len(result)),
        "numeric_rows": int(result["field_akernorm_t_ha"].notna().sum()) if len(result) else 0,
        "field_status_counts": {str(k): int(v) for k, v in coverage["field_status"].value_counts().sort_index().items()},
        "model_status_counts": {str(k): int(v) for k, v in result["model_status"].value_counts().sort_index().items()} if len(result) else {},
        "artifacts": artifacts,
    }
    atomic_json(manifest, directory / "checkpoint_manifest.json")
    checked = validate_checkpoint(directory, state["run_key"], ids, code)
    if checked is None:
        raise RuntimeError(f"Fresh municipality checkpoint did not verify: {code}")
    return checked, False


def output_hash(checkpoints: list[dict]) -> str:
    payload = [{
        "municipality_code": str(row["municipality_code"]),
        "reference_fields": int(row["reference_fields"]),
        "field_crop_rows": int(row["field_crop_rows"]),
        "artifacts": row["artifacts"],
    } for row in sorted(checkpoints, key=lambda item: str(item["municipality_code"]))]
    return stable_hash(payload)


def read_checkpoint_frames(output_root: Path, checkpoints: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    outputs, coverages = [], []
    for row in sorted(checkpoints, key=lambda item: str(item["municipality_code"])):
        directory = checkpoint_dir(output_root, str(row["municipality_code"]), str(row["municipality"]))
        outputs.append(pd.read_parquet(directory / "field_akernorm_v1.parquet"))
        coverages.append(pd.read_parquet(directory / "field_coverage.parquet"))
    return pd.concat(outputs, ignore_index=True), pd.concat(coverages, ignore_index=True)


def numeric_crop_summary(output: pd.DataFrame) -> pd.DataFrame:
    rows = []
    numeric = output[output["field_akernorm_t_ha"].notna()].copy()
    for (code, name), group in numeric.groupby(["crop_code_canonical", "crop_name"], sort=True):
        values = group["field_akernorm_t_ha"].astype(float)
        adjustments = group["adjustment_t_ha"].astype(float)
        rows.append({
            "crop_code_canonical": int(code), "crop_name": str(name), "rows": int(len(group)),
            "min_t_ha": float(values.min()), "p01_t_ha": float(values.quantile(.01)),
            "p05_t_ha": float(values.quantile(.05)), "p50_t_ha": float(values.quantile(.50)),
            "p95_t_ha": float(values.quantile(.95)), "p99_t_ha": float(values.quantile(.99)),
            "max_t_ha": float(values.max()),
            "adjustment_min_t_ha": float(adjustments.min()),
            "adjustment_p01_t_ha": float(adjustments.quantile(.01)),
            "adjustment_p05_t_ha": float(adjustments.quantile(.05)),
            "adjustment_p50_t_ha": float(adjustments.quantile(.50)),
            "adjustment_p95_t_ha": float(adjustments.quantile(.95)),
            "adjustment_p99_t_ha": float(adjustments.quantile(.99)),
            "adjustment_max_t_ha": float(adjustments.max()),
            "official_mean_t_ha": float(group["official_sko_norm_t_ha"].astype(float).mean()),
            "field_mean_t_ha": float(values.mean()),
            "non_positive": int(values.le(0).sum()),
        })
    return pd.DataFrame(rows)


def problem_rows(output: pd.DataFrame) -> pd.DataFrame:
    work = output.copy()
    categories = []
    limits = {2: (0.5, 20.0), 3: (0.5, 20.0), 4: (0.5, 20.0), 20: (0.25, 10.0), 45: (5.0, 100.0), 46: (5.0, 100.0)}
    for row in work.itertuples(index=False):
        flags = []
        value = row.field_akernorm_t_ha
        if str(row.model_status).startswith("UNAVAILABLE"):
            flags.append("BLOCKED_UNAVAILABLE")
        if str(row.score_support_status) in {"BELOW_OBSERVED_MIN", "ABOVE_OBSERVED_MAX"}:
            flags.append("OUTSIDE_OBSERVED_SCORE_SUPPORT")
        if value is not None and not pd.isna(value):
            if float(value) <= 0:
                flags.append("NON_POSITIVE_AKERNORM")
            lower, upper = limits.get(int(row.crop_code_canonical), (-math.inf, math.inf))
            if float(value) < lower or float(value) > upper:
                flags.append("AGRONOMIC_QA_EXTREME")
        categories.append(";".join(sorted(set(flags))))
    work["qa_categories"] = categories
    return work[work["qa_categories"].ne("")].sort_values(
        ["municipality_code", "current_field_id", "crop_code_canonical"], kind="mergesort"
    ).reset_index(drop=True)


def reason_distribution(output: pd.DataFrame) -> pd.DataFrame:
    counts: dict[str, int] = {}
    for value in output["reason_flags"].fillna(""):
        for flag in str(value).split(";"):
            if flag:
                counts[flag] = counts.get(flag, 0) + 1
    return pd.DataFrame([{"reason_flag": key, "rows": counts[key]} for key in sorted(counts)])


def sko_crop_coverage(output: pd.DataFrame) -> pd.DataFrame:
    return output.groupby(
        ["sko_id", "crop_code_canonical", "crop_name", "model_status"], sort=True, dropna=False
    ).agg(rows=("current_field_id", "size"), fields=("current_field_id", "nunique")).reset_index()


def geometry_sample(
    geometry_path: Path,
    expected_field_ids: set[str],
    problems: pd.DataFrame,
    destination: Path,
) -> dict[str, Any]:
    import geopandas as gpd
    from shapely.geometry import mapping

    if not geometry_path.exists():
        raise RuntimeError(f"2025 geometry source is missing: {geometry_path}")
    geometry = gpd.read_file(geometry_path)
    required = {"blockid", "skiftesbeteckning", "geometry"}
    missing = sorted(required - set(geometry.columns))
    if missing:
        raise RuntimeError(f"Geometry source lacks columns: {missing}")
    geometry = geometry[["blockid", "skiftesbeteckning", "geometry"]].copy()
    geometry["current_field_id"] = [
        f"{PILOT.normalized_id(block)}|{PILOT.normalized_id(field)}"
        for block, field in zip(geometry["blockid"], geometry["skiftesbeteckning"])
    ]
    if geometry["current_field_id"].duplicated().any():
        raise RuntimeError("2025 geometry source contains duplicate field IDs")
    if set(geometry["current_field_id"]) != expected_field_ids:
        raise RuntimeError("2025 geometry IDs do not reconcile to all frozen reference fields")

    if problems.empty:
        sample = problems
    else:
        exploded = problems.assign(qa_category=problems["qa_categories"].str.split(";")).explode("qa_category")
        sample = exploded.sort_values(
            ["qa_category", "municipality_code", "crop_code_canonical", "current_field_id"], kind="mergesort"
        ).groupby(["qa_category", "municipality_code", "crop_code_canonical"], sort=True).head(2)
        sample = sample.head(2_000).drop_duplicates("current_field_id", keep="first")
    attributes = sample.groupby("current_field_id", sort=True).agg(
        municipality_code=("municipality_code", "first"),
        municipality=("municipality", "first"),
        qa_categories=("qa_categories", lambda values: ";".join(sorted(set(values)))),
        crop_codes=("crop_code_canonical", lambda values: ";".join(map(str, sorted(set(map(int, values)))))),
        model_statuses=("model_status", lambda values: ";".join(sorted(set(map(str, values))))),
    ).reset_index() if len(sample) else pd.DataFrame(columns=[
        "current_field_id", "municipality_code", "municipality", "qa_categories", "crop_codes", "model_statuses"
    ])
    selected = geometry[geometry["current_field_id"].isin(set(attributes["current_field_id"]))].merge(
        attributes, on="current_field_id", how="inner", validate="one_to_one"
    )
    if len(selected) != len(attributes):
        raise RuntimeError("Problem GeoJSON sample did not reconcile to geometry")
    selected = selected.to_crs(4326).sort_values("current_field_id", kind="mergesort")
    features = []
    for row in selected.itertuples(index=False):
        properties = {
            "current_field_id": str(row.current_field_id),
            "municipality_code": str(row.municipality_code),
            "municipality": str(row.municipality),
            "qa_categories": str(row.qa_categories),
            "crop_codes": str(row.crop_codes),
            "model_statuses": str(row.model_statuses),
        }
        features.append({"type": "Feature", "properties": properties, "geometry": mapping(row.geometry)})
    atomic_json({"type": "FeatureCollection", "features": features}, destination)
    return {
        "source_path": str(geometry_path), "source_sha256": sha256_file(geometry_path),
        "reference_fields": int(len(geometry)), "problem_rows": int(len(problems)),
        "problem_fields": int(problems["current_field_id"].nunique()) if len(problems) else 0,
        "geojson_sample_fields": int(len(features)),
    }


def write_qa_markdown(path: Path, qa: dict, crop_summary: pd.DataFrame) -> None:
    lines = [
        "# ÅkerNorm V1 – full Skåne QA (STOPPUNKT C)", "",
        "- Status: `PASS`",
        f"- Referensskiften: `{qa['reference_fields']}`",
        f"- Kommuner: `{qa['municipalities']}`",
        f"- Fält/grödrader: `{qa['field_crop_rows']}`",
        f"- Numeriska ÅkerNorm-rader: `{qa['numeric_rows']}`",
        f"- Full outputhash: `{qa['output_hash']}`",
        f"- Rerun/checkpoint-stabilitet: `{qa['rerun_stability']}`",
        "- Webb/Sentinel-2: `NO`", "",
        "## Status", "",
    ]
    lines.extend(f"- `{key}`: {value}" for key, value in qa["model_status_counts"].items())
    lines += ["", "## Numeriska grödor", ""]
    if crop_summary.empty:
        lines.append("Inga numeriska rader.")
    else:
        lines += [
            "| Gröda | Rader | Min | P01 | P05 | P50 | P95 | P99 | Max | Icke-positiva |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for row in crop_summary.itertuples(index=False):
            lines.append(
                f"| {row.crop_name} | {row.rows} | {row.min_t_ha:.6g} | {row.p01_t_ha:.6g} | "
                f"{row.p05_t_ha:.6g} | {row.p50_t_ha:.6g} | {row.p95_t_ha:.6g} | "
                f"{row.p99_t_ha:.6g} | {row.max_t_ha:.6g} | {row.non_positive} |"
            )
    lines += [
        "", "## Problem- och kartkontroll", "",
        f"- Problemrader i full CSV-lista: `{qa['geometry']['problem_rows']}`",
        f"- Unika problemfält: `{qa['geometry']['problem_fields']}`",
        f"- Deterministiskt GeoJSON-stickprov: `{qa['geometry']['geojson_sample_fields']}` fält",
        "", "## STOPPUNKT C", "",
        "Ingen webbbyggnad, taggning, deployment eller Sentinel-2-bearbetning har körts.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def global_artifact_paths(output_root: Path, checkpoints: list[dict]) -> list[str]:
    paths = [
        "full_skane/field_coverage.parquet",
        "qa/full_skane_qa.json", "qa/full_skane_qa.md",
        "qa/full_skane_municipality_coverage.csv", "qa/full_skane_status_distribution.csv",
        "qa/full_skane_crop_summary.csv", "qa/full_skane_score_support.csv",
        "qa/full_skane_reason_distribution.csv", "qa/full_skane_sko_crop_coverage.csv",
        "qa/full_skane_unsupported_coverage.csv", "qa/full_skane_official_vs_field.csv",
        "qa/full_skane_reference_conservation.csv", "qa/full_skane_problem_rows.csv",
        "qa/full_skane_problem_fields_sample.geojson",
    ]
    for checkpoint in checkpoints:
        directory = checkpoint_dir(output_root, str(checkpoint["municipality_code"]), str(checkpoint["municipality"]))
        relative = directory.relative_to(output_root).as_posix()
        paths.extend([
            f"{relative}/field_akernorm_v1.parquet",
            f"{relative}/field_coverage.parquet",
            f"{relative}/checkpoint_manifest.json",
        ])
    return paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--akerminne-skane-root", required=True, type=Path)
    parser.add_argument("--field-geometry", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    logs = output_root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "full_skane_traceback.log").unlink(missing_ok=True)
    try:
        if git("branch", "--show-current") != "feature/akernorm-product-v1a":
            raise RuntimeError("Full Skåne must run on feature/akernorm-product-v1a")
        if git("status", "--short"):
            raise RuntimeError("Working tree is not clean before full Skåne")
        config = load_config(CONFIG_PATH)
        state = load_frozen_state(
            args.input_dir.resolve(), args.akerminne_skane_root.resolve(), output_root, config
        )
        checkpoints, reused = [], 0
        grouped_fields = state["base"].sort_values(
            ["municipality_code", "current_field_id"], kind="mergesort"
        ).groupby("municipality_code", sort=True)
        for code, municipality_fields in grouped_fields:
            name = str(municipality_fields.iloc[0]["municipality"])
            print(f"[{code} {name}] fields={len(municipality_fields)}", flush=True)
            checkpoint, was_reused = build_checkpoint(output_root, municipality_fields, state, config)
            checkpoints.append(checkpoint)
            reused += int(was_reused)
            print(f"[{code} {name}] {'CHECKPOINT REUSED' if was_reused else 'BUILT'} rows={checkpoint['field_crop_rows']}", flush=True)
        if len(checkpoints) != EXPECTED_MUNICIPALITIES:
            raise RuntimeError("Full run did not produce exactly 33 municipality checkpoints")

        first_hash = output_hash(checkpoints)
        for checkpoint in checkpoints:
            code, name = str(checkpoint["municipality_code"]), str(checkpoint["municipality"])
            fields = state["base"][state["base"]["municipality_code"].astype(str).eq(code)]
            if validate_checkpoint(checkpoint_dir(output_root, code, name), state["run_key"], set(fields["current_field_id"]), code) is None:
                raise RuntimeError(f"Checkpoint reuse verification failed: {code}")
        second_hash = output_hash(checkpoints)
        if first_hash != second_hash:
            raise RuntimeError("Output hash changed during no-op checkpoint reuse verification")

        result, coverage = read_checkpoint_frames(output_root, checkpoints)
        if len(coverage) != EXPECTED_FIELDS or coverage["current_field_id"].nunique() != EXPECTED_FIELDS:
            raise RuntimeError("Full field coverage does not reconcile to 128,636 fields")
        if result.duplicated(["current_field_id", "crop_code_canonical"]).any():
            raise RuntimeError("Full output contains duplicate field/crop rows")
        if set(result["current_field_id"].astype(str)) - set(coverage["current_field_id"].astype(str)):
            raise RuntimeError("Full output contains a field outside frozen coverage")

        qa_dir = output_root / "qa"
        atomic_parquet(coverage, output_root / "full_skane/field_coverage.parquet")
        municipality = coverage.groupby(["municipality_code", "municipality"], sort=True).agg(
            reference_fields=("current_field_id", "size"),
            fields_with_numeric_akernorm=("numeric_crop_rows", lambda values: int(values.gt(0).sum())),
            fields_without_crop_history=("field_status", lambda values: int(values.eq("NO_DISPLAYABLE_CROP_HISTORY").sum())),
        ).reset_index()
        status = result.groupby(["crop_code_canonical", "crop_name", "model_status"], sort=True).size().rename("rows").reset_index()
        score_support = result.groupby(["crop_code_canonical", "crop_name", "score_support_status"], sort=True).size().rename("rows").reset_index()
        crop_summary = numeric_crop_summary(result)
        reasons = reason_distribution(result)
        sko_crop = sko_crop_coverage(result)
        unsupported = result[~result["model_status"].astype(str).str.startswith("FIELD_ADJUSTED")].groupby(
            ["municipality_code", "municipality", "sko_id", "crop_code_canonical", "crop_name", "model_status"],
            sort=True, dropna=False,
        ).agg(rows=("current_field_id", "size"), fields=("current_field_id", "nunique")).reset_index()
        numeric = result[result["field_akernorm_t_ha"].notna()].copy()
        official_vs_field = numeric.groupby(
            ["crop_code_canonical", "crop_name", "sko_id"], sort=True
        ).agg(
            rows=("current_field_id", "size"), fields=("current_field_id", "nunique"),
            official_sko_norm_t_ha=("official_sko_norm_t_ha", "first"),
            field_mean_t_ha=("field_akernorm_t_ha", "mean"),
            adjustment_mean_t_ha=("adjustment_t_ha", "mean"),
            adjustment_min_t_ha=("adjustment_t_ha", "min"),
            adjustment_max_t_ha=("adjustment_t_ha", "max"),
        ).reset_index()
        problems = problem_rows(result)
        conservation = pd.read_csv(output_root / "model/reference_conservation_qa.csv", dtype={"sko_id": str})
        if conservation.empty or not conservation["status"].eq("PASS").all() or conservation["absolute_error_t_ha"].max() > 1e-12:
            raise RuntimeError("Frozen crop/SKO conservation check is not PASS")
        atomic_csv(municipality, qa_dir / "full_skane_municipality_coverage.csv")
        atomic_csv(status, qa_dir / "full_skane_status_distribution.csv")
        atomic_csv(crop_summary, qa_dir / "full_skane_crop_summary.csv")
        atomic_csv(score_support, qa_dir / "full_skane_score_support.csv")
        atomic_csv(reasons, qa_dir / "full_skane_reason_distribution.csv")
        atomic_csv(sko_crop, qa_dir / "full_skane_sko_crop_coverage.csv")
        atomic_csv(unsupported, qa_dir / "full_skane_unsupported_coverage.csv")
        atomic_csv(official_vs_field, qa_dir / "full_skane_official_vs_field.csv")
        atomic_csv(conservation, qa_dir / "full_skane_reference_conservation.csv")
        atomic_csv(problems, qa_dir / "full_skane_problem_rows.csv")
        geometry = geometry_sample(
            args.field_geometry.resolve(), set(coverage["current_field_id"].astype(str)), problems,
            qa_dir / "full_skane_problem_fields_sample.geojson",
        )
        status_counts = {str(k): int(v) for k, v in result["model_status"].value_counts().sort_index().items()}
        support_counts = {str(k): int(v) for k, v in result["score_support_status"].value_counts().sort_index().items()}
        qa = {
            "schema_version": "akernorm-full-skane-qa-v1", "status": "PASS",
            "reference_fields": int(len(coverage)), "municipalities": int(len(municipality)),
            "field_crop_rows": int(len(result)), "numeric_rows": int(result["field_akernorm_t_ha"].notna().sum()),
            "field_status_counts": {str(k): int(v) for k, v in coverage["field_status"].value_counts().sort_index().items()},
            "model_status_counts": status_counts, "score_support_counts": support_counts,
            "low_sko_share_rows": int(result["model_status"].eq("UNAVAILABLE_LOW_SKO_SHARE").sum()),
            "missing_score_rows": int(result["model_status"].eq("UNAVAILABLE_MISSING_AKERSCORE").sum()),
            "history_component_only_rows": int(result["history_quality"].eq("HISTORY_COMPONENT_ONLY").sum()),
            "non_positive_rows": int(result["field_akernorm_t_ha"].dropna().le(0).sum()),
            "agronomic_extreme_rows": int(problems["qa_categories"].str.contains("AGRONOMIC_QA_EXTREME", regex=False).sum()),
            "outside_p05_p95_rows": int(result["score_support_status"].isin([
                "BELOW_P05_WITHIN_OBSERVED", "ABOVE_P95_WITHIN_OBSERVED", "BELOW_OBSERVED_MIN", "ABOVE_OBSERVED_MAX"
            ]).sum()),
            "outside_observed_min_max_rows": int(result["score_support_status"].isin(["BELOW_OBSERVED_MIN", "ABOVE_OBSERVED_MAX"]).sum()),
            "conservation_rows": int(len(conservation)), "conservation_status": "PASS",
            "output_hash": first_hash, "rerun_stability": "PASS", "checkpoints_reused_on_entry": reused,
            "component_source_mode": state["component_mode"], "component_fingerprint": state["component_fingerprint"],
            "geometry": geometry,
            "scope": {"full_skane_run": True, "web_changed": False, "sentinel2_changed": False},
        }
        atomic_json(qa, qa_dir / "full_skane_qa.json")
        write_qa_markdown(qa_dir / "full_skane_qa.md", qa, crop_summary)
        relative = global_artifact_paths(output_root, checkpoints)
        manifest = {
            "schema_version": FULL_SCHEMA, "status": "PASS",
            "manifest_id": f"akernorm-full-skane-{first_hash[:16]}",
            "repository_head": git("rev-parse", "HEAD"), "run_key": state["run_key"],
            "model_manifest_id": state["model_manifest"]["manifest_id"],
            "source_manifest_id": state["source_manifest"]["manifest_id"],
            "pilot_manifest_sha256": sha256_file(output_root / "manifests/pilot_manifest.json"),
            "stopb_verification_sha256": sha256_file(output_root / "qa/stopb_verification.json"),
            "reference_fields": int(len(coverage)), "municipalities": int(len(checkpoints)),
            "field_crop_rows": int(len(result)), "numeric_rows": int(result["field_akernorm_t_ha"].notna().sum()),
            "output_hash": first_hash, "rerun_stability": "PASS",
            "checkpoint_reuse_verification": "PASS", "component_source_mode": state["component_mode"],
            "municipality_checkpoints": [{
                "municipality_code": row["municipality_code"], "municipality": row["municipality"],
                "reference_fields": row["reference_fields"], "field_crop_rows": row["field_crop_rows"],
            } for row in checkpoints],
            "scope": {"model_frozen": True, "pilot_run": True, "full_skane_run": True, "web_changed": False, "sentinel2_changed": False},
            "artifacts": artifact_records(output_root, relative),
        }
        atomic_json(manifest, output_root / "manifests/full_skane_manifest.json")
        print("=" * 88)
        print("AKERNORM V1 FULL SKANE: PASS")
        print("=" * 88)
        print(f"Municipalities: {len(checkpoints)}")
        print(f"Reference fields: {len(coverage)}")
        print(f"Field/crop rows: {len(result)}")
        print(f"Output hash: {first_hash}")
        print("Rerun/checkpoint stability: PASS")
        print("No web, deployment or Sentinel-2 work ran.")
        return 0
    except Exception as exc:
        (logs / "full_skane_traceback.log").write_text(traceback.format_exc(), encoding="utf-8")
        print(traceback.format_exc())
        print(f"AKERNORM V1 FULL SKANE: FAIL — {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
