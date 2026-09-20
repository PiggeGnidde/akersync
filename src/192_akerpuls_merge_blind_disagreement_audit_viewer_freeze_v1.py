#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Formal freeze of the pre-label blind merge disagreement audit viewer V1B.

Verifies the already-built 4x25 blind viewer/sample and rendering artefacts.
Does not reveal/open blind-key contents beyond hashing the file. Does not create
human labels, perform fusion, select sign, tune thresholds, merge, or mutate geometry.
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
EXPECTED_SOURCE_GIT_HEAD = "8e59dd6f83b5819bf5f5aab83fa1018521aa35bd"

SOURCE_DIR = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_blind_disagreement_audit_viewer_v1b")
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_blind_disagreement_audit_viewer_freeze_v1")
STATUS = "FROZEN_AKERPULS_MERGE_BLIND_DISAGREEMENT_AUDIT_VIEWER_V1"

EXPECTED_M2_FREEZE_SHA256 = "54a567c2a198e9724761f131d6fb6b438b3df897358f461cc41349cf4175c859"
EXPECTED_SAMPLE_POPULATION_SHA256 = "c2e22aee44e012e11a77f76baec0218aec74557e644537c9d9e808a6cc2d39bb"
EXPECTED_BLIND_KEY_SHA256 = "706d800769ac2bd1eb9deb5ff6d035aaef2407b4586501bd2a0cfc5ad87feeee"
EXPECTED_ASSESSABLE = 22358
EXPECTED_SAMPLE = 100
EXPECTED_PER_STRATUM = 25
EXPECTED_STRATUM_COUNTS = {"HH": 1011, "HL": 54, "LH": 335, "LL": 533}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def verify_source(src: Path) -> dict:
    manifest_path = src / "MERGE_BLIND_DISAGREEMENT_AUDIT_VIEWER_MANIFEST_V1.json"
    html_path = src / "index.html"
    validity_path = src / "blind_pair_validity.json"
    blind_key_path = src / "BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv"
    image_dir = src / "images"

    for p in (manifest_path, html_path, validity_path, blind_key_path):
        if not p.is_file():
            raise FileNotFoundError(p)
    if not image_dir.is_dir():
        raise FileNotFoundError(image_dir)

    manifest = read_json(manifest_path)
    if manifest.get("schema_version") != "akerpuls-merge-blind-disagreement-audit-viewer-v1b":
        raise RuntimeError("Unexpected blind-audit manifest schema")
    if manifest.get("status") != "PASS_TO_BLIND_MERGE_DISAGREEMENT_AUDIT_V1B":
        raise RuntimeError(f"Unexpected viewer source status: {manifest.get('status')}")
    if manifest.get("git_head") != EXPECTED_SOURCE_GIT_HEAD:
        raise RuntimeError(f"Unexpected viewer source git head: {manifest.get('git_head')}")
    if manifest.get("parent_m2_diagnostic_freeze_sha256") != EXPECTED_M2_FREEZE_SHA256:
        raise RuntimeError("Viewer does not pin expected M2 freeze")
    if int(manifest.get("assessable_population", -1)) != EXPECTED_ASSESSABLE:
        raise RuntimeError("Assessable population changed")

    sample = manifest.get("sample", {})
    if int(sample.get("rows", -1)) != EXPECTED_SAMPLE:
        raise RuntimeError("Audit sample size changed")
    if int(sample.get("per_stratum", -1)) != EXPECTED_PER_STRATUM:
        raise RuntimeError("Per-stratum sample size changed")
    if sample.get("stratum_population_counts") != EXPECTED_STRATUM_COUNTS:
        raise RuntimeError(f"Stratum population counts changed: {sample.get('stratum_population_counts')}")
    if sample.get("sample_population_sha256") != EXPECTED_SAMPLE_POPULATION_SHA256:
        raise RuntimeError("Sample population SHA changed")
    if sample.get("design_revision") != "V1B_AFTER_PRELABEL_V1_FEASIBILITY_STOP_HL14":
        raise RuntimeError("Audit design-revision provenance changed")
    if float(sample.get("m0_tail_fraction", -1)) != 0.10 or float(sample.get("m1_tail_fraction", -1)) != 0.25:
        raise RuntimeError("Audit tail fractions changed")
    if sample.get("v1_failed_prelabel_stratum_counts") != {"HH": 433, "HL": 14, "LH": 36, "LL": 181}:
        raise RuntimeError("V1 pre-label feasibility provenance changed")

    if manifest.get("blind_key_sha256") != EXPECTED_BLIND_KEY_SHA256:
        raise RuntimeError("Manifest blind-key SHA changed")
    if sha256_file(blind_key_path) != EXPECTED_BLIND_KEY_SHA256:
        raise RuntimeError("Blind-key file SHA changed")

    if sha256_file(html_path) != manifest.get("html_sha256"):
        raise RuntimeError("Viewer HTML changed")
    if sha256_file(validity_path) != manifest.get("validity_sha256"):
        raise RuntimeError("Blind validity file changed")

    image_hashes = manifest.get("image_hashes", {})
    if len(image_hashes) != EXPECTED_SAMPLE:
        raise RuntimeError(f"Expected {EXPECTED_SAMPLE} rendered audit images, got {len(image_hashes)}")
    expected_names = {f"audit_{i:03d}.jpg" for i in range(1, EXPECTED_SAMPLE + 1)}
    if set(image_hashes) != expected_names:
        raise RuntimeError("Rendered image-name set changed")
    for name, expected in image_hashes.items():
        p = image_dir / name
        if not p.is_file():
            raise FileNotFoundError(p)
        if sha256_file(p) != expected:
            raise RuntimeError(f"Rendered image changed: {name}")

    blind = manifest.get("blindness", {})
    for k in ("scores_visible", "stratum_visible", "pair_id_visible", "m0_status_visible"):
        if blind.get(k) is not False:
            raise RuntimeError(f"Blindness guard changed: {k}")
    if blind.get("blind_key_must_remain_closed_until_labels_exported_and_frozen") is not True:
        raise RuntimeError("Blind-key close-until-label-freeze rule changed")

    guards = manifest.get("guards", {})
    required_false = [
        "fusion_executed", "fusion_score_created", "sign_selected",
        "human_labels_used_for_sampling", "thresholds_tuned",
        "automatic_merge", "geometry_mutated",
    ]
    if any(guards.get(k) is not False for k in required_false):
        raise RuntimeError(f"Viewer guard changed: {guards}")
    if guards.get("review_only") is not True:
        raise RuntimeError("Viewer is no longer review-only")

    return {
        "source_manifest_sha256": sha256_file(manifest_path),
        "html_sha256": sha256_file(html_path),
        "validity_sha256": sha256_file(validity_path),
        "blind_key_sha256": EXPECTED_BLIND_KEY_SHA256,
        "sample_population_sha256": EXPECTED_SAMPLE_POPULATION_SHA256,
        "image_count": len(image_hashes),
        "image_hashes": image_hashes,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-dir", default=str(SOURCE_DIR))
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    head = git_guard()
    src = Path(args.source_dir)
    out = Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Freeze output already exists: {out}")

    verified = verify_source(src)

    freeze = {
        "schema_version": "akerpuls-merge-blind-disagreement-audit-viewer-freeze-v1",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "freeze_git_head": head,
        "source_git_head": EXPECTED_SOURCE_GIT_HEAD,
        "parent_m2_diagnostic_freeze_sha256": EXPECTED_M2_FREEZE_SHA256,
        "source_dir": str(src),
        "sample": {
            "assessable_population": EXPECTED_ASSESSABLE,
            "rows": EXPECTED_SAMPLE,
            "per_stratum": EXPECTED_PER_STRATUM,
            "stratum_population_counts": EXPECTED_STRATUM_COUNTS,
            "sample_population_sha256": EXPECTED_SAMPLE_POPULATION_SHA256,
            "design": "M0_TOP_BOTTOM_10_PERCENT__M1_TOP_BOTTOM_25_PERCENT",
        },
        "source_hashes": verified,
        "contract": {
            "pre_label_freeze": True,
            "blind_key_contents_revealed": False,
            "human_labels_created": False,
            "scores_visible": False,
            "stratum_visible": False,
            "pair_id_visible": False,
            "m0_status_visible": False,
            "fusion_executed": False,
            "sign_selected": False,
            "thresholds_tuned": False,
            "automatic_merge": False,
            "geometry_mutated": False,
        },
        "next": "COMPLETE_100_BLIND_LABELS_EXPORT_CSV_THEN_FREEZE_LABELS_BEFORE_REVEAL",
    }

    out.mkdir(parents=True, exist_ok=False)
    freeze_path = out / "AKERPULS_MERGE_BLIND_DISAGREEMENT_AUDIT_VIEWER_FREEZE_V1.json"
    freeze_path.write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    freeze_sha = sha256_file(freeze_path)
    (out / "AKERPULS_MERGE_BLIND_DISAGREEMENT_AUDIT_VIEWER_FREEZE_V1.sha256").write_text(
        freeze_sha + "  AKERPULS_MERGE_BLIND_DISAGREEMENT_AUDIT_VIEWER_FREEZE_V1.json\n",
        encoding="utf-8",
    )
    shutil.copyfile(
        src / "MERGE_BLIND_DISAGREEMENT_AUDIT_VIEWER_MANIFEST_V1.json",
        out / "SOURCE_VIEWER_MANIFEST.json",
    )

    print("AKERPULS MERGE BLIND DISAGREEMENT AUDIT VIEWER FORMAL FREEZE")
    print(f"STATUS={STATUS}")
    print(f"SOURCE_GIT_HEAD={EXPECTED_SOURCE_GIT_HEAD}")
    print(f"FREEZE_GIT_HEAD={head}")
    print(f"M2_DIAGNOSTIC_FREEZE_SHA256={EXPECTED_M2_FREEZE_SHA256}")
    print(f"AUDIT_VIEWER_FREEZE_SHA256={freeze_sha}")
    print(f"ASSESSABLE_POPULATION={EXPECTED_ASSESSABLE} SAMPLE={EXPECTED_SAMPLE} PER_STRATUM={EXPECTED_PER_STRATUM}")
    print("STRATUM_COUNTS=" + " | ".join(f"{k}:{v}" for k, v in EXPECTED_STRATUM_COUNTS.items()))
    print(f"SAMPLE_POPULATION_SHA256={EXPECTED_SAMPLE_POPULATION_SHA256}")
    print(f"BLIND_KEY_SHA256={EXPECTED_BLIND_KEY_SHA256}")
    print(f"RENDERED_IMAGES_VERIFIED={verified['image_count']}")
    print("BLIND_KEY_CONTENTS_REVEALED=FALSE HUMAN_LABELS_CREATED=FALSE")
    print("FUSION_EXECUTED=FALSE SIGN_SELECTED=FALSE THRESHOLDS_TUNED=FALSE AUTOMATIC_MERGE=FALSE GEOMETRY_MUTATED=FALSE")
    print("NEXT=COMPLETE_100_BLIND_LABELS_EXPORT_CSV_THEN_FREEZE_LABELS_BEFORE_REVEAL")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
