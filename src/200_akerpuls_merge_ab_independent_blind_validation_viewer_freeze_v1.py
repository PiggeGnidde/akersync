#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Formal pre-label freeze of independent blind A/B merge validation viewer.

Validates the deterministic 50 A + 50 B sample, explicit exclusion of all
100 first-audit pairs, browser blindness, source hashes and all 100 rendered
images. The blind-key CSV is never parsed; only its SHA256 is checked.

No human labels, no reveal, no fusion, no threshold tuning, no automatic merge,
no cross-block merge, no geometry mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
EXPECTED_SOURCE_GIT_HEAD = "671b8e69cb4be79fe6b69ca690ef1514fbd9557a"

SRC = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_ab_independent_blind_validation_viewer_v1")
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_ab_independent_blind_validation_viewer_freeze_v1")
STATUS = "FROZEN_AKERPULS_MERGE_AB_INDEPENDENT_BLIND_VALIDATION_VIEWER_V1"

EXPECTED_RANKING_FREEZE_SHA = "2f98d504c61ba71da396e4d459ffd6b3e5d2feaacbe5a8faaab9635d2882ef26"
EXPECTED_FIRST_JOIN_SHA = "bce010ece5982599231117e83fb301f3391b78b00e5d6e39abc700588b63e284"
EXPECTED_EXCLUSION_SET_SHA = "c2e22aee44e012e11a77f76baec0218aec74557e644537c9d9e808a6cc2d39bb"
EXPECTED_SAMPLE_POPULATION_SHA = "f5df348a57660df3eadbd8ab7c0bc35b90985b9f22f5540735e2cf56bf0ed677"
EXPECTED_BLIND_KEY_SHA = "fec621243d0b7cefc33d345be6ee361bd06cdba802a2d72b3925fa3257f7dc5f"
EXPECTED_SAMPLE = 100
EXPECTED_PER_TIER = 50
EXPECTED_ELIGIBLE = {"A_CONFIRMED_HIGH": 986, "B_SAT_HIGH_H_MID": 1171}


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
    if subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip():
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-dir", default=str(SRC))
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    head = git_guard()
    src = Path(args.source_dir)
    out = Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Freeze output already exists: {out}")

    manifest_path = src / "AB_INDEPENDENT_VALIDATION_VIEWER_MANIFEST_V1.json"
    html_path = src / "index.html"
    validity_path = src / "validation_pair_validity.json"
    key_path = src / "AB_VALIDATION_BLIND_KEY_DO_NOT_OPEN.csv"
    imgdir = src / "images"

    for p in (manifest_path, html_path, validity_path, key_path):
        if not p.is_file():
            raise FileNotFoundError(p)
    if not imgdir.is_dir():
        raise FileNotFoundError(imgdir)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest.get("status") != "PASS_TO_INDEPENDENT_BLIND_AB_VALIDATION":
        raise RuntimeError("Unexpected source viewer status")
    if manifest.get("git_head") != EXPECTED_SOURCE_GIT_HEAD:
        raise RuntimeError("Unexpected source viewer git head")

    parents = manifest.get("parents", {})
    if parents.get("sh_gated_ranking_freeze_sha256") != EXPECTED_RANKING_FREEZE_SHA:
        raise RuntimeError("Ranking-freeze lineage changed")
    if parents.get("first_audit_revealed_join_sha256") != EXPECTED_FIRST_JOIN_SHA:
        raise RuntimeError("First-audit lineage changed")

    smp = manifest.get("sampling", {})
    if smp.get("tiers") != ["A_CONFIRMED_HIGH", "B_SAT_HIGH_H_MID"]:
        raise RuntimeError("Tier design changed")
    if int(smp.get("per_tier", -1)) != EXPECTED_PER_TIER or int(smp.get("rows", -1)) != EXPECTED_SAMPLE:
        raise RuntimeError("Sample size changed")
    if smp.get("eligible_after_exclusion") != EXPECTED_ELIGIBLE:
        raise RuntimeError(f"Eligible census changed: {smp.get('eligible_after_exclusion')}")
    if int(smp.get("first_audit_pairs_excluded", -1)) != 100:
        raise RuntimeError("First-audit exclusion count changed")
    if smp.get("first_audit_exclusion_set_sha256") != EXPECTED_EXCLUSION_SET_SHA:
        raise RuntimeError("First-audit exclusion set changed")
    if smp.get("sample_population_sha256") != EXPECTED_SAMPLE_POPULATION_SHA:
        raise RuntimeError("Validation sample changed")
    if smp.get("human_labels_used_for_sampling") is not False:
        raise RuntimeError("Human labels contaminated sampling")

    if manifest.get("blind_key_sha256") != EXPECTED_BLIND_KEY_SHA:
        raise RuntimeError("Manifest blind-key SHA changed")
    # Hash only; do not parse/read semantic contents of the blind key.
    if sha256_file(key_path) != EXPECTED_BLIND_KEY_SHA:
        raise RuntimeError("Blind-key file bytes changed")

    blindness = manifest.get("blindness", {})
    for k in ("tier_visible", "scores_visible", "pair_id_visible", "field_ids_visible", "m0_status_visible"):
        if blindness.get(k) is not False:
            raise RuntimeError(f"Blindness contract changed: {k}")
    if blindness.get("blind_key_must_remain_closed_until_labels_exported_and_frozen") is not True:
        raise RuntimeError("Blind-key closure contract changed")

    policy = manifest.get("policy", {})
    if policy.get("block_boundary_hard_wall") is not True:
        raise RuntimeError("Block hard-wall policy changed")
    if policy.get("cross_block_merge_allowed") is not False:
        raise RuntimeError("Cross-block policy changed")
    if policy.get("automatic_merge") is not False or policy.get("geometry_mutated") is not False:
        raise RuntimeError("Operational policy changed")

    guards = manifest.get("guards", {})
    for k in ("fusion_executed", "fusion_weight_selected", "thresholds_tuned", "automatic_merge", "geometry_mutated"):
        if guards.get(k) is not False:
            raise RuntimeError(f"Guard changed: {k}")

    if sha256_file(html_path) != manifest.get("html_sha256"):
        raise RuntimeError("index.html hash mismatch")
    if sha256_file(validity_path) != manifest.get("validity_sha256"):
        raise RuntimeError("validity JSON hash mismatch")

    image_hashes = manifest.get("image_hashes", {})
    if len(image_hashes) != EXPECTED_SAMPLE:
        raise RuntimeError(f"Expected 100 image hashes, got {len(image_hashes)}")
    actual_images = sorted(p.name for p in imgdir.glob("*.jpg"))
    if len(actual_images) != EXPECTED_SAMPLE or set(actual_images) != set(image_hashes):
        raise RuntimeError("Rendered image census/name set changed")
    for name, expected_sha in image_hashes.items():
        if sha256_file(imgdir / name) != expected_sha:
            raise RuntimeError(f"Rendered image hash changed: {name}")

    pre = manifest.get("predeclared_analysis", {})
    if pre.get("primary_endpoint") != "broad_positive = TYDLIG_MERGE + MÖJLIG_MERGE among assessable":
        raise RuntimeError("Primary endpoint changed")
    if pre.get("secondary_endpoint") != "strict_positive = TYDLIG_MERGE among assessable":
        raise RuntimeError("Secondary endpoint changed")
    if pre.get("primary_contrast") != "A_CONFIRMED_HIGH vs B_SAT_HIGH_H_MID":
        raise RuntimeError("Primary contrast changed")

    source_manifest_sha = sha256_file(manifest_path)
    freeze = {
        "schema_version": "akerpuls-merge-ab-independent-blind-validation-viewer-freeze-v1",
        "status": STATUS,
        "source_git_head": EXPECTED_SOURCE_GIT_HEAD,
        "freeze_git_head": head,
        "parents": {
            "sh_gated_ranking_freeze_sha256": EXPECTED_RANKING_FREEZE_SHA,
            "first_audit_revealed_join_sha256": EXPECTED_FIRST_JOIN_SHA,
        },
        "sample": {
            "rows": EXPECTED_SAMPLE,
            "per_tier": EXPECTED_PER_TIER,
            "eligible_after_exclusion": EXPECTED_ELIGIBLE,
            "first_audit_pairs_excluded": 100,
            "first_audit_exclusion_set_sha256": EXPECTED_EXCLUSION_SET_SHA,
            "sample_population_sha256": EXPECTED_SAMPLE_POPULATION_SHA,
        },
        "source_hashes": {
            "source_manifest_sha256": source_manifest_sha,
            "index_html_sha256": sha256_file(html_path),
            "validity_sha256": sha256_file(validity_path),
            "blind_key_sha256": EXPECTED_BLIND_KEY_SHA,
            "rendered_images_verified": EXPECTED_SAMPLE,
        },
        "predeclared_analysis": pre,
        "contract": {
            "viewer_and_sample_frozen_before_human_labels": True,
            "blind_key_contents_revealed": False,
            "human_labels_created": False,
            "tier_visible": False,
            "scores_visible": False,
            "pair_id_visible": False,
            "field_ids_visible": False,
            "block_boundary_hard_wall": True,
            "cross_block_merge_allowed": False,
            "fusion_executed": False,
            "thresholds_tuned": False,
            "automatic_merge": False,
            "geometry_mutated": False,
        },
        "next": "COMPLETE_100_BLIND_AB_VALIDATION_LABELS_THEN_FREEZE_LABELS_BEFORE_REVEAL",
    }

    out.mkdir(parents=True, exist_ok=False)
    fp = out / "AKERPULS_MERGE_AB_INDEPENDENT_BLIND_VALIDATION_VIEWER_FREEZE_V1.json"
    fp.write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fsha = sha256_file(fp)
    (out / "AKERPULS_MERGE_AB_INDEPENDENT_BLIND_VALIDATION_VIEWER_FREEZE_V1.sha256").write_text(
        fsha + "  AKERPULS_MERGE_AB_INDEPENDENT_BLIND_VALIDATION_VIEWER_FREEZE_V1.json\n",
        encoding="utf-8",
    )
    shutil.copyfile(manifest_path, out / "SOURCE_AB_INDEPENDENT_VALIDATION_VIEWER_MANIFEST_V1.json")

    print("AKERPULS MERGE A/B INDEPENDENT BLIND VALIDATION VIEWER FORMAL FREEZE")
    print(f"STATUS={STATUS}")
    print(f"SOURCE_GIT_HEAD={EXPECTED_SOURCE_GIT_HEAD}")
    print(f"FREEZE_GIT_HEAD={head}")
    print(f"SH_GATED_RANKING_FREEZE_SHA256={EXPECTED_RANKING_FREEZE_SHA}")
    print(f"VIEWER_FREEZE_SHA256={fsha}")
    print(f"SOURCE_MANIFEST_SHA256={source_manifest_sha}")
    print(f"SAMPLE_POPULATION_SHA256={EXPECTED_SAMPLE_POPULATION_SHA}")
    print(f"BLIND_KEY_SHA256={EXPECTED_BLIND_KEY_SHA}")
    print("SAMPLE=A:50 | B:50 | TOTAL:100")
    print("FIRST_AUDIT_EXCLUDED=100")
    print("RENDERED_IMAGES_VERIFIED=100")
    print("BLIND_KEY_CONTENTS_REVEALED=FALSE HUMAN_LABELS_CREATED=FALSE")
    print("BLOCK_BOUNDARY_HARD_WALL=TRUE CROSS_BLOCK_MERGE_ALLOWED=FALSE")
    print("FUSION_EXECUTED=FALSE THRESHOLDS_TUNED=FALSE AUTOMATIC_MERGE=FALSE GEOMETRY_MUTATED=FALSE")
    print("NEXT=COMPLETE_100_BLIND_AB_VALIDATION_LABELS_THEN_FREEZE_LABELS_BEFORE_REVEAL")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
