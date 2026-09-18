#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Formal freeze of the accepted persistent M4 V1B reproduction package.

This stage verifies the exact reproduction evidence and saved fold models. It
does not fit any model and does not predict 2026.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
EXPECTED_REPRO_GIT_HEAD = "74f0ad83115fb8f87985be0a78939b7ea8cde86e"
EXPECTED_REPRO_DIR = Path(r"C:\AkerSyncRepo\work\akerpuls_m4_reproduction_gate_v1b")
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_m4_reimplementation_v1b_freeze")
STATUS = "FROZEN_AKERPULS_M4_REIMPLEMENTATION_V1B"

EXPECTED_MANIFEST_SHA256 = "a8b108041d6fde4bcb434d7270bb88c1f620bd7327650ed418ce49eafac17e17"
EXPECTED_FILES = {
    "ENVIRONMENT.json": "fa8457f88433eb6ba9f56c7ad0ee80d26a2501fefedd645883cd7f592ddc014a",
    "FEATURE_CONTRACT.json": "a264d348728dd417435fa418c4e9b14abf927d727c0f5b2c2f9587e6be986d35",
    "M4_REIMPLEMENTATION_FOLD_METRICS.csv": "fb1d099eb7ad1d503e3828c06db338d81e183e0bed67b092c5f9624dd2c672ad",
    "REPRODUCTION_SUMMARY.json": "a0a7cb234b6379b33bbab4154ee29b66d9d6452a00029d9370d49fe42af1df0f",
    "V1B_TARGET_VALIDITY_PROVENANCE.json": "2a1c3a31f8f4ab37e1a4eb7f87007199991f43ca33da74147033da448a9cb59b",
    "models/M4_REIMPL_FOLD_2021.txt": "fbbb049cda018ae4acee055f8ddc729137b180d334d43519c2764da011d93f81",
    "models/M4_REIMPL_FOLD_2022.txt": "075451ca7d298910894d4b2d68f2ee3f2e8ee7c87b939308cc4ce6035128ac6e",
    "models/M4_REIMPL_FOLD_2023.txt": "150fdb239b0a28a94174d9fcd83ff3812a7b1b1531719606feeada73076fd488",
    "models/M4_REIMPL_FOLD_2024.txt": "fc455632b9fbdeb7277a5197a42bb87029b5335ec5865e42acc2d19b2e0022de",
    "models/M4_REIMPL_FOLD_2025.txt": "b2372179f76e69396eec0110dc636c62053d2490e57ea66468591f0bf0eceda7",
}
EXPECTED_TARGET_N = {2021: 118190, 2022: 119101, 2023: 120330, 2024: 122065, 2025: 128636}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def verify_source_package(src: Path) -> dict:
    if not src.is_dir():
        raise FileNotFoundError(src)

    manifest = src / "SHA256_MANIFEST.txt"
    if not manifest.is_file():
        raise FileNotFoundError(manifest)
    got_manifest_sha = sha256_file(manifest)
    if got_manifest_sha != EXPECTED_MANIFEST_SHA256:
        raise RuntimeError(f"Reproduction manifest SHA changed: {got_manifest_sha}")

    verified = {}
    for rel, expected in EXPECTED_FILES.items():
        p = src / rel
        if not p.is_file():
            raise FileNotFoundError(p)
        got = sha256_file(p)
        if got != expected:
            raise RuntimeError(f"Reproduction artefact SHA mismatch {rel}: {got}")
        verified[rel] = got

    summary = load_json(src / "REPRODUCTION_SUMMARY.json")
    if summary.get("status") != "PASS_M4_REIMPLEMENTATION_REPRODUCTION_COMPATIBILITY_GATE":
        raise RuntimeError(f"Reproduction status is not PASS: {summary.get('status')}")
    if summary.get("git_head") != EXPECTED_REPRO_GIT_HEAD:
        raise RuntimeError(f"Unexpected reproduction git head: {summary.get('git_head')}")
    if summary.get("prediction_2026_executed") is not False:
        raise RuntimeError("2026 prediction must remain unopened before freeze")
    if summary.get("fusion_executed") is not False or summary.get("geometry_mutated") is not False:
        raise RuntimeError("Reproduction package has unexpected fusion/geometry mutation")

    census = {int(x["year"]): x for x in summary.get("target_census", []) if int(x["year"]) in EXPECTED_TARGET_N}
    for year, n in EXPECTED_TARGET_N.items():
        row = census.get(year)
        if row is None or int(row.get("n_valid_target", -1)) != n or row.get("n_match") is not True:
            raise RuntimeError(f"Target census mismatch for {year}: {row}")

    comp = summary.get("comparison", {})
    if comp.get("n_exact_all_years") is not True:
        raise RuntimeError("Exact target-N gate not passed")
    gates = comp.get("gate_metrics", {})
    required = ["log_loss", "brier_multiclass", "top1_accuracy", "top3_accuracy", "mean_entropy"]
    if any(gates.get(k, {}).get("pass") is not True for k in required):
        raise RuntimeError("One or more frozen compatibility metric gates did not pass")

    prov = load_json(src / "V1B_TARGET_VALIDITY_PROVENANCE.json")
    if prov.get("exclude_statuses") != ["NO_PUBLIC_MATCH"]:
        raise RuntimeError("Unexpected V1B target validity rule")
    if prov.get("apply_to_target_validity") is not True or prov.get("apply_to_history_feature_validity") is not True:
        raise RuntimeError("V1B NO_PUBLIC_MATCH rule is not applied to both target and history validity")
    if prov.get("prediction_2026_executed") is not False:
        raise RuntimeError("V1B provenance says 2026 was predicted")

    return {
        "source_manifest_sha256": got_manifest_sha,
        "verified_files": verified,
        "summary_status": summary["status"],
        "target_census": {str(y): EXPECTED_TARGET_N[y] for y in sorted(EXPECTED_TARGET_N)},
        "compatibility_metrics": gates,
        "target_validity_rule": {
            "exclude_statuses": ["NO_PUBLIC_MATCH"],
            "apply_to_target_validity": True,
            "apply_to_history_feature_validity": True,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-dir", default=str(EXPECTED_REPRO_DIR))
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    freeze_git_head = git_guard()
    src = Path(args.source_dir)
    out = Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Freeze output already exists: {out}")

    verified = verify_source_package(src)

    payload = {
        "schema_version": "akerpuls-m4-reimplementation-v1b-freeze-v1",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "freeze_git_head": freeze_git_head,
        "reproduction_git_head": EXPECTED_REPRO_GIT_HEAD,
        "source_reproduction_dir": str(src),
        "source_reproduction_manifest_sha256": verified["source_manifest_sha256"],
        "source_artefacts": verified["verified_files"],
        "reproduction_status": verified["summary_status"],
        "target_census": verified["target_census"],
        "compatibility_metrics": verified["compatibility_metrics"],
        "target_validity_rule": verified["target_validity_rule"],
        "model_contract": {
            "selected_model": "M4-hard multiclass reimplementation V1B",
            "target_classes": 16,
            "lightgbm_version": "4.7.0",
            "fold_models_saved": 5,
            "original_transient_feature_builder_preserved": False,
            "compatibility_not_bit_exact_identity": True,
        },
        "guards": {
            "model_fit_executed_in_freeze": False,
            "prediction_2026_executed": False,
            "fusion_executed": False,
            "geometry_mutated": False,
            "thresholds_retuned_after_reproduction": False,
        },
        "next": "TRAIN_AND_PERSIST_FINAL_M4_2026_PRIOR_USING_HISTORY_THROUGH_2025",
    }

    out.mkdir(parents=True, exist_ok=False)
    freeze_json = out / "AKERPULS_M4_REIMPLEMENTATION_V1B_FREEZE.json"
    freeze_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    freeze_sha = sha256_file(freeze_json)
    (out / "AKERPULS_M4_REIMPLEMENTATION_V1B_FREEZE.sha256").write_text(
        freeze_sha + "  AKERPULS_M4_REIMPLEMENTATION_V1B_FREEZE.json\n", encoding="utf-8"
    )
    shutil.copyfile(src / "SHA256_MANIFEST.txt", out / "SOURCE_REPRODUCTION_SHA256_MANIFEST.txt")

    readme = (
        "# ÅkerPuls M4 reimplementation V1B freeze\n\n"
        f"Status: {STATUS}\n\n"
        f"Canonical freeze SHA-256: {freeze_sha}\n\n"
        "This freeze accepts the persistent V1B reimplementation as historically compatible "
        "with frozen STOPPUNKT C under tolerances committed before the reproduction run. "
        "It is not a claim of bit-identical recovery of the lost transient feature builder.\n\n"
        "The exact historical target census is reproduced for 2021–2025 and the V1B "
        "validity rule is status != NO_PUBLIC_MATCH, applied to both target validity "
        "and history-feature validity.\n\n"
        "No 2026 prediction, merge fusion or geometry mutation occurred in this freeze.\n"
    )
    (out / "README.md").write_text(readme, encoding="utf-8")

    print("AKERPULS M4 REIMPLEMENTATION V1B FREEZE")
    print(f"STATUS={STATUS}")
    print(f"REPRODUCTION_GIT_HEAD={EXPECTED_REPRO_GIT_HEAD}")
    print(f"FREEZE_GIT_HEAD={freeze_git_head}")
    print(f"SOURCE_REPRODUCTION_MANIFEST_SHA256={verified['source_manifest_sha256']}")
    print(f"M4_REIMPLEMENTATION_FREEZE_SHA256={freeze_sha}")
    print("TARGET_CENSUS_EXACT_2021_2025=TRUE")
    print("COMPATIBILITY_GATE_ALL_METRICS=PASS")
    print("NO_PUBLIC_MATCH_RULE_TARGET_AND_HISTORY=TRUE")
    print("MODEL_FIT_EXECUTED_IN_FREEZE=FALSE PREDICTION_2026_EXECUTED=FALSE")
    print("FUSION_EXECUTED=FALSE GEOMETRY_MUTATED=FALSE THRESHOLDS_RETUNED=FALSE")
    print("NEXT=TRAIN_AND_PERSIST_FINAL_M4_2026_PRIOR_USING_HISTORY_THROUGH_2025")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
