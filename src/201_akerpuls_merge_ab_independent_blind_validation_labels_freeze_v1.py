#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freeze completed independent blind A/B validation labels before reveal.

Reads ONLY the exported human-label CSV plus the already-frozen viewer metadata.
It never opens/parses the blind key. No A/B reveal, no score join, no fusion,
no threshold tuning, no automatic merge, no cross-block merge, no geometry mutation.
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

VIEWER_FREEZE = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_ab_independent_blind_validation_viewer_freeze_v1\AKERPULS_MERGE_AB_INDEPENDENT_BLIND_VALIDATION_VIEWER_FREEZE_V1.json")
EXPECTED_VIEWER_FREEZE_SHA = "c7b7173314255074e0f34c9efbe35a9a464119fa4621ff924dbbbdd500f96fb1"
EXPECTED_RANKING_FREEZE_SHA = "2f98d504c61ba71da396e4d459ffd6b3e5d2feaacbe5a8faaab9635d2882ef26"
EXPECTED_BLIND_KEY_SHA = "fec621243d0b7cefc33d345be6ee361bd06cdba802a2d72b3925fa3257f7dc5f"
EXPECTED_SAMPLE_POPULATION_SHA = "f5df348a57660df3eadbd8ab7c0bc35b90985b9f22f5540735e2cf56bf0ed677"

DEFAULT_LABELS = Path.home() / "Downloads" / "merge_ab_independent_validation_labels.csv"
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_ab_independent_blind_validation_labels_freeze_v1")
STATUS = "FROZEN_AKERPULS_MERGE_AB_INDEPENDENT_BLIND_VALIDATION_LABELS_V1"
EXPECTED_ROWS = 100
ALLOWED_LABELS = ["TYDLIG_MERGE","MÖJLIG_MERGE","TVEKSAM","BEHÅLL_GRÄNS","EJ_BEDÖMBAR"]


def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()


def git_guard() -> str:
    branch=subprocess.check_output(["git","branch","--show-current"],cwd=ROOT,text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    if subprocess.check_output(["git","status","--short"],cwd=ROOT,text=True).strip():
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()


def verify_viewer_freeze() -> dict:
    if not VIEWER_FREEZE.is_file():
        raise FileNotFoundError(VIEWER_FREEZE)
    if sha256_file(VIEWER_FREEZE) != EXPECTED_VIEWER_FREEZE_SHA:
        raise RuntimeError("Viewer freeze SHA changed")
    v=json.loads(VIEWER_FREEZE.read_text(encoding="utf-8-sig"))
    if v.get("status") != "FROZEN_AKERPULS_MERGE_AB_INDEPENDENT_BLIND_VALIDATION_VIEWER_V1":
        raise RuntimeError("Unexpected viewer freeze status")
    if v.get("parents",{}).get("sh_gated_ranking_freeze_sha256") != EXPECTED_RANKING_FREEZE_SHA:
        raise RuntimeError("Ranking-freeze lineage changed")
    if v.get("sample",{}).get("sample_population_sha256") != EXPECTED_SAMPLE_POPULATION_SHA:
        raise RuntimeError("Frozen sample population changed")
    if v.get("source_hashes",{}).get("blind_key_sha256") != EXPECTED_BLIND_KEY_SHA:
        raise RuntimeError("Frozen blind-key SHA changed")
    if int(v.get("sample",{}).get("rows",-1)) != EXPECTED_ROWS:
        raise RuntimeError("Frozen sample size changed")
    if v.get("contract",{}).get("blind_key_contents_revealed") is not False:
        raise RuntimeError("Viewer freeze says blind key was revealed")
    return v


def validate_labels(path: Path) -> tuple[pd.DataFrame,dict]:
    if not path.is_file():
        raise FileNotFoundError(path)
    df=pd.read_csv(path,encoding="utf-8-sig",dtype=str,keep_default_na=False)
    expected_cols=[
        "sh_gated_ranking_freeze_sha256",
        "blind_key_sha256",
        "blind_index",
        "merge_label",
        "note",
    ]
    if list(df.columns) != expected_cols:
        raise RuntimeError(f"Unexpected label CSV schema: {list(df.columns)}")
    if len(df) != EXPECTED_ROWS:
        raise RuntimeError(f"Expected {EXPECTED_ROWS} labels, got {len(df)}")

    idx=pd.to_numeric(df["blind_index"],errors="raise").astype(int)
    if sorted(idx.tolist()) != list(range(1,EXPECTED_ROWS+1)):
        raise RuntimeError("blind_index must be exactly 1..100, once each")
    if idx.duplicated().any():
        raise RuntimeError("Duplicate blind_index")

    if not (df["sh_gated_ranking_freeze_sha256"] == EXPECTED_RANKING_FREEZE_SHA).all():
        raise RuntimeError("Exported labels do not pin expected ranking freeze")
    if not (df["blind_key_sha256"] == EXPECTED_BLIND_KEY_SHA).all():
        raise RuntimeError("Exported labels do not pin expected blind-key SHA")

    invalid=sorted(set(df["merge_label"]) - set(ALLOWED_LABELS))
    if invalid:
        raise RuntimeError(f"Invalid merge labels: {invalid}")
    if (df["merge_label"] == "").any():
        raise RuntimeError("All 100 validation pairs must be labelled before freeze")

    counts={lab:int((df["merge_label"]==lab).sum()) for lab in ALLOWED_LABELS}
    if sum(counts.values()) != EXPECTED_ROWS:
        raise RuntimeError("Label census does not sum to 100")

    return df,{
        "labels_sha256":sha256_file(path),
        "label_counts_blind_only":counts,
        "notes_nonempty":int((df["note"].astype(str).str.len()>0).sum()),
    }


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--labels",default=str(DEFAULT_LABELS))
    ap.add_argument("--output-dir",default=str(DEFAULT_OUT))
    args=ap.parse_args()

    head=git_guard()
    verify_viewer_freeze()
    labels_path=Path(args.labels)
    out=Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Label-freeze output already exists: {out}")

    _,diag=validate_labels(labels_path)

    out.mkdir(parents=True,exist_ok=False)
    frozen=out/"merge_ab_independent_validation_labels_frozen.csv"
    shutil.copyfile(labels_path,frozen)
    if sha256_file(frozen) != diag["labels_sha256"]:
        raise RuntimeError("Frozen label copy hash mismatch")

    freeze={
        "schema_version":"akerpuls-merge-ab-independent-blind-validation-labels-freeze-v1",
        "status":STATUS,
        "generated_utc":datetime.now(timezone.utc).isoformat(),
        "freeze_git_head":head,
        "viewer_freeze_sha256":EXPECTED_VIEWER_FREEZE_SHA,
        "sh_gated_ranking_freeze_sha256":EXPECTED_RANKING_FREEZE_SHA,
        "sample_population_sha256":EXPECTED_SAMPLE_POPULATION_SHA,
        "blind_key_sha256":EXPECTED_BLIND_KEY_SHA,
        "labels":{
            "rows":EXPECTED_ROWS,
            "sha256":diag["labels_sha256"],
            "label_counts_blind_only":diag["label_counts_blind_only"],
            "notes_nonempty":diag["notes_nonempty"],
            "frozen_relative_path":frozen.name,
        },
        "contract":{
            "blind_key_contents_revealed":False,
            "tiers_joined":False,
            "scores_joined":False,
            "fusion_executed":False,
            "thresholds_tuned":False,
            "automatic_merge":False,
            "cross_block_merge_allowed":False,
            "geometry_mutated":False,
        },
        "next":"REVEAL_A_VS_B_AND_RUN_PREDECLARED_INDEPENDENT_VALIDATION_ANALYSIS",
    }
    fp=out/"AKERPULS_MERGE_AB_INDEPENDENT_BLIND_VALIDATION_LABELS_FREEZE_V1.json"
    fp.write_text(json.dumps(freeze,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    fsha=sha256_file(fp)
    (out/"AKERPULS_MERGE_AB_INDEPENDENT_BLIND_VALIDATION_LABELS_FREEZE_V1.sha256").write_text(
        fsha+"  AKERPULS_MERGE_AB_INDEPENDENT_BLIND_VALIDATION_LABELS_FREEZE_V1.json\n",
        encoding="utf-8",
    )

    print("AKERPULS MERGE A/B INDEPENDENT BLIND VALIDATION LABEL FREEZE")
    print(f"STATUS={STATUS}")
    print(f"FREEZE_GIT_HEAD={head}")
    print(f"VIEWER_FREEZE_SHA256={EXPECTED_VIEWER_FREEZE_SHA}")
    print(f"SH_GATED_RANKING_FREEZE_SHA256={EXPECTED_RANKING_FREEZE_SHA}")
    print(f"SAMPLE_POPULATION_SHA256={EXPECTED_SAMPLE_POPULATION_SHA}")
    print(f"BLIND_KEY_SHA256={EXPECTED_BLIND_KEY_SHA}")
    print(f"LABELS_SHA256={diag['labels_sha256']}")
    print(f"LABELS_FREEZE_SHA256={fsha}")
    print("ROWS=100")
    print("LABEL_COUNTS_BLIND_ONLY="+" | ".join(f"{lab}:{diag['label_counts_blind_only'][lab]}" for lab in ALLOWED_LABELS))
    print(f"NOTES_NONEMPTY={diag['notes_nonempty']}")
    print("BLIND_KEY_CONTENTS_REVEALED=FALSE TIERS_JOINED=FALSE SCORES_JOINED=FALSE")
    print("FUSION_EXECUTED=FALSE THRESHOLDS_TUNED=FALSE AUTOMATIC_MERGE=FALSE")
    print("CROSS_BLOCK_MERGE_ALLOWED=FALSE GEOMETRY_MUTATED=FALSE")
    print("NEXT=REVEAL_A_VS_B_AND_RUN_PREDECLARED_INDEPENDENT_VALIDATION_ANALYSIS")
    print(f"OUTPUT={out}")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
