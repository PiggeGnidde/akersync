#!/usr/bin/env python3
"""Independent STOPPUNKT C verifier for the full ÅkerNorm V1 run."""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import subprocess
import traceback
from pathlib import Path

import pandas as pd
from pandas.api.types import is_numeric_dtype

from akernorm_v1_core import atomic_json, load_config, sha256_file


ROOT = Path(__file__).resolve().parents[1]
CONTEXT_COMMIT = "1ad5c77656bb93664d94254af298009a6620da4f"


def load_full_module():
    spec = importlib.util.spec_from_file_location(
        "akernorm_v1_full_verification_runtime", ROOT / "src/83_run_akernorm_v1_full_skane.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load full-Skåne runtime")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FULL = load_full_module()


def git(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()


def verify_scope() -> list[str]:
    changed = git("diff", "--name-only", f"{CONTEXT_COMMIT}..HEAD").splitlines()
    allowed_exact = {
        "RUN_AKERNORM_V1_DISCOVERY.bat", "VERIFY_AKERNORM_V1_REPRODUCTION.bat",
        "FREEZE_AKERNORM_V1_MODEL.bat", "RUN_AKERNORM_V1_PILOT.bat", "VERIFY_AKERNORM_V1_PILOT.bat",
        "RUN_AKERNORM_V1_FULL_SKANE.bat", "VERIFY_AKERNORM_V1_FULL_SKANE.bat",
        "config/akernorm_v1.json", "docs/AKERNORM_V1_MODEL_CANDIDATE.md",
        "src/78_akernorm_v1_discovery.py", "src/79_verify_akernorm_v1_reproduction.py",
        "src/80_freeze_akernorm_v1_model.py", "src/81_run_akernorm_v1_pilot.py",
        "src/82_verify_akernorm_v1_pilot.py", "src/83_run_akernorm_v1_full_skane.py",
        "src/84_verify_akernorm_v1_full_skane.py", "src/akernorm_v1_discovery_core.py",
        "src/akernorm_v1_core.py", "tests/test_akernorm_v1_discovery.py",
        "tests/test_akernorm_v1_model.py", "tests/test_akernorm_v1_pilot.py",
        "tests/test_akernorm_v1_full_skane.py",
    }
    allowed_prefixes = ("analysis/akerscore_normskord_validation_v0a/", "analysis/akernorm_v1_discovery/")
    unexpected = [path for path in changed if path not in allowed_exact and not path.startswith(allowed_prefixes)]
    if unexpected:
        raise RuntimeError(f"Full-Skåne scope contains unexpected paths: {unexpected}")
    forbidden_tokens = ("sentinel", "web/", "dist/", "akerdrift", "akervarde")
    forbidden = [path for path in changed if any(token in path.lower() for token in forbidden_tokens)]
    if forbidden:
        raise RuntimeError(f"Full-Skåne scope touches a protected product: {forbidden}")
    return changed


def verify_full_manifest(output_root: Path) -> dict:
    manifest = FULL.verify_manifest(output_root / "manifests/full_skane_manifest.json", output_root)
    if manifest.get("schema_version") != FULL.FULL_SCHEMA:
        raise RuntimeError("Unexpected full-Skåne manifest schema")
    if manifest.get("repository_head") != git("rev-parse", "HEAD"):
        raise RuntimeError("Full-Skåne manifest was produced by another repository HEAD")
    if int(manifest.get("reference_fields", -1)) != FULL.EXPECTED_FIELDS:
        raise RuntimeError("Full manifest does not contain exactly 128,636 fields")
    if int(manifest.get("municipalities", -1)) != FULL.EXPECTED_MUNICIPALITIES:
        raise RuntimeError("Full manifest does not contain exactly 33 municipalities")
    if manifest.get("rerun_stability") != "PASS" or manifest.get("checkpoint_reuse_verification") != "PASS":
        raise RuntimeError("Full manifest lacks rerun/checkpoint stability PASS")
    scope = manifest.get("scope", {})
    if not scope.get("full_skane_run") or scope.get("web_changed") or scope.get("sentinel2_changed"):
        raise RuntimeError("Full manifest scope is not limited to authorized Phase C")
    return manifest


def compare_frames(actual: pd.DataFrame, expected: pd.DataFrame, label: str) -> None:
    sort_columns = [column for column in ("current_field_id", "crop_code_canonical") if column in actual.columns]
    actual = actual.sort_values(sort_columns, kind="mergesort").reset_index(drop=True)
    expected = expected.sort_values(sort_columns, kind="mergesort").reset_index(drop=True)
    if list(actual.columns) != list(expected.columns) or len(actual) != len(expected):
        raise RuntimeError(f"{label} schema/row count differs from independent recomputation")
    for column in actual.columns:
        if not (is_numeric_dtype(actual[column]) and is_numeric_dtype(expected[column])):
            actual[column] = actual[column].astype("string").fillna("")
            expected[column] = expected[column].astype("string").fillna("")
    try:
        pd.testing.assert_frame_equal(
            actual, expected, check_dtype=False, check_exact=False, rtol=0.0, atol=1e-12,
        )
    except AssertionError as exc:
        raise RuntimeError(f"{label} differs from independent recomputation: {exc}") from exc


def verify_geometry_ids(path: Path, expected_ids: set[str]) -> dict:
    import geopandas as gpd

    geometry = gpd.read_file(path)
    missing = sorted({"blockid", "skiftesbeteckning", "geometry"} - set(geometry.columns))
    if missing:
        raise RuntimeError(f"Geometry source lacks columns: {missing}")
    ids = {
        f"{FULL.PILOT.normalized_id(block)}|{FULL.PILOT.normalized_id(field)}"
        for block, field in zip(geometry["blockid"], geometry["skiftesbeteckning"])
    }
    if len(geometry) != len(ids):
        raise RuntimeError("Geometry source contains duplicate field IDs")
    if ids != expected_ids:
        raise RuntimeError("Geometry source does not reconcile to frozen reference fields")
    return {"fields": len(ids), "sha256": sha256_file(path)}


def verify_partitions(output_root: Path, state: dict, config: dict, manifest: dict) -> dict:
    checkpoints = []
    all_actual, all_coverage = [], []
    for entry in sorted(manifest["municipality_checkpoints"], key=lambda row: str(row["municipality_code"])):
        code, name = str(entry["municipality_code"]), str(entry["municipality"])
        fields = state["base"][state["base"]["municipality_code"].astype(str).eq(code)].copy()
        ids = set(fields["current_field_id"].astype(str))
        directory = FULL.checkpoint_dir(output_root, code, name)
        checkpoint = FULL.validate_checkpoint(directory, state["run_key"], ids, code)
        if checkpoint is None:
            raise RuntimeError(f"Municipality checkpoint is invalid: {code}")
        actual = pd.read_parquet(directory / "field_akernorm_v1.parquet")
        expected = FULL.PILOT.calculate_pilot(
            sorted(ids), state["presence"], state["base"], state["official"],
            state["references"], config, state["source_manifest"]["manifest_id"],
        )
        compare_frames(actual, expected, f"Municipality {code} field output")
        actual_coverage = pd.read_parquet(directory / "field_coverage.parquet")
        expected_coverage = FULL.build_field_coverage(fields, expected)
        compare_frames(actual_coverage, expected_coverage, f"Municipality {code} field coverage")
        checkpoints.append(checkpoint)
        all_actual.append(actual)
        all_coverage.append(actual_coverage)

    if len(checkpoints) != FULL.EXPECTED_MUNICIPALITIES:
        raise RuntimeError("Independent verifier did not find 33 checkpoints")
    digest = FULL.output_hash(checkpoints)
    if digest != manifest["output_hash"]:
        raise RuntimeError("Recomputed full output hash differs from manifest")
    output = pd.concat(all_actual, ignore_index=True)
    coverage = pd.concat(all_coverage, ignore_index=True)
    if len(coverage) != FULL.EXPECTED_FIELDS or coverage["current_field_id"].nunique() != FULL.EXPECTED_FIELDS:
        raise RuntimeError("Independent coverage does not reconcile to 128,636 fields")
    if int(manifest["field_crop_rows"]) != len(output):
        raise RuntimeError("Manifest field/crop row count differs")
    return {"checkpoints": checkpoints, "output": output, "coverage": coverage, "output_hash": digest}


def verify_qa(output_root: Path, result: dict, geometry: dict, manifest: dict) -> dict:
    output, coverage = result["output"], result["coverage"]
    qa = json.loads((output_root / "qa/full_skane_qa.json").read_text(encoding="utf-8-sig"))
    if qa.get("status") != "PASS" or qa.get("output_hash") != manifest["output_hash"]:
        raise RuntimeError("Full QA status/output hash differs from manifest")
    if qa.get("rerun_stability") != "PASS":
        raise RuntimeError("Full QA rerun stability is not PASS")
    expected_status = {str(k): int(v) for k, v in output["model_status"].value_counts().sort_index().items()}
    expected_support = {str(k): int(v) for k, v in output["score_support_status"].value_counts().sort_index().items()}
    expected_field = {str(k): int(v) for k, v in coverage["field_status"].value_counts().sort_index().items()}
    if qa.get("model_status_counts") != expected_status or qa.get("score_support_counts") != expected_support:
        raise RuntimeError("Full QA row distributions do not reconcile")
    if qa.get("field_status_counts") != expected_field:
        raise RuntimeError("Full QA field distributions do not reconcile")
    if qa.get("geometry", {}).get("source_sha256") != geometry["sha256"]:
        raise RuntimeError("Full QA geometry hash differs")
    problems = pd.read_csv(
        output_root / "qa/full_skane_problem_rows.csv", low_memory=False,
        dtype={"current_field_id": str, "municipality_code": str, "sko_id": str},
    )
    expected_problems = FULL.problem_rows(output)
    compare_frames(problems, expected_problems, "Problem-row list")
    geojson = json.loads((output_root / "qa/full_skane_problem_fields_sample.geojson").read_text(encoding="utf-8-sig"))
    if geojson.get("type") != "FeatureCollection" or len(geojson.get("features", [])) != int(qa["geometry"]["geojson_sample_fields"]):
        raise RuntimeError("Problem GeoJSON sample does not reconcile")
    feature_ids = [str(row["properties"]["current_field_id"]) for row in geojson["features"]]
    if len(feature_ids) != len(set(feature_ids)) or not set(feature_ids).issubset(set(problems["current_field_id"].astype(str))):
        raise RuntimeError("Problem GeoJSON IDs are duplicate or outside the full problem list")
    conservation = pd.read_csv(output_root / "qa/full_skane_reference_conservation.csv")
    if conservation.empty or not conservation["status"].eq("PASS").all():
        raise RuntimeError("Full crop/SKO conservation artifact is not PASS")
    if not all(math.isfinite(float(value)) and float(value) <= 1e-12 for value in conservation["absolute_error_t_ha"]):
        raise RuntimeError("Full crop/SKO conservation tolerance failed")
    return {
        "model_status_counts": expected_status,
        "score_support_counts": expected_support,
        "field_status_counts": expected_field,
        "problem_rows": len(problems),
        "problem_geojson_fields": len(feature_ids),
        "conservation_rows": len(conservation),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--akerminne-skane-root", required=True, type=Path)
    parser.add_argument("--field-geometry", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    try:
        if git("branch", "--show-current") != "feature/akernorm-product-v1a":
            raise RuntimeError("STOPPUNKT C verifier must run on feature/akernorm-product-v1a")
        if git("status", "--short"):
            raise RuntimeError("Working tree is not clean before STOPPUNKT C verification")
        changed = verify_scope()
        config = load_config(ROOT / "config/akernorm_v1.json")
        manifest = verify_full_manifest(output_root)
        state = FULL.load_frozen_state(
            args.input_dir.resolve(), args.akerminne_skane_root.resolve(), output_root, config
        )
        if state["run_key"] != manifest["run_key"]:
            raise RuntimeError("Current frozen sources produce another run key")
        if state["model_manifest"]["manifest_id"] != manifest["model_manifest_id"]:
            raise RuntimeError("Model manifest ID differs from full manifest")
        result = verify_partitions(output_root, state, config, manifest)
        geometry = verify_geometry_ids(args.field_geometry.resolve(), set(result["coverage"]["current_field_id"].astype(str)))
        qa = verify_qa(output_root, result, geometry, manifest)
        traces = sorted((output_root / "logs").glob("*_traceback.log"))
        if traces:
            raise RuntimeError(f"Failure traceback exists: {traces}")
        report = {
            "schema_version": "akernorm-stopc-verification-v1", "status": "PASS",
            "repository_head": git("rev-parse", "HEAD"),
            "full_manifest_id": manifest["manifest_id"],
            "model_manifest_id": manifest["model_manifest_id"],
            "source_manifest_id": manifest["source_manifest_id"],
            "municipalities": FULL.EXPECTED_MUNICIPALITIES,
            "reference_fields": FULL.EXPECTED_FIELDS,
            "field_crop_rows": int(len(result["output"])),
            "output_hash": result["output_hash"], "rerun_stability": "PASS",
            "qa": qa, "geometry": geometry, "phase_c_scope_paths": changed,
            "scope": {"full_skane_run": True, "web_changed": False, "sentinel2_changed": False},
        }
        atomic_json(report, output_root / "qa/stopc_verification.json")
        print("=" * 88)
        print("AKERNORM V1 STOPPUNKT C VERIFIER: PASS")
        print("=" * 88)
        print(f"Municipalities: {FULL.EXPECTED_MUNICIPALITIES}")
        print(f"Reference fields: {FULL.EXPECTED_FIELDS}")
        print(f"Field/crop rows: {len(result['output'])}")
        print(f"Output hash: {result['output_hash']}")
        print("Rerun/checkpoint stability: PASS")
        print("Full Skane: YES. Web/Sentinel-2: NO.")
        print("STOPPUNKT C")
        return 0
    except Exception as exc:
        print(traceback.format_exc())
        print(f"AKERNORM V1 STOPPUNKT C VERIFIER: FAIL — {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
