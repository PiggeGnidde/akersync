#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify the immutable ÅkerPrestation phase 0 freeze contract before tagging."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from akerprestation_phase0_discovery_core import load_json, sha256_file

PHASE = ROOT / "data" / "derived" / "akerprestation_phase0"
QA_PATH = PHASE / "qa" / "skane" / "qa.json"
MANIFEST_PATH = PHASE / "manifests" / "skane_phase0_manifest.json"

TAG_NAME = "akerprestation-phase0-v0a"
EXPECTED_BRANCH = "feature/akerprestation-phase0-freeze-v0a"
EXPECTED_BUILD_HEAD = "92c1e92535ac636e50b522f93c0e675c2b6f63ed"
EXPECTED_BASE_COMMIT = "4b53ab24e9822f1c36c6cc31931dba3c1855fead"
EXPECTED_REFERENCE_FIELDS = 128_636
EXPECTED_MUNICIPALITIES = 33
EXPECTED_CLASSES = list(range(1, 11))
EXPECTED_SKO_IDS = [
    "0731", "1011", "1111", "1112", "1121", "1122", "1123", "1124", "1131",
    "1211", "1212", "1213", "1214", "1215", "1216", "1221", "1222", "1321",
]
EXPECTED_REFERENCE_HASH = "63f256c012a8f8aab75f22699bc729e60036913429caeb070306f57c19b31706"
EXPECTED_SOIL_HASH = "6f4375a1e0ba1f1abde13ddae70e28b6defa853019e1a3663a9ee6e9903ff4a1"
EXPECTED_SKO_HASH = "04ebf07a2e6b0646af0f65056fe59d198f23965fa12fb896b004e3d8fca02f31"
EXPECTED_OVERLAY_HASH = "ee28c510082ee0c87360ad728d84318ddccac32671f869590309d0cbcdd737b9"
EXPECTED_FIELD_ID_DIGEST = "3ef3dd23e1a91dd216f1d99497da8de8297fe16d4902ca0dc7dcaa95a366e1a0"

ALLOWED_POST_BUILD_FILES = {
    "FREEZE_AKERPRESTATION_PHASE0_V0A.bat",
    "docs/AKERPRESTATION_PHASE0_FREEZE.md",
    "src/76_verify_akerprestation_phase0_freeze.py",
    "tests/test_akerprestation_phase0_freeze.py",
}


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def validate_contract(qa: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    if qa.get("status") != "PASS" or not (qa.get("acceptance") or {}).get("pass"):
        errors.append("full-Skåne qa.json is not accepted PASS")
    if manifest.get("status") != "PASS":
        errors.append("full-Skåne manifest is not PASS")
    if int(qa.get("reference_fields", -1)) != EXPECTED_REFERENCE_FIELDS:
        errors.append("qa reference_fields != 128,636")
    if int(manifest.get("reference_fields", -1)) != EXPECTED_REFERENCE_FIELDS:
        errors.append("manifest reference_fields != 128,636")
    if int(qa.get("municipalities_passed", -1)) != EXPECTED_MUNICIPALITIES:
        errors.append("qa municipalities_passed != 33")
    if int(qa.get("municipalities_total", -1)) != EXPECTED_MUNICIPALITIES:
        errors.append("qa municipalities_total != 33")

    soil = qa.get("soil") or {}
    if list(soil.get("classes_present") or []) != EXPECTED_CLASSES:
        errors.append("soil classes are not exactly 1-10")
    if soil.get("unverified_component_rows") != 0:
        errors.append("unverified soil components are not zero")
    if int(soil.get("missing_fields", -1)) != 17_540:
        errors.append("soil missing field count changed from validated 17,540")
    if int(soil.get("partial_fields", -1)) != 22_775:
        errors.append("soil partial field count changed from validated 22,775")
    if int(soil.get("mixed_fields", -1)) != 18_439:
        errors.append("soil mixed field count changed from validated 18,439")

    sko = qa.get("sko") or {}
    if list(sko.get("sko_ids_present") or []) != EXPECTED_SKO_IDS:
        errors.append("SKO ID domain changed from validated 18 IDs")
    if int(sko.get("boundary_fields", -1)) != 2_195:
        errors.append("raw SKO boundary field count changed from validated 2,195")
    if sko.get("unverified_component_rows") != 0:
        errors.append("unverified SKO components are not zero")
    if sko.get("missing_fields") != 0:
        errors.append("SKO missing field count is not zero")

    aker = qa.get("akerminne_reference") or {}
    if aker.get("status") != "PASS":
        errors.append("ÅkerMinne reference verification is not PASS")
    if int(aker.get("matched_ids", -1)) != EXPECTED_REFERENCE_FIELDS:
        errors.append("ÅkerMinne matched ID count != 128,636")
    if aker.get("verification_mode") != "freeze_contract_reference_identity":
        errors.append("unexpected ÅkerMinne verification mode")
    if str(aker.get("freeze_commit") or "") != EXPECTED_BASE_COMMIT:
        errors.append("ÅkerMinne freeze base commit mismatch")

    gates = qa.get("gates") or {}
    if gates.get("skurup_pilot_status") != "PASS":
        errors.append("Skurup pilot gate is not PASS")
    if gates.get("real_class123_status") != "PASS":
        errors.append("real class 1/2/3 gate is not PASS")
    if qa.get("problem_municipalities") not in ([], None):
        errors.append("problem_municipalities is not empty")
    if str(qa.get("reference_field_id_digest") or "") != EXPECTED_FIELD_ID_DIGEST:
        errors.append("reference field ID digest changed")

    qgit = qa.get("git") or {}
    mgit = manifest.get("git") or {}
    if qgit.get("head_commit") != EXPECTED_BUILD_HEAD:
        errors.append("qa was not produced by the validated build HEAD")
    if mgit.get("head_commit") != EXPECTED_BUILD_HEAD:
        errors.append("manifest was not produced by the validated build HEAD")

    expected_sources = {
        "reference_fields_sha256": EXPECTED_REFERENCE_HASH,
        "soil_class_sha256": EXPECTED_SOIL_HASH,
        "sko_sha256": EXPECTED_SKO_HASH,
        "overlay_core_sha256": EXPECTED_OVERLAY_HASH,
    }
    for key, expected in expected_sources.items():
        if str((qa.get("sources") or {}).get(key) or "") != expected:
            errors.append(f"qa source hash mismatch: {key}")
        if str((manifest.get("sources") or {}).get(key) or "") != expected:
            errors.append(f"manifest source hash mismatch: {key}")

    municipalities = manifest.get("municipalities") or {}
    if len(municipalities) != EXPECTED_MUNICIPALITIES:
        errors.append("manifest does not contain 33 municipalities")
    for code, row in municipalities.items():
        if (row or {}).get("status") != "PASS":
            errors.append(f"manifest municipality {code} is not PASS")

    return errors


def main() -> int:
    errors: list[str] = []
    if not QA_PATH.exists():
        errors.append(f"missing {QA_PATH}")
    if not MANIFEST_PATH.exists():
        errors.append(f"missing {MANIFEST_PATH}")
    if errors:
        for err in errors:
            print("ERROR_FREEZE: " + err)
        return 1

    qa = load_json(QA_PATH)
    manifest = load_json(MANIFEST_PATH)
    errors.extend(validate_contract(qa, manifest))

    branch = git("branch", "--show-current")
    head = git("rev-parse", "HEAD")
    if branch != EXPECTED_BRANCH:
        errors.append(f"expected branch {EXPECTED_BRANCH}, got {branch}")

    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", EXPECTED_BUILD_HEAD, head], cwd=ROOT
    )
    if proc.returncode != 0:
        errors.append("freeze HEAD does not descend from validated Skåne build HEAD")

    changed = {
        x.strip().replace("\\", "/")
        for x in git("diff", "--name-only", f"{EXPECTED_BUILD_HEAD}..HEAD").splitlines()
        if x.strip()
    }
    unexpected = sorted(changed - ALLOWED_POST_BUILD_FILES)
    missing_metadata = sorted(ALLOWED_POST_BUILD_FILES - changed)
    if unexpected:
        errors.append("unexpected post-build tracked changes: " + ", ".join(unexpected))
    if missing_metadata:
        errors.append("freeze metadata files not all present in post-build diff: " + ", ".join(missing_metadata))

    for rel, expected_hash in (manifest.get("outputs") or {}).items():
        path = PHASE / Path(rel)
        if not path.exists():
            errors.append(f"manifest output missing: {rel}")
        elif sha256_file(path) != str(expected_hash):
            errors.append(f"manifest output hash mismatch: {rel}")

    print("=" * 96)
    print("ÅkerPrestation phase 0 · FREEZE PREFLIGHT")
    print("=" * 96)
    print(f"Tag to create: {TAG_NAME}")
    print(f"Validated build HEAD: {EXPECTED_BUILD_HEAD}")
    print(f"Freeze metadata HEAD: {head}")
    print(f"Reference fields: {qa.get('reference_fields'):,}")
    print(f"Municipalities PASS: {qa.get('municipalities_passed')}/{qa.get('municipalities_total')}")
    print(f"Classes: {(qa.get('soil') or {}).get('classes_present')}")
    print(f"SKO IDs: {len((qa.get('sko') or {}).get('sko_ids_present') or [])}")
    print(f"Soil missing/partial: {(qa.get('soil') or {}).get('missing_fields'):,} / {(qa.get('soil') or {}).get('partial_fields'):,}")
    print(f"SKO missing: {(qa.get('sko') or {}).get('missing_fields')}")

    if errors:
        for err in errors:
            print("ERROR_FREEZE: " + err)
        print("VERIFY_AKERPRESTATION_PHASE0_FREEZE: FAIL")
        return 1

    print("VERIFY_AKERPRESTATION_PHASE0_FREEZE: PASS")
    print("Freeze preflight only; tag creation is performed by the BAT runner after this PASS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
