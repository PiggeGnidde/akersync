#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freeze completed blind merge-audit labels before any blind-key reveal.

This script validates only the exported human-label CSV and the already-frozen
viewer contract. It MUST NOT read BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv.

No reveal, no stratum join, no score analysis, no fusion, no sign selection,
no threshold tuning, no automatic merge, no geometry mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"

VIEWER_FREEZE = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_blind_disagreement_audit_viewer_freeze_v1\AKERPULS_MERGE_BLIND_DISAGREEMENT_AUDIT_VIEWER_FREEZE_V1.json")
EXPECTED_VIEWER_FREEZE_SHA256 = "482e817753e00cca4f92972147515bd000e4a5800dd2bb1ff74af35a89e64a6a"
EXPECTED_M2_FREEZE_SHA256 = "54a567c2a198e9724761f131d6fb6b438b3df897358f461cc41349cf4175c859"
EXPECTED_BLIND_KEY_SHA256 = "706d800769ac2bd1eb9deb5ff6d035aaef2407b4586501bd2a0cfc5ad87feeee"

DEFAULT_LABELS = Path.home() / "Downloads" / "merge_disagreement_audit_labels.csv"
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_blind_disagreement_audit_labels_freeze_v1")
STATUS = "FROZEN_AKERPULS_MERGE_BLIND_DISAGREEMENT_AUDIT_LABELS_V1"
EXPECTED_ROWS = 100
ALLOWED_LABELS = ["TYDLIG_MERGE", "MÖJLIG_MERGE", "TVEKSAM", "BEHÅLL_GRÄNS", "EJ_BEDÖMBAR"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def verify_viewer_freeze() -> dict:
    if not VIEWER_FREEZE.is_file():
        raise FileNotFoundError(VIEWER_FREEZE)
    if sha256_file(VIEWER_FREEZE) != EXPECTED_VIEWER_FREEZE_SHA256:
        raise RuntimeError("Viewer freeze SHA changed")
    v = load_json(VIEWER_FREEZE)
    if v.get("status") != "FROZEN_AKERPULS_MERGE_BLIND_DISAGREEMENT_AUDIT_VIEWER_V1":
        raise RuntimeError("Unexpected viewer-freeze status")
    if v.get("parent_m2_diagnostic_freeze_sha256") != EXPECTED_M2_FREEZE_SHA256:
        raise RuntimeError("Viewer freeze M2 lineage changed")
    if v.get("source_hashes", {}).get("blind_key_sha256") != EXPECTED_BLIND_KEY_SHA256:
        raise RuntimeError("Viewer freeze blind-key hash changed")
    if int(v.get("sample", {}).get("rows", -1)) != EXPECTED_ROWS:
        raise RuntimeError("Viewer freeze sample size changed")
    return v


def validate_labels(path: Path) -> tuple[pd.DataFrame, dict]:
    if not path.is_file():
        raise FileNotFoundError(path)

    # The exported CSV is the only human-audit input read here.
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    expected_cols = [
        "m2_diagnostic_freeze_sha256",
        "blind_key_sha256",
        "blind_index",
        "merge_label",
        "note",
    ]
    if list(df.columns) != expected_cols:
        raise RuntimeError(f"Unexpected label CSV schema: {list(df.columns)}")
    if len(df) != EXPECTED_ROWS:
        raise RuntimeError(f"Expected {EXPECTED_ROWS} labels, got {len(df)}")

    try:
        idx = pd.to_numeric(df["blind_index"], errors="raise").astype(int)
    except Exception as exc:
        raise RuntimeError("blind_index is not integer-valued") from exc
    if sorted(idx.tolist()) != list(range(1, EXPECTED_ROWS + 1)):
        raise RuntimeError("blind_index must be exactly 1..100, once each")
    if idx.duplicated().any():
        raise RuntimeError("Duplicate blind_index in labels")

    if not (df["m2_diagnostic_freeze_sha256"] == EXPECTED_M2_FREEZE_SHA256).all():
        raise RuntimeError("Exported labels do not pin expected M2 freeze")
    if not (df["blind_key_sha256"] == EXPECTED_BLIND_KEY_SHA256).all():
        raise RuntimeError("Exported labels do not pin expected blind-key SHA")

    invalid = sorted(set(df["merge_label"]) - set(ALLOWED_LABELS))
    if invalid:
        raise RuntimeError(f"Invalid merge labels: {invalid}")
    if (df["merge_label"] == "").any():
        raise RuntimeError("All 100 pairs must be labelled before freeze")

    counts = {lab: int((df["merge_label"] == lab).sum()) for lab in ALLOWED_LABELS}
    if sum(counts.values()) != EXPECTED_ROWS:
        raise RuntimeError("Label census does not sum to 100")

    return df, {
        "label_counts_blind_only": counts,
        "notes_nonempty": int((df["note"].astype(str).str.len() > 0).sum()),
        "labels_sha256": sha256_file(path),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default=str(DEFAULT_LABELS))
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    head = git_guard()
    labels_path = Path(args.labels)
    out = Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Label-freeze output already exists: {out}")

    verify_viewer_freeze()
    _df, diag = validate_labels(labels_path)

    out.mkdir(parents=True, exist_ok=False)
    frozen_labels = out / "merge_disagreement_audit_labels_frozen.csv"
    shutil.copyfile(labels_path, frozen_labels)
    if sha256_file(frozen_labels) != diag["labels_sha256"]:
        raise RuntimeError("Copied frozen label CSV hash mismatch")

    freeze = {
        "schema_version": "akerpuls-merge-blind-disagreement-audit-labels-freeze-v1",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "freeze_git_head": head,
        "viewer_freeze_sha256": EXPECTED_VIEWER_FREEZE_SHA256,
        "m2_diagnostic_freeze_sha256": EXPECTED_M2_FREEZE_SHA256,
        "blind_key_sha256": EXPECTED_BLIND_KEY_SHA256,
        "labels": {
            "rows": EXPECTED_ROWS,
            "sha256": diag["labels_sha256"],
            "label_counts_blind_only": diag["label_counts_blind_only"],
            "notes_nonempty": diag["notes_nonempty"],
            "frozen_relative_path": frozen_labels.name,
        },
        "contract": {
            "blind_key_contents_revealed": False,
            "strata_joined": False,
            "scores_joined": False,
            "sign_selected": False,
            "fusion_executed": False,
            "fusion_score_created": False,
            "thresholds_tuned": False,
            "automatic_merge": False,
            "geometry_mutated": False,
        },
        "next": "REVEAL_FROZEN_BLIND_KEY_AND_ANALYZE_PREDECLARED_STRATUM_CONTRASTS",
    }

    freeze_path = out / "AKERPULS_MERGE_BLIND_DISAGREEMENT_AUDIT_LABELS_FREEZE_V1.json"
    freeze_path.write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    freeze_sha = sha256_file(freeze_path)
    (out / "AKERPULS_MERGE_BLIND_DISAGREEMENT_AUDIT_LABELS_FREEZE_V1.sha256").write_text(
        freeze_sha + "  AKERPULS_MERGE_BLIND_DISAGREEMENT_AUDIT_LABELS_FREEZE_V1.json\n",
        encoding="utf-8",
    )

    print("AKERPULS MERGE BLIND DISAGREEMENT AUDIT LABEL FREEZE")
    print(f"STATUS={STATUS}")
    print(f"FREEZE_GIT_HEAD={head}")
    print(f"VIEWER_FREEZE_SHA256={EXPECTED_VIEWER_FREEZE_SHA256}")
    print(f"M2_DIAGNOSTIC_FREEZE_SHA256={EXPECTED_M2_FREEZE_SHA256}")
    print(f"BLIND_KEY_SHA256={EXPECTED_BLIND_KEY_SHA256}")
    print(f"LABELS_SHA256={diag['labels_sha256']}")
    print(f"LABELS_FREEZE_SHA256={freeze_sha}")
    print(f"ROWS={EXPECTED_ROWS}")
    print("LABEL_COUNTS_BLIND_ONLY=" + " | ".join(
        f"{lab}:{diag['label_counts_blind_only'][lab]}" for lab in ALLOWED_LABELS
    ))
    print(f"NOTES_NONEMPTY={diag['notes_nonempty']}")
    print("BLIND_KEY_CONTENTS_REVEALED=FALSE STRATA_JOINED=FALSE SCORES_JOINED=FALSE")
    print("SIGN_SELECTED=FALSE FUSION_EXECUTED=FALSE THRESHOLDS_TUNED=FALSE")
    print("AUTOMATIC_MERGE=FALSE GEOMETRY_MUTATED=FALSE")
    print("NEXT=REVEAL_FROZEN_BLIND_KEY_AND_ANALYZE_PREDECLARED_STRATUM_CONTRASTS")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
