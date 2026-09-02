#!/usr/bin/env python3
"""Final, independent AkerNorm V1 freeze verification.

This gate verifies the accepted STOPPUNKT A-D artifacts without recomputing the
four-hour full-Skane production run.  It is intentionally stricter than the
individual phase gates: every manifested artifact is hashed again, frozen input
hashes are checked, the local web is compared with its protected base, and the
complete Git scope is allowlisted before the immutable product tag is created.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import traceback
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BRANCH = "feature/akernorm-product-v1a"
TAG = "akernorm-v1.0"
CONTEXT_COMMIT = "1ad5c77656bb93664d94254af298009a6620da4f"
PRODUCT_PARENT_TREE = "5a938a72dd978a3b529834bd0a8c2aef09292100"
SOURCE_ID = "akernorm-source-2026-f03930b8a2a063de"
MODEL_ID = "akernorm-model-def3710a77e7ace9"
FULL_ID = "akernorm-full-skane-38d679e0f59c3ae0"
FULL_OUTPUT_HASH = "38d679e0f59c3ae0326661cabffe363c21ae15622a491fdb5cceb6e4e3635e6e"
EXPECTED_MUNICIPALITIES = 33
EXPECTED_FIELDS = 128_636
EXPECTED_ROWS = 402_922
EXPECTED_INPUTS = {
    "field_static_context_selected.csv.gz": "31db31b79b53a4c0aa32621fb7bfa44165ea65b6b46371c32e4e19935f59feea",
    "akerminne_2015_2025_selected.csv.gz": "05423236dc30544f86422d42ce5c9095376a9d5dac58e6ea110f6e6702cecdcf",
    "akerscore_soil_skiften_selected.csv.gz": "71dfd711a4243b3cbe465de7eaa013725b2d2f9be3a8890d213a89bc095427da",
}
FREEZE_FILES = {
    "FREEZE_AKERNORM_V1.bat",
    "docs/AKERNORM_V1_FREEZE.md",
    "src/88_verify_akernorm_v1_freeze.py",
    "tests/test_akernorm_v1_freeze.py",
}
ALLOWED_EXACT = {
    "BUILD_AKERNORM_V1_WEB.bat", "FREEZE_AKERNORM_V1_MODEL.bat",
    "RUN_AKERNORM_V1_DISCOVERY.bat", "RUN_AKERNORM_V1_FULL_SKANE.bat",
    "RUN_AKERNORM_V1_PILOT.bat", "VERIFY_AKERNORM_V1_FULL_SKANE.bat",
    "VERIFY_AKERNORM_V1_PILOT.bat", "VERIFY_AKERNORM_V1_REPRODUCTION.bat",
    "VERIFY_AKERNORM_V1_WEB.bat", "config/akernorm_v1.json",
    "docs/AKERNORM_V1_MODEL_CANDIDATE.md",
    *FREEZE_FILES,
    "src/78_akernorm_v1_discovery.py", "src/79_verify_akernorm_v1_reproduction.py",
    "src/80_freeze_akernorm_v1_model.py", "src/81_run_akernorm_v1_pilot.py",
    "src/82_verify_akernorm_v1_pilot.py", "src/83_run_akernorm_v1_full_skane.py",
    "src/84_verify_akernorm_v1_full_skane.py", "src/85_build_akernorm_v1_web.py",
    "src/86_patch_akerpass_akernorm_v1_ui.py", "src/87_verify_akernorm_v1_web.py",
    "src/akernorm_v1_core.py", "src/akernorm_v1_discovery_core.py",
    "tests/test_akernorm_v1_discovery.py", "tests/test_akernorm_v1_full_skane.py",
    "tests/test_akernorm_v1_model.py", "tests/test_akernorm_v1_pilot.py",
    "tests/test_akernorm_v1_web.py", "tests/test_akernorm_v1_web_ui.py",
}
ALLOWED_PREFIXES = ("analysis/akernorm_v1_discovery/", "analysis/akerscore_normskord_validation_v0a/")


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"Missing JSON artifact: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()


def verify_record(root: Path, record: dict[str, Any]) -> None:
    relative = Path(str(record["path"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError(f"Unsafe manifested path: {record['path']}")
    artifact = root / relative
    if not artifact.is_file():
        raise RuntimeError(f"Manifested artifact is missing: {artifact}")
    if artifact.stat().st_size != int(record["bytes"]) or sha256_file(artifact) != str(record["sha256"]):
        raise RuntimeError(f"Manifested artifact differs: {artifact}")


def verify_manifest_artifacts(document: dict[str, Any], root: Path) -> int:
    records = document.get("artifacts") or []
    for record in records:
        verify_record(root, record)
    return len(records)


def protected_inventory(root: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root)
        if relative.as_posix() == "index.html" or Path("data/akernorm") in relative.parents:
            continue
        records.append({"path": relative.as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return records


def verify_scope(changed: list[str]) -> None:
    unexpected = [path for path in changed if path not in ALLOWED_EXACT and not path.startswith(ALLOWED_PREFIXES)]
    if unexpected:
        raise RuntimeError(f"Freeze scope contains unexpected paths: {unexpected}")
    forbidden = [path for path in changed if "sentinel" in path.casefold()]
    if forbidden:
        raise RuntimeError(f"Freeze scope touches Sentinel-2: {forbidden}")
    if not FREEZE_FILES.issubset(changed):
        raise RuntimeError(f"Freeze metadata is incomplete: {sorted(FREEZE_FILES - set(changed))}")


def verify_contract(
    stop_a_dir: Path, input_dir: Path, output_root: Path, base_dist: Path, dist: Path,
) -> dict[str, Any]:
    source = read_json(output_root / "manifests/source_manifest.json")
    model = read_json(output_root / "manifests/model_manifest.json")
    pilot = read_json(output_root / "manifests/pilot_manifest.json")
    full = read_json(output_root / "manifests/full_skane_manifest.json")
    web = read_json(output_root / "manifests/akernorm_web_manifest.json")
    stopb = read_json(output_root / "qa/stopb_verification.json")
    stopc = read_json(output_root / "qa/stopc_verification.json")
    stopd = read_json(output_root / "qa/stopd_verification.json")

    required_status = (source, model, pilot, full, web, stopb, stopc, stopd)
    if any(item.get("status") not in {"PASS", "FROZEN_CANDIDATE_STOPB"} for item in required_status):
        raise RuntimeError("At least one accepted STOPPUNKT A-D manifest/report is not PASS")
    if source.get("manifest_id") != SOURCE_ID or model.get("source_manifest_id") != SOURCE_ID:
        raise RuntimeError("Frozen official-source lineage differs")
    if model.get("manifest_id") != MODEL_ID or pilot.get("model_manifest_id") != MODEL_ID:
        raise RuntimeError("Frozen model lineage differs")
    if full.get("manifest_id") != FULL_ID or web.get("full_manifest_id") != FULL_ID:
        raise RuntimeError("Full-Skane/web lineage differs")
    if full.get("output_hash") != FULL_OUTPUT_HASH or web.get("full_output_hash") != FULL_OUTPUT_HASH:
        raise RuntimeError("Full-Skane output hash differs")
    if int(full.get("reference_fields", -1)) != EXPECTED_FIELDS or int(full.get("field_crop_rows", -1)) != EXPECTED_ROWS:
        raise RuntimeError("Full-Skane field/row totals differ")
    if (int(web.get("municipality_count", -1)), int(web.get("field_count", -1)), int(web.get("field_crop_rows", -1))) != (
        EXPECTED_MUNICIPALITIES, EXPECTED_FIELDS, EXPECTED_ROWS,
    ):
        raise RuntimeError("Web municipality/field/row totals differ")
    for document in (full, web, stopc, stopd):
        scope = document.get("scope") or {}
        if scope.get("sentinel2_changed") or scope.get("deployment"):
            raise RuntimeError("An accepted artifact claims deployment or Sentinel-2 work")

    stop_a_manifest = stop_a_dir / "discovery_manifest.json"
    if sha256_file(stop_a_manifest) != model.get("stop_a_manifest_sha256"):
        raise RuntimeError("STOPPUNKT A manifest differs from the frozen model input")
    if read_json(stop_a_manifest).get("status") != "PASS":
        raise RuntimeError("STOPPUNKT A manifest is not PASS")
    for name, expected_sha in EXPECTED_INPUTS.items():
        path = input_dir / name
        if not path.is_file() or sha256_file(path) != expected_sha:
            raise RuntimeError(f"Frozen input differs: {path}")

    artifact_counts = {
        "source": verify_manifest_artifacts(source, output_root / "source"),
        "model": verify_manifest_artifacts(model, output_root),
        "pilot": verify_manifest_artifacts(pilot, output_root),
        "full_skane": verify_manifest_artifacts(full, output_root),
    }
    if artifact_counts != {"source": 20, "model": 6, "pilot": 7, "full_skane": 113}:
        raise RuntimeError(f"Manifest artifact counts differ: {artifact_counts}")

    if sha256_file(base_dist / "index.html") != web.get("base_index_sha256"):
        raise RuntimeError("Frozen base index differs from web manifest")
    if sha256_file(dist / "index.html") != web.get("patched_index_sha256"):
        raise RuntimeError("Patched ÅkerNorm index differs from web manifest")
    protected = web.get("protected_base_files") or []
    if protected_inventory(base_dist) != protected or protected_inventory(dist) != protected:
        raise RuntimeError("Score/Value/Drift/Minne web artifacts are not byte-identical")
    for record in web.get("web_artifacts") or []:
        verify_record(dist / "data/akernorm", record)
    index = read_json(dist / "data/akernorm/skane_index.json")
    if (index.get("status"), int(index.get("municipality_count", -1)), int(index.get("field_count", -1)), int(index.get("field_crop_rows", -1))) != (
        "PASS", EXPECTED_MUNICIPALITIES, EXPECTED_FIELDS, EXPECTED_ROWS,
    ):
        raise RuntimeError("ÅkerNorm web index totals/status differ")
    if int(index.get("sidecar_bytes", -1)) != int(web.get("sidecar_bytes", -2)):
        raise RuntimeError("ÅkerNorm web sidecar byte total differs")

    return {
        "source_manifest_id": SOURCE_ID,
        "model_manifest_id": MODEL_ID,
        "full_manifest_id": FULL_ID,
        "web_manifest_id": web["manifest_id"],
        "full_output_hash": FULL_OUTPUT_HASH,
        "artifact_counts": artifact_counts,
        "web_artifacts": len(web.get("web_artifacts") or []),
        "sidecar_bytes": int(web["sidecar_bytes"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop-a-dir", required=True, type=Path)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--base-dist", required=True, type=Path)
    parser.add_argument("--dist", default=str(ROOT / "dist"), type=Path)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    logs = output_root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    trace = logs / "freeze_verify_traceback.log"
    trace.unlink(missing_ok=True)
    try:
        if git("branch", "--show-current") != BRANCH:
            raise RuntimeError(f"Freeze requires branch {BRANCH}")
        if git("status", "--short"):
            raise RuntimeError("Working tree is not clean before freeze verification")
        if git("rev-parse", "HEAD~1") == "":
            raise RuntimeError("Freeze commit has no product parent")
        if git("rev-parse", "HEAD~1^{tree}") != PRODUCT_PARENT_TREE:
            raise RuntimeError("Freeze parent tree differs from the accepted STOPPUNKT D product tree")
        freeze_delta = set(git("diff", "--name-only", "HEAD^", "HEAD").splitlines())
        if freeze_delta != FREEZE_FILES:
            raise RuntimeError(f"Freeze commit must contain only freeze metadata: {sorted(freeze_delta)}")
        changed = git("diff", "--name-only", f"{CONTEXT_COMMIT}..HEAD").splitlines()
        verify_scope(changed)
        contract = verify_contract(
            args.stop_a_dir.resolve(), args.input_dir.resolve(), output_root,
            args.base_dist.resolve(), args.dist.resolve(),
        )
        report = {
            "schema_version": "akernorm-freeze-verification-v1", "status": "PASS",
            "tag_candidate": TAG, "freeze_commit": git("rev-parse", "HEAD"),
            "product_parent": git("rev-parse", "HEAD~1"), "product_parent_tree": PRODUCT_PARENT_TREE,
            "branch": BRANCH, "scope_paths": changed, **contract,
            "counts": {"municipalities": EXPECTED_MUNICIPALITIES, "fields": EXPECTED_FIELDS, "field_crop_rows": EXPECTED_ROWS},
            "scope": {"model_frozen": True, "full_skane_run": True, "web_changed": True, "deployment": False, "sentinel2_changed": False},
        }
        qa = output_root / "qa"
        qa.mkdir(parents=True, exist_ok=True)
        (qa / "freeze_verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("=" * 88)
        print("AKERNORM V1 FINAL FREEZE VERIFIER: PASS")
        print("=" * 88)
        print(f"Source/model/full: {SOURCE_ID} / {MODEL_ID} / {FULL_ID}")
        print(f"Municipalities/fields/rows: {EXPECTED_MUNICIPALITIES} / {EXPECTED_FIELDS:,} / {EXPECTED_ROWS:,}")
        print(f"Full output SHA256: {FULL_OUTPUT_HASH}")
        print("STOPPUNKT A-D artifacts: HASH VERIFIED")
        print("Existing Score/Value/Drift/Minne: BYTE-IDENTICAL")
        print("Deployment/Sentinel-2: NO")
        print(f"Tag candidate: {TAG}")
        return 0
    except Exception as exc:
        trace.write_text(traceback.format_exc(), encoding="utf-8")
        print(traceback.format_exc())
        print(f"AKERNORM V1 FINAL FREEZE VERIFIER: FAIL — {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
