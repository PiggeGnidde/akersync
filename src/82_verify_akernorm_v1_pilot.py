#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import subprocess
import traceback
from pathlib import Path

import pandas as pd

from akernorm_v1_core import atomic_json, load_config, sha256_file


ROOT = Path(__file__).resolve().parents[1]
CONTEXT_COMMIT = "1ad5c77656bb93664d94254af298009a6620da4f"


def verify_manifest(root: Path, name: str, artifact_root: Path | None = None) -> dict:
    path = root / f"manifests/{name}"
    if not path.exists():
        raise RuntimeError(f"Missing manifest: {path}")
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if document.get("status") not in {"PASS", "FROZEN_CANDIDATE_STOPB"}:
        raise RuntimeError(f"Manifest is not PASS: {path}")
    artifact_root = root if artifact_root is None else artifact_root
    for record in document.get("artifacts", []):
        relative = Path(record["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"Manifest artifact path is unsafe: {record['path']}")
        artifact = artifact_root / relative
        if not artifact.exists() or sha256_file(artifact) != record["sha256"]:
            raise RuntimeError(f"Manifest artifact mismatch: {record['path']}")
        if artifact.stat().st_size != int(record["bytes"]):
            raise RuntimeError(f"Manifest artifact byte count mismatch: {record['path']}")
    return document


def verify_scope() -> list[str]:
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", f"{CONTEXT_COMMIT}..HEAD"], cwd=ROOT, text=True, encoding="utf-8"
    ).splitlines()
    allowed_exact = {
        "RUN_AKERNORM_V1_DISCOVERY.bat", "VERIFY_AKERNORM_V1_REPRODUCTION.bat",
        "FREEZE_AKERNORM_V1_MODEL.bat", "RUN_AKERNORM_V1_PILOT.bat", "VERIFY_AKERNORM_V1_PILOT.bat",
        "config/akernorm_v1.json", "docs/AKERNORM_V1_MODEL_CANDIDATE.md",
        "src/78_akernorm_v1_discovery.py", "src/79_verify_akernorm_v1_reproduction.py",
        "src/80_freeze_akernorm_v1_model.py", "src/81_run_akernorm_v1_pilot.py",
        "src/82_verify_akernorm_v1_pilot.py", "src/akernorm_v1_discovery_core.py", "src/akernorm_v1_core.py",
        "tests/test_akernorm_v1_discovery.py", "tests/test_akernorm_v1_model.py",
        "tests/test_akernorm_v1_pilot.py",
    }
    allowed_prefixes = ("analysis/akerscore_normskord_validation_v0a/", "analysis/akernorm_v1_discovery/")
    unexpected = [path for path in changed if path not in allowed_exact and not path.startswith(allowed_prefixes)]
    if unexpected:
        raise RuntimeError(f"Freeze-scope contains unexpected paths: {unexpected}")
    forbidden_tokens = ("sentinel", "web/", "dist/", "akerdrift", "akervarde", "akerscore_soil", "akerminne_v1a.json")
    forbidden = [path for path in changed if any(token in path.lower() for token in forbidden_tokens)]
    if forbidden:
        raise RuntimeError(f"Freeze-scope touches a protected product: {forbidden}")
    return changed


def verify_pilot(root: Path, config: dict) -> dict:
    csv_path = root / "pilot/field_akernorm_v1_pilot.csv"
    parquet_path = root / "pilot/field_akernorm_v1_pilot.parquet"
    csv = pd.read_csv(csv_path, dtype={"current_field_id": str, "sko_id": str})
    parquet = pd.read_parquet(parquet_path)
    if len(csv) != len(parquet) or list(csv.columns) != list(parquet.columns):
        raise RuntimeError("Pilot CSV/Parquet schema or row count differs")
    if csv.duplicated(["current_field_id", "crop_code_canonical"]).any():
        raise RuntimeError("Pilot has duplicate field/crop rows")
    numeric = csv[csv["field_akernorm_t_ha"].notna()].copy()
    if numeric.empty:
        raise RuntimeError("Pilot has no adjusted numeric rows")
    expected = numeric["official_sko_norm_t_ha"] + numeric["beta_t_ha_per_score"] * (
        numeric["akerscore_value"] - numeric["sko_crop_reference_score"]
    )
    if not all(math.isclose(a, b, abs_tol=1e-12) for a, b in zip(numeric["field_akernorm_t_ha"], expected)):
        raise RuntimeError("Pilot formula recomputation differs")
    potatoes = csv[csv["crop_code_canonical"].isin([45, 46])]
    if potatoes.empty or potatoes["field_akernorm_t_ha"].notna().any() or potatoes["beta_t_ha_per_score"].notna().any():
        raise RuntimeError("Potato pilot guardrail failed")
    if not potatoes["municipality_code"].astype(str).eq("1290").any():
        raise RuntimeError("Pilot lacks Kristianstad potato coverage")
    grain = csv[csv["crop_code_canonical"].isin([2, 4])]
    if not grain["municipality_code"].astype(str).eq("1264").any():
        raise RuntimeError("Pilot lacks a grain case in the configured grain-area candidate Skurup")
    low_sko = csv[csv["model_status"].eq("UNAVAILABLE_LOW_SKO_SHARE")]
    if low_sko.empty or low_sko["field_akernorm_t_ha"].notna().any():
        raise RuntimeError("Low-SKO-share status coverage failed")
    component = csv[csv["history_quality"].eq("HISTORY_COMPONENT_ONLY")]
    if component.empty:
        raise RuntimeError("Pilot lacks HISTORY_COMPONENT_ONLY")
    no_norm = csv[csv["model_status"].eq("UNAVAILABLE_NO_OFFICIAL_NORM")]
    if no_norm.empty or no_norm["field_akernorm_t_ha"].notna().any():
        raise RuntimeError("Pilot lacks explicit unavailable-no-norm case")
    support_allowed = {
        "NOT_APPLICABLE", "MISSING_AKERSCORE", "REFERENCE_UNAVAILABLE", "WITHIN_P05_P95",
        "BELOW_P05_WITHIN_OBSERVED", "ABOVE_P95_WITHIN_OBSERVED", "BELOW_OBSERVED_MIN", "ABOVE_OBSERVED_MAX",
    }
    unknown = sorted(set(csv["score_support_status"].dropna()) - support_allowed)
    if unknown:
        raise RuntimeError(f"Unknown score-support statuses: {unknown}")
    coverage = pd.read_csv(root / "pilot/pilot_coverage.csv")
    if not coverage.loc[coverage["required"].astype(bool), "status"].eq("SELECTED").all():
        raise RuntimeError("Required pilot coverage is incomplete")
    invariants = pd.read_csv(root / "qa/pilot_invariants.csv")
    if not (invariants["center_invariant"].eq("PASS") & invariants["difference_invariant"].eq("PASS")).all():
        raise RuntimeError("Pilot invariants are not all PASS")
    conservation = pd.read_csv(root / "model/reference_conservation_qa.csv")
    if not conservation["status"].eq("PASS").all() or conservation["absolute_error_t_ha"].max() > 1e-12:
        raise RuntimeError("Reference conservation is not PASS")
    contract = json.loads((root / "model/akernorm_model_contract_v1.json").read_text(encoding="utf-8-sig"))
    if "global regression intercept as local base" not in contract["disallowed"]:
        raise RuntimeError("Contract lacks global-intercept guardrail")
    for crop in contract["crops"]:
        code = int(crop["canonical_code"])
        if code in {45, 46} and crop["beta_t_ha_per_score"] is not None:
            raise RuntimeError("Model contract score-adjusts potato")
    return {
        "rows": int(len(csv)), "fields": int(csv["current_field_id"].nunique()),
        "adjusted_rows": int(len(numeric)), "status_counts": csv["model_status"].value_counts().sort_index().to_dict(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    root = args.output_root.resolve()
    try:
        if subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True, encoding="utf-8").strip():
            raise RuntimeError("Working tree is not clean before STOPPUNKT B verification")
        config = load_config(ROOT / "config/akernorm_v1.json")
        source = verify_manifest(root, "source_manifest.json", root / "source")
        model = verify_manifest(root, "model_manifest.json")
        pilot = verify_manifest(root, "pilot_manifest.json")
        for document in (model, pilot):
            scope = document.get("scope", {})
            if scope.get("full_skane_run") or scope.get("web_changed") or scope.get("sentinel2_changed"):
                raise RuntimeError("Manifest scope crossed STOPPUNKT B")
        changed = verify_scope()
        result = verify_pilot(root, config)
        for trace in (root / "logs").glob("*_traceback.log"):
            raise RuntimeError(f"Stale/current failure trace exists: {trace}")
        report = {
            "schema_version": "akernorm-stopb-verification-v1", "status": "PASS",
            "model_manifest_id": model["manifest_id"], "source_manifest_id": source["manifest_id"],
            "pilot": result, "freeze_scope_paths": changed,
            "scope": {"model_frozen": True, "pilot_run": True, "full_skane_run": False, "web_changed": False, "sentinel2_changed": False},
        }
        atomic_json(report, root / "qa/stopb_verification.json")
        print("=" * 88)
        print("AKERNORM V1 STOPPUNKT B VERIFIER: PASS")
        print("=" * 88)
        print(f"Pilot fields: {result['fields']}")
        print(f"Pilot field/crop rows: {result['rows']}")
        print(f"Adjusted numeric rows: {result['adjusted_rows']}")
        print("Model freeze: YES — candidate pending Bengt decision")
        print("Full Skane/web/Sentinel-2: NO")
        print("STOPPUNKT B")
        return 0
    except Exception as exc:
        print(traceback.format_exc())
        print(f"AKERNORM V1 STOPPUNKT B VERIFIER: FAIL — {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
