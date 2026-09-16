#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freeze the completed P95 review-only split-line proposal package.

This stage consumes the already generated 618-field P95 geometry-review package,
verifies its frozen D2C + human-audit lineage and exact output hashes/census, then
writes a separate immutable freeze package. It does not rerun B2/D2A, alter any
proposal geometry, tune thresholds, refit fusion/model state, or replace official
2025 geometry.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
EXPECTED_D2C_FREEZE_SHA256 = "60b021a5eef2483b54ea8d369ebbc7752c164ac51b113eb7faa524c9552be950"
EXPECTED_HUMAN_AUDIT_FREEZE_SHA256 = "5b5bc1d5c427d8a1c8fb54d03643cbb975cc4064c57d9086f69104b1864f9be4"
EXPECTED_SOURCE_STATUS = "PASS_TO_P95_SPLIT_LINE_HUMAN_REVIEW"
EXPECTED_P95_FIELDS = 618
EXPECTED_LINE_AVAILABLE = 613
EXPECTED_NO_INTERFACE = 5
EXPECTED_CHILD_FEATURES = 1236
DEFAULT_D2C = Path(r"C:\AkerSyncRepo\work\akerpuls_d2c_full_skane_freeze_review_v1")
SOURCE_DIRNAME = "d2c_p95_split_line_review_v1"
OUTPUT_DIRNAME = "d2c_p95_split_line_freeze_v1"
SOURCE_MANIFEST = "p95_split_line_review_manifest.json"
FREEZE_NAME = "P95_SPLIT_LINE_PROPOSAL_FREEZE_V1.json"
MANIFEST_NAME = "p95_split_line_freeze_manifest.json"

REQUIRED_SOURCE_OUTPUTS = {
    "p95_split_proposal_summary.csv",
    "p95_b2_child_evidence_review.gpkg",
    "p95_official_2025_parents_review.gpkg",
    "p95_raw_k2_interface_review.gpkg",
    "p95_primary_split_line_review.gpkg",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def verify_source(source: Path) -> tuple[dict[str, Any], Path]:
    manifest_path = source / SOURCE_MANIFEST
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    m = read_json(manifest_path)
    if m.get("schema_version") != "akerpuls-d2c-p95-split-line-review-v1":
        raise RuntimeError("Unexpected P95 split-line review manifest schema")
    if m.get("status") != EXPECTED_SOURCE_STATUS:
        raise RuntimeError(f"Source proposal status changed: {m.get('status')}")
    if m.get("parent_d2c_freeze_sha256") != EXPECTED_D2C_FREEZE_SHA256:
        raise RuntimeError("Source parent D2C freeze binding changed")
    if m.get("parent_human_audit_freeze_sha256") != EXPECTED_HUMAN_AUDIT_FREEZE_SHA256:
        raise RuntimeError("Source parent human-audit freeze binding changed")
    if int(m.get("p95_fields", -1)) != EXPECTED_P95_FIELDS:
        raise RuntimeError("P95 source census changed")
    if int(m.get("d2a_reconstruction_exact_fields", -1)) != EXPECTED_P95_FIELDS:
        raise RuntimeError("D2A exact reconstruction census changed")
    if int(m.get("b2_child_evidence_features", -1)) != EXPECTED_CHILD_FEATURES:
        raise RuntimeError("B2 child-evidence census changed")
    if int(m.get("line_available_fields", -1)) != EXPECTED_LINE_AVAILABLE:
        raise RuntimeError("Line-available census changed")
    if int(m.get("no_shared_interface_fields", -1)) != EXPECTED_NO_INTERFACE:
        raise RuntimeError("No-interface census changed")
    if m.get("selection_rule") != "EXACT_FROZEN_D2C_P95_TIER_ONLY_HUMAN_LABELS_NOT_USED":
        raise RuntimeError("P95 selection rule changed")

    gm = m.get("geometry_method", {})
    expected_gm = {
        "cluster_assignment": "EXACT_D2A_B2_DETERMINISTIC_K2_WITH_ALL_OWNER_FIELD_RASTERIZATION",
        "child_evidence": "FROZEN_B2_LARGEST_CONNECTED_COMPONENT_MASK_GEOM",
        "raw_interface": "SHARED_BOUNDARY_OF_FULL_K2_10M_PIXEL_LABEL_POLYGONS",
        "primary_line": "LONGEST_CONTIGUOUS_PART_OF_RAW_INTERFACE",
        "smoothing": False,
        "gap_filling": False,
    }
    if gm != expected_gm:
        raise RuntimeError(f"Geometry method changed: {gm}")

    guards = {
        "network_calls": int(m.get("network_calls", -1)) == 0,
        "model_refit": m.get("model_refit") is False,
        "thresholds_tuned": m.get("thresholds_tuned") is False,
        "fusion_refit": m.get("fusion_refit") is False,
        "merge_executed": m.get("merge_executed") is False,
        "human_labels_not_used": m.get("human_audit_labels_used_for_selection_or_geometry") is False,
        "official_2025_not_replaced": m.get("official_2025_geometry_replaced") is False,
        "automatic_geometry_mutation": m.get("automatic_geometry_mutation") is False,
        "review_only": m.get("review_only") is True,
    }
    if not all(guards.values()):
        raise RuntimeError(f"Source geometry guards changed: {guards}")

    outputs = m.get("output_hashes", {})
    if set(outputs) != REQUIRED_SOURCE_OUTPUTS:
        raise RuntimeError(f"Source output set changed: {sorted(outputs)}")
    for name in sorted(REQUIRED_SOURCE_OUTPUTS):
        rec = outputs[name]
        p = Path(rec["path"])
        if p.parent.resolve() != source.resolve() or p.name != name:
            raise RuntimeError(f"Source output escaped proposal directory: {p}")
        if not p.is_file():
            raise FileNotFoundError(p)
        got = sha256_file(p)
        if got != rec.get("sha256"):
            raise RuntimeError(f"Source proposal output hash changed: {name}")
        if int(p.stat().st_size) != int(rec.get("bytes", -1)):
            raise RuntimeError(f"Source proposal output byte size changed: {name}")

    summary_path = source / "p95_split_proposal_summary.csv"
    df = pd.read_csv(summary_path, encoding="utf-8-sig", dtype={"parent_field_id_2025": str})
    if len(df) != EXPECTED_P95_FIELDS or df.parent_field_id_2025.duplicated().any():
        raise RuntimeError("Proposal summary is not 618 unique P95 fields")
    counts = df.proposal_status.astype(str).value_counts().to_dict()
    if counts != {"LINE_AVAILABLE": EXPECTED_LINE_AVAILABLE, "NO_SHARED_INTERFACE": EXPECTED_NO_INTERFACE}:
        raise RuntimeError(f"Proposal status census changed: {counts}")
    if not bool(df.reconstructed_d2a_exact.astype(bool).all()):
        raise RuntimeError("Not every P95 proposal row is exact D2A reconstruction")
    return m, manifest_path


def verify_existing_freeze(out: Path) -> dict[str, Any]:
    manifest_path = out / MANIFEST_NAME
    freeze_path = out / FREEZE_NAME
    if not manifest_path.is_file() or not freeze_path.is_file():
        raise RuntimeError(f"Freeze directory exists but is incomplete: {out}")
    m = read_json(manifest_path)
    if m.get("status") != "FROZEN_P95_SPLIT_LINE_PROPOSALS_V1":
        raise RuntimeError("Existing freeze status changed")
    got = sha256_file(freeze_path)
    if got != m.get("proposal_freeze_sha256"):
        raise RuntimeError("Existing proposal freeze SHA changed")
    for rec in m.get("output_hashes", {}).values():
        p = Path(rec["path"])
        if not p.is_file() or sha256_file(p) != rec["sha256"]:
            raise RuntimeError(f"Existing freeze output changed: {p}")
    return m


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--d2c-dir", default=str(DEFAULT_D2C))
    args = ap.parse_args()

    head = git_guard()
    d2c = Path(args.d2c_dir)
    source = d2c / SOURCE_DIRNAME
    out = d2c / OUTPUT_DIRNAME

    print("P95_SPLIT_LINE_FREEZE_PROGRESS=VERIFY_EXACT_PROPOSAL_PACKAGE", flush=True)
    source_manifest, source_manifest_path = verify_source(source)
    source_manifest_sha = sha256_file(source_manifest_path)

    if out.exists():
        old = verify_existing_freeze(out)
        if old.get("source_proposal_manifest_sha256") != source_manifest_sha:
            raise RuntimeError("Existing freeze is bound to another source proposal manifest")
        print("AKERPULS D2C P95 SPLIT-LINE PROPOSAL FREEZE")
        print("STATUS=FROZEN_P95_SPLIT_LINE_PROPOSALS_V1_CACHED")
        print(f"PROPOSAL_FREEZE_SHA256={old['proposal_freeze_sha256']}")
        print(f"OUTPUT={out}")
        return 0

    source_hashes = {
        name: {
            "path": source_manifest["output_hashes"][name]["path"],
            "sha256": source_manifest["output_hashes"][name]["sha256"],
            "bytes": int(source_manifest["output_hashes"][name]["bytes"]),
        }
        for name in sorted(REQUIRED_SOURCE_OUTPUTS)
    }

    out.mkdir(parents=True, exist_ok=False)
    freeze = {
        "schema_version": "akerpuls-d2c-p95-split-line-proposal-freeze-v1",
        "status": "FROZEN_P95_SPLIT_LINE_PROPOSALS_V1",
        "frozen_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "parent_d2c_freeze_sha256": EXPECTED_D2C_FREEZE_SHA256,
        "parent_human_audit_freeze_sha256": EXPECTED_HUMAN_AUDIT_FREEZE_SHA256,
        "source_proposal_manifest": str(source_manifest_path),
        "source_proposal_manifest_sha256": source_manifest_sha,
        "p95_fields": EXPECTED_P95_FIELDS,
        "line_available_fields": EXPECTED_LINE_AVAILABLE,
        "no_shared_interface_fields": EXPECTED_NO_INTERFACE,
        "b2_child_evidence_features": EXPECTED_CHILD_FEATURES,
        "source_output_hashes": source_hashes,
        "selection_rule": "EXACT_FROZEN_D2C_P95_TIER_ONLY_HUMAN_LABELS_NOT_USED",
        "geometry_contract": source_manifest["geometry_method"],
        "guards": {
            "model_executed": False,
            "thresholds_tuned": False,
            "fusion_refit": False,
            "merge_executed": False,
            "smoothing": False,
            "gap_filling": False,
            "human_audit_labels_used_for_selection_or_geometry": False,
            "official_2025_geometry_replaced": False,
            "automatic_geometry_mutation": False,
            "review_only": True,
        },
        "next_step": "Build a separately blind, deterministic 100-field line-geometry audit viewer bound to this exact freeze SHA.",
    }
    freeze_path = out / FREEZE_NAME
    write_json(freeze_path, freeze)
    freeze_sha = sha256_file(freeze_path)

    report_path = out / "P95_SPLIT_LINE_PROPOSAL_FREEZE_REPORT_V1.md"
    report_path.write_text(
        "# ÅkerPuls P95 split-line proposal freeze v1\n\n"
        "Status: `FROZEN_P95_SPLIT_LINE_PROPOSALS_V1`\n\n"
        f"- P95 fields: {EXPECTED_P95_FIELDS}\n"
        f"- Line available: {EXPECTED_LINE_AVAILABLE}\n"
        f"- No shared interface: {EXPECTED_NO_INTERFACE}\n"
        f"- Child evidence features: {EXPECTED_CHILD_FEATURES}\n"
        "- Proposal geometry: raw 10 m K2 interface; primary = longest contiguous part.\n"
        "- No smoothing or gap filling.\n"
        "- No official 2025 geometry replacement.\n"
        f"- Source proposal manifest SHA256: `{source_manifest_sha}`\n"
        f"- Proposal freeze SHA256: `{freeze_sha}`\n",
        encoding="utf-8",
    )

    freeze_outputs = [freeze_path, report_path]
    output_hashes = {
        p.name: {"path": str(p), "sha256": sha256_file(p), "bytes": int(p.stat().st_size)}
        for p in freeze_outputs
    }
    manifest = {
        "schema_version": "akerpuls-d2c-p95-split-line-proposal-freeze-manifest-v1",
        "status": "FROZEN_P95_SPLIT_LINE_PROPOSALS_V1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "parent_d2c_freeze_sha256": EXPECTED_D2C_FREEZE_SHA256,
        "parent_human_audit_freeze_sha256": EXPECTED_HUMAN_AUDIT_FREEZE_SHA256,
        "source_proposal_manifest_sha256": source_manifest_sha,
        "proposal_freeze_sha256": freeze_sha,
        "p95_fields": EXPECTED_P95_FIELDS,
        "line_available_fields": EXPECTED_LINE_AVAILABLE,
        "no_shared_interface_fields": EXPECTED_NO_INTERFACE,
        "output_hashes": output_hashes,
        "model_executed": False,
        "thresholds_tuned": False,
        "fusion_refit": False,
        "merge_executed": False,
        "smoothing": False,
        "gap_filling": False,
        "official_2025_geometry_replaced": False,
        "automatic_geometry_mutation": False,
        "review_only": True,
    }
    manifest_path = out / MANIFEST_NAME
    write_json(manifest_path, manifest)

    print("AKERPULS D2C P95 SPLIT-LINE PROPOSAL FREEZE")
    print("STATUS=FROZEN_P95_SPLIT_LINE_PROPOSALS_V1")
    print(f"PARENT_D2C_FREEZE_SHA256={EXPECTED_D2C_FREEZE_SHA256}")
    print(f"PARENT_HUMAN_AUDIT_FREEZE_SHA256={EXPECTED_HUMAN_AUDIT_FREEZE_SHA256}")
    print(f"SOURCE_PROPOSAL_MANIFEST_SHA256={source_manifest_sha}")
    print(f"P95_FIELDS={EXPECTED_P95_FIELDS} LINE_AVAILABLE_FIELDS={EXPECTED_LINE_AVAILABLE} NO_SHARED_INTERFACE_FIELDS={EXPECTED_NO_INTERFACE}")
    print(f"PROPOSAL_FREEZE_SHA256={freeze_sha}")
    print("SMOOTHING=FALSE GAP_FILLING=FALSE MODEL_EXECUTED=FALSE THRESHOLDS_TUNED=FALSE FUSION_REFIT=FALSE")
    print("OFFICIAL_2025_GEOMETRY_REPLACED=FALSE AUTOMATIC_GEOMETRY_MUTATION=FALSE REVIEW_ONLY=TRUE")
    print("NEXT=BLIND_100_FIELD_LINE_GEOMETRY_AUDIT_VIEWER")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
