#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from akernorm_v1_discovery_core import (
    artifact_hashes,
    repository_snapshot,
    sha256_file,
    verify_repository_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "discovery_repository_report.md",
    "akernorm_analysis_inventory.md",
    "official_norm_source_report.md",
    "crop_code_contract.json",
    "reproduction_comparison.csv",
    "discovery_manifest.json",
    "discovery_qa.md",
    "reproduction_model_decisions.json",
    "reproduced_metrics.json",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    failures: list[str] = []

    snapshot = repository_snapshot(ROOT)
    failures.extend(f"repository: {value}" for value in verify_repository_snapshot(snapshot))
    for name in REQUIRED:
        if not (output / name).is_file():
            failures.append(f"missing required artifact: {name}")

    if failures:
        print("AKERNORM V1 REPRODUCTION VERIFIER: FAIL")
        for failure in failures:
            print("ERROR:", failure)
        return 1

    manifest = json.loads((output / "discovery_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "PASS":
        failures.append(f"discovery manifest status is {manifest.get('status')}, expected PASS")
    if manifest.get("errors"):
        failures.append(f"discovery manifest contains errors: {manifest.get('errors')}")
    fatal_traceback = output / "logs/fatal_traceback.log"
    if fatal_traceback.is_file():
        failures.append(f"fatal traceback log exists after PASS run: {fatal_traceback}")
    scope = manifest.get("scope") or {}
    forbidden_true = [name for name, value in scope.items() if bool(value)]
    if forbidden_true:
        failures.append(f"discovery scope claims later-phase work: {forbidden_true}")

    comparison = pd.read_csv(output / "reproduction_comparison.csv")
    mismatch = comparison[comparison["status"] != "PASS"]
    if len(mismatch):
        failures.append(f"reproduction comparison contains {len(mismatch)} non-PASS rows")

    crop_contract = json.loads((output / "crop_code_contract.json").read_text(encoding="utf-8"))
    if crop_contract.get("status") != "PASS":
        failures.append(f"crop-code contract status is {crop_contract.get('status')}")

    decisions = json.loads((output / "reproduction_model_decisions.json").read_text(encoding="utf-8"))
    if decisions.get("status") != "PASS":
        failures.append(f"model decision reproduction status is {decisions.get('status')}")
    if decisions.get("climate_selected_for_v1") is not False:
        failures.append("climate_selected_for_v1 must remain false at STOPPUNKT A")
    if decisions.get("potato_score_adjusted_in_v1") is not False:
        failures.append("potato_score_adjusted_in_v1 must remain false at STOPPUNKT A")

    expected_hashes = manifest.get("artifact_hashes") or {}
    actual_hashes = artifact_hashes(output)
    missing_hashes = sorted(set(expected_hashes) - set(actual_hashes))
    extra_hashes = sorted(set(actual_hashes) - set(expected_hashes))
    changed_hashes = sorted(
        name for name in set(expected_hashes) & set(actual_hashes)
        if expected_hashes[name].get("sha256") != actual_hashes[name].get("sha256")
    )
    if missing_hashes:
        failures.append(f"manifested artifacts missing: {missing_hashes}")
    if extra_hashes:
        failures.append(f"unmanifested artifacts present: {extra_hashes}")
    if changed_hashes:
        failures.append(f"artifact hash mismatch: {changed_hashes}")

    source = manifest.get("source") or {}
    normalized_path = Path(source.get("normalized_path") or "")
    if not normalized_path.is_file():
        failures.append(f"normalized official source missing: {normalized_path}")
    elif sha256_file(normalized_path) != source.get("normalized_sha256"):
        failures.append("normalized official source SHA256 mismatch")

    if failures:
        print("=" * 88)
        print("AKERNORM V1 REPRODUCTION VERIFIER: FAIL")
        print("=" * 88)
        for failure in failures:
            print("ERROR:", failure)
        return 1

    print("=" * 88)
    print("AKERNORM V1 REPRODUCTION VERIFIER: PASS")
    print("=" * 88)
    print(f"Repository HEAD: {snapshot['head']}")
    print(f"Comparison rows: {len(comparison)} all PASS")
    print(f"Manifested artifacts: {len(expected_hashes)}")
    print("Model freeze: NO")
    print("Production/pilot/full Skane/web/Sentinel-2: NO")
    print("STOPPUNKT A")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
