#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freeze the completed blind P95 line-geometry audit before reveal.

Consumes the exact exported 100-row geometry-audit CSV, verifies its SHA256,
proposal-freeze binding, blind-key binding and predeclared label domains/counts,
then writes a separate immutable freeze package. The blind key is NOT opened or
joined here; reveal happens only after this freeze succeeds locally.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
DEFAULT_D2C = Path(r"C:\AkerSyncRepo\work\akerpuls_d2c_full_skane_freeze_review_v1")
VIEWER_DIRNAME = "d2c_p95_geometry_audit_viewer_v1"
VIEWER_MANIFEST = "p95_geometry_audit_viewer_manifest.json"
FREEZE_DIRNAME = "d2c_p95_geometry_audit_freeze_v1"
FREEZE_NAME = "P95_GEOMETRY_AUDIT_FREEZE_V1.json"
MANIFEST_NAME = "p95_geometry_audit_freeze_manifest.json"

EXPECTED_PROPOSAL_FREEZE_SHA256 = "d3a06356fdd941b47c713535c1f00b388b09a4f23f61acf276528c8f5929e30a"
EXPECTED_LABELS_SHA256 = "3b9be03ea440eebf581e4f80e5a84a825a81a972ab0a44f4dfd3a2c16254d76a"
EXPECTED_BLIND_KEY_SHA256 = "75515e0f1bd7f0466657317d7176be535f73da06a3505f2bad68b3190b33b428"
EXPECTED_ROWS = 100
SPLIT_LABELS = ["TYDLIG_SPLIT", "MÖJLIG_SPLIT", "TVEKSAM", "FALSK_SPLIT", "EJ_BEDÖMBAR"]
LINE_LABELS = ["RATT_GRANS", "NARA_GRANS", "FEL_GRANS", "EJ_BEDOMBAR", "EJ_TILLAMPLIG"]
EXPECTED_SPLIT_COUNTS = {
    "TYDLIG_SPLIT": 64, "MÖJLIG_SPLIT": 16, "TVEKSAM": 12,
    "FALSK_SPLIT": 8, "EJ_BEDÖMBAR": 0,
}
EXPECTED_LINE_COUNTS = {
    "RATT_GRANS": 76, "NARA_GRANS": 5, "FEL_GRANS": 2,
    "EJ_BEDOMBAR": 0, "EJ_TILLAMPLIG": 17,
}
PREDECLARED_ANALYSIS = {
    "split_positive_for_geometry": ["TYDLIG_SPLIT", "MÖJLIG_SPLIT"],
    "split_ambiguous": ["TVEKSAM"],
    "split_negative": ["FALSK_SPLIT"],
    "line_strict_positive": ["RATT_GRANS"],
    "line_broad_positive": ["RATT_GRANS", "NARA_GRANS"],
    "line_negative": ["FEL_GRANS"],
    "line_excluded": ["EJ_BEDOMBAR", "EJ_TILLAMPLIG"],
    "joint_strict_success": "split in {TYDLIG_SPLIT,MOJLIG_SPLIT} AND line=RATT_GRANS",
    "joint_broad_success": "split in {TYDLIG_SPLIT,MOJLIG_SPLIT} AND line in {RATT_GRANS,NARA_GRANS}",
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


def verify_viewer(d2c: Path) -> dict[str, Any]:
    p = d2c / VIEWER_DIRNAME / VIEWER_MANIFEST
    if not p.is_file():
        raise FileNotFoundError(p)
    m = read_json(p)
    if m.get("status") != "PASS_TO_BLIND_P95_LINE_GEOMETRY_AUDIT":
        raise RuntimeError(f"Viewer status changed: {m.get('status')}")
    if m.get("parent_proposal_freeze_sha256") != EXPECTED_PROPOSAL_FREEZE_SHA256:
        raise RuntimeError("Viewer proposal-freeze binding changed")
    if int(m.get("audit_sample", -1)) != EXPECTED_ROWS:
        raise RuntimeError("Viewer audit sample changed")
    if m.get("blind_key_sha256") != EXPECTED_BLIND_KEY_SHA256:
        raise RuntimeError("Viewer blind-key SHA changed")
    if m.get("predeclared_analysis") != PREDECLARED_ANALYSIS:
        raise RuntimeError("Viewer predeclared analysis changed")
    guards = {
        "field_id_hidden": m.get("field_id_visible") is False,
        "fusion_hidden": m.get("fusion_score_visible") is False,
        "previous_audit_hidden": m.get("previous_human_audit_visible") is False,
        "geometry_metrics_hidden": m.get("geometry_metrics_visible") is False,
        "model_not_executed": m.get("model_executed") is False,
        "thresholds_not_tuned": m.get("thresholds_tuned") is False,
        "fusion_not_refit": m.get("fusion_refit") is False,
        "smoothing_false": m.get("smoothing") is False,
        "gap_filling_false": m.get("gap_filling") is False,
        "review_only": m.get("review_only") is True,
    }
    if not all(guards.values()):
        raise RuntimeError(f"Viewer guards changed: {guards}")
    return m


def validate_labels(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    got_sha = sha256_file(path)
    if got_sha != EXPECTED_LABELS_SHA256:
        raise RuntimeError(f"Geometry-audit labels SHA changed: {got_sha}")
    df = pd.read_csv(path, encoding="utf-8-sig", dtype={"blind_index": int})
    req = {"parent_proposal_freeze_sha256", "blind_key_sha256", "blind_index", "split_label", "line_label", "note"}
    if set(df.columns) != req:
        raise RuntimeError(f"Unexpected labels columns: {list(df.columns)}")
    if len(df) != EXPECTED_ROWS or df.blind_index.duplicated().any():
        raise RuntimeError("Expected 100 unique blind-index rows")
    if sorted(df.blind_index.tolist()) != list(range(1, EXPECTED_ROWS + 1)):
        raise RuntimeError("blind_index domain changed")
    if set(df.parent_proposal_freeze_sha256.astype(str)) != {EXPECTED_PROPOSAL_FREEZE_SHA256}:
        raise RuntimeError("Labels proposal-freeze binding changed")
    if set(df.blind_key_sha256.astype(str)) != {EXPECTED_BLIND_KEY_SHA256}:
        raise RuntimeError("Labels blind-key binding changed")
    if df.split_label.isna().any() or df.line_label.isna().any():
        raise RuntimeError("Missing split/line labels")
    bad_split = sorted(set(df.split_label.astype(str)) - set(SPLIT_LABELS))
    bad_line = sorted(set(df.line_label.astype(str)) - set(LINE_LABELS))
    if bad_split or bad_line:
        raise RuntimeError(f"Unknown labels: split={bad_split} line={bad_line}")
    sc = {k: int((df.split_label.astype(str) == k).sum()) for k in SPLIT_LABELS}
    lc = {k: int((df.line_label.astype(str) == k).sum()) for k in LINE_LABELS}
    if sc != EXPECTED_SPLIT_COUNTS or lc != EXPECTED_LINE_COUNTS:
        raise RuntimeError(f"Frozen count table changed: split={sc} line={lc}")
    return df


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("labels_csv")
    ap.add_argument("--d2c-dir", default=str(DEFAULT_D2C))
    args = ap.parse_args()

    head = git_guard()
    d2c = Path(args.d2c_dir)
    labels_path = Path(args.labels_csv)
    print("P95_GEOMETRY_AUDIT_FREEZE_PROGRESS=VERIFY_BLIND_LABEL_EXPORT_WITHOUT_REVEAL", flush=True)
    viewer = verify_viewer(d2c)
    df = validate_labels(labels_path)

    split_pos = df.split_label.astype(str).isin(["TYDLIG_SPLIT", "MÖJLIG_SPLIT"])
    strict_joint = int((split_pos & df.line_label.astype(str).eq("RATT_GRANS")).sum())
    broad_joint = int((split_pos & df.line_label.astype(str).isin(["RATT_GRANS", "NARA_GRANS"])).sum())
    split_counts = {k: int((df.split_label.astype(str) == k).sum()) for k in SPLIT_LABELS}
    line_counts = {k: int((df.line_label.astype(str) == k).sum()) for k in LINE_LABELS}
    cross = pd.crosstab(df.split_label.astype(str), df.line_label.astype(str), dropna=False)
    cross_table = {
        s: {l: int(cross.loc[s, l]) if s in cross.index and l in cross.columns else 0 for l in LINE_LABELS}
        for s in SPLIT_LABELS
    }

    out = d2c / FREEZE_DIRNAME
    if out.exists():
        mp = out / MANIFEST_NAME; fp = out / FREEZE_NAME
        if not mp.is_file() or not fp.is_file():
            raise RuntimeError(f"Existing freeze directory incomplete: {out}")
        old = read_json(mp)
        if old.get("source_labels_sha256") != EXPECTED_LABELS_SHA256:
            raise RuntimeError("Existing freeze belongs to another labels export")
        if sha256_file(fp) != old.get("geometry_audit_freeze_sha256"):
            raise RuntimeError("Existing geometry-audit freeze changed")
        print("AKERPULS D2C P95 GEOMETRY AUDIT FREEZE")
        print("STATUS=FROZEN_P95_GEOMETRY_AUDIT_V1_CACHED")
        print(f"GEOMETRY_AUDIT_FREEZE_SHA256={old['geometry_audit_freeze_sha256']}")
        print(f"OUTPUT={out}")
        return 0

    out.mkdir(parents=True, exist_ok=False)
    freeze = {
        "schema_version": "akerpuls-d2c-p95-geometry-audit-freeze-v1",
        "status": "FROZEN_P95_GEOMETRY_AUDIT_V1",
        "frozen_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "parent_proposal_freeze_sha256": EXPECTED_PROPOSAL_FREEZE_SHA256,
        "source_labels_sha256": EXPECTED_LABELS_SHA256,
        "blind_key_sha256": EXPECTED_BLIND_KEY_SHA256,
        "audit_rows": EXPECTED_ROWS,
        "sample_population_sha256": viewer.get("sample_population_sha256"),
        "predeclared_analysis": PREDECLARED_ANALYSIS,
        "split_counts": split_counts,
        "line_counts": line_counts,
        "cross_table": cross_table,
        "pre_reveal_joint_counts": {
            "split_positive_n": int(split_pos.sum()),
            "joint_strict_success_n": strict_joint,
            "joint_broad_success_n": broad_joint,
        },
        "blind_key_opened_by_this_stage": False,
        "reveal_executed": False,
        "model_executed": False,
        "thresholds_tuned": False,
        "fusion_refit": False,
        "smoothing": False,
        "gap_filling": False,
        "official_2025_geometry_replaced": False,
        "review_only": True,
        "next_step": "Reveal blind key only after this freeze; then estimate split and line-geometry performance for the frozen 100/613 sample.",
    }
    freeze_path = out / FREEZE_NAME
    write_json(freeze_path, freeze)
    freeze_sha = sha256_file(freeze_path)

    report_path = out / "P95_GEOMETRY_AUDIT_FREEZE_REPORT_V1.md"
    report_path.write_text(
        "# ÅkerPuls P95 geometry audit freeze v1\n\n"
        "Status: `FROZEN_P95_GEOMETRY_AUDIT_V1`\n\n"
        f"- Labels SHA256: `{EXPECTED_LABELS_SHA256}`\n"
        f"- Blind-key SHA256: `{EXPECTED_BLIND_KEY_SHA256}` (not opened by freeze stage)\n"
        "- Split: 64 tydlig, 16 möjlig, 12 tveksam, 8 falsk, 0 ej bedömbar.\n"
        "- Line: 76 rätt, 5 nära, 2 fel, 0 ej bedömbar, 17 ej tillämplig.\n"
        f"- Pre-reveal split-positive: {int(split_pos.sum())}/100.\n"
        f"- Pre-reveal joint strict: {strict_joint}/100; broad: {broad_joint}/100.\n"
        "- No model/threshold/fusion/geometry mutation.\n"
        f"- Freeze SHA256: `{freeze_sha}`\n",
        encoding="utf-8",
    )
    output_hashes = {
        p.name: {"path": str(p), "sha256": sha256_file(p), "bytes": int(p.stat().st_size)}
        for p in (freeze_path, report_path)
    }
    manifest = {
        "schema_version": "akerpuls-d2c-p95-geometry-audit-freeze-manifest-v1",
        "status": "FROZEN_P95_GEOMETRY_AUDIT_V1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "parent_proposal_freeze_sha256": EXPECTED_PROPOSAL_FREEZE_SHA256,
        "source_labels_sha256": EXPECTED_LABELS_SHA256,
        "blind_key_sha256": EXPECTED_BLIND_KEY_SHA256,
        "geometry_audit_freeze_sha256": freeze_sha,
        "output_hashes": output_hashes,
        "blind_key_opened": False,
        "reveal_executed": False,
        "model_executed": False,
        "thresholds_tuned": False,
        "fusion_refit": False,
        "official_2025_geometry_replaced": False,
        "review_only": True,
    }
    write_json(out / MANIFEST_NAME, manifest)

    print("AKERPULS D2C P95 GEOMETRY AUDIT FREEZE")
    print("STATUS=FROZEN_P95_GEOMETRY_AUDIT_V1")
    print(f"PARENT_PROPOSAL_FREEZE_SHA256={EXPECTED_PROPOSAL_FREEZE_SHA256}")
    print(f"SOURCE_LABELS_SHA256={EXPECTED_LABELS_SHA256}")
    print(f"BLIND_KEY_SHA256={EXPECTED_BLIND_KEY_SHA256}")
    print("SPLIT_COUNTS=TYDLIG:64 MOJLIG:16 TVEKSAM:12 FALSK:8 EJ_BEDOMBAR:0")
    print("LINE_COUNTS=RATT:76 NARA:5 FEL:2 EJ_BEDOMBAR:0 EJ_TILLAMPLIG:17")
    print(f"PRE_REVEAL_SPLIT_POSITIVE={int(split_pos.sum())}/100 JOINT_STRICT={strict_joint}/100 JOINT_BROAD={broad_joint}/100")
    print(f"GEOMETRY_AUDIT_FREEZE_SHA256={freeze_sha}")
    print("BLIND_KEY_OPENED=FALSE REVEAL_EXECUTED=FALSE")
    print("MODEL_EXECUTED=FALSE THRESHOLDS_TUNED=FALSE FUSION_REFIT=FALSE OFFICIAL_2025_GEOMETRY_REPLACED=FALSE REVIEW_ONLY=TRUE")
    print("NEXT=REVEAL_AND_ANALYZE_P95_GEOMETRY_AUDIT")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
