#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freeze completed low-Hprior C validation labels before reveal.

Reads only the exported blind-label CSV plus the already-frozen viewer metadata.
It does NOT parse the blind key or matching diagnostic.

No arm reveal, no score join, no fusion, no threshold tuning, no automatic merge,
no cross-block merge, no geometry mutation.
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

ROOT=Path(__file__).resolve().parents[1]
EXPECTED_BRANCH="feature/akerpuls-prelim-fields-2026-v0a"

VIEWER_FREEZE=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_c_low_hprior_independent_validation_viewer_freeze_v1\AKERPULS_MERGE_C_LOW_HPRIOR_INDEPENDENT_VALIDATION_VIEWER_FREEZE_V1.json")
EXPECTED_VIEWER_FREEZE_SHA="b5c621cb6e3cd80a3906ad489a8ab05d8abd37cfeca090f6f7a777fa89f899ed"
EXPECTED_RANKING_FREEZE_SHA="2f98d504c61ba71da396e4d459ffd6b3e5d2feaacbe5a8faaab9635d2882ef26"
EXPECTED_SAMPLE_POPULATION_SHA="c0af9da308d6e250eaca7fa149b64f993bfa91d2af6e3eb533cb3a97023fcd45"
EXPECTED_MATCHING_SHA="e19ced20288d334c6e9943df91242f5d1f780ed6b51a26e78c1e205c6c455aec"
EXPECTED_BLIND_KEY_SHA="81c0ea5e69c8cbcc6032cc860d3581447ab514b83bf890be6f0c6938f453d53d"
EXPECTED_LABELS_SHA="8d769eb915a32f0b2f73be3c58ee28e2921d1357261f46c4fd09c118e90c3dd6"

DEFAULT_LABELS=Path.home()/"Downloads"/"merge_c_low_hprior_validation_labels.csv"
DEFAULT_OUT=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_c_low_hprior_independent_validation_labels_freeze_v1")
STATUS="FROZEN_AKERPULS_MERGE_C_LOW_HPRIOR_INDEPENDENT_VALIDATION_LABELS_V1"
EXPECTED_ROWS=58
ALLOWED_LABELS=["TYDLIG_MERGE","MÖJLIG_MERGE","TVEKSAM","BEHÅLL_GRÄNS","EJ_BEDÖMBAR"]


def sha(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()


def git_guard()->str:
    b=subprocess.check_output(["git","branch","--show-current"],cwd=ROOT,text=True).strip()
    if b!=EXPECTED_BRANCH: raise RuntimeError(f"Expected {EXPECTED_BRANCH}, got {b}")
    if subprocess.check_output(["git","status","--short"],cwd=ROOT,text=True).strip():
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()


def verify_viewer_freeze()->dict:
    if not VIEWER_FREEZE.is_file(): raise FileNotFoundError(VIEWER_FREEZE)
    if sha(VIEWER_FREEZE)!=EXPECTED_VIEWER_FREEZE_SHA:
        raise RuntimeError("Viewer freeze SHA changed")
    v=json.loads(VIEWER_FREEZE.read_text(encoding="utf-8-sig"))
    if v.get("status")!="FROZEN_AKERPULS_MERGE_C_LOW_HPRIOR_INDEPENDENT_VALIDATION_VIEWER_V1":
        raise RuntimeError("Unexpected viewer freeze status")
    if v.get("parents",{}).get("sh_gated_ranking_freeze_sha256")!=EXPECTED_RANKING_FREEZE_SHA:
        raise RuntimeError("Ranking-freeze lineage changed")
    s=v.get("sample",{})
    if s.get("sample_population_sha256")!=EXPECTED_SAMPLE_POPULATION_SHA:
        raise RuntimeError("Sample population changed")
    if s.get("matching_sha256")!=EXPECTED_MATCHING_SHA:
        raise RuntimeError("Matching identity changed")
    if v.get("source_hashes",{}).get("blind_key_sha256")!=EXPECTED_BLIND_KEY_SHA:
        raise RuntimeError("Blind-key identity changed")
    if int(s.get("rows",-1))!=EXPECTED_ROWS:
        raise RuntimeError("Frozen sample size changed")
    c=v.get("contract",{})
    if c.get("blind_key_contents_revealed") is not False:
        raise RuntimeError("Viewer freeze says blind key was revealed")
    if c.get("matching_diagnostic_contents_revealed") is not False:
        raise RuntimeError("Viewer freeze says matching diagnostic was revealed")
    return v


def validate_labels(path:Path)->dict:
    if not path.is_file(): raise FileNotFoundError(path)
    if sha(path)!=EXPECTED_LABELS_SHA:
        raise RuntimeError("Exported labels SHA does not match the reviewed 58-row export")
    d=pd.read_csv(path,encoding="utf-8-sig",dtype=str,keep_default_na=False)
    expected_cols=[
        "sh_gated_ranking_freeze_sha256","blind_key_sha256",
        "blind_index","merge_label","note",
    ]
    if list(d.columns)!=expected_cols:
        raise RuntimeError(f"Unexpected labels schema: {list(d.columns)}")
    if len(d)!=EXPECTED_ROWS:
        raise RuntimeError(f"Expected {EXPECTED_ROWS} rows, got {len(d)}")
    idx=pd.to_numeric(d["blind_index"],errors="raise").astype(int)
    if idx.duplicated().any() or sorted(idx.tolist())!=list(range(1,EXPECTED_ROWS+1)):
        raise RuntimeError("blind_index must be exactly 1..58, once each")
    if not (d["sh_gated_ranking_freeze_sha256"]==EXPECTED_RANKING_FREEZE_SHA).all():
        raise RuntimeError("Labels do not pin expected ranking freeze")
    if not (d["blind_key_sha256"]==EXPECTED_BLIND_KEY_SHA).all():
        raise RuntimeError("Labels do not pin expected blind-key SHA")
    invalid=sorted(set(d["merge_label"])-set(ALLOWED_LABELS))
    if invalid: raise RuntimeError(f"Invalid labels: {invalid}")
    if (d["merge_label"]=="").any():
        raise RuntimeError("All 58 pairs must be labelled")
    counts={lab:int((d["merge_label"]==lab).sum()) for lab in ALLOWED_LABELS}
    if sum(counts.values())!=EXPECTED_ROWS: raise RuntimeError("Label census does not sum to 58")
    return {
        "counts":counts,
        "notes_nonempty":int((d["note"].astype(str).str.len()>0).sum()),
    }


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--labels",default=str(DEFAULT_LABELS))
    ap.add_argument("--output-dir",default=str(DEFAULT_OUT))
    args=ap.parse_args()

    head=git_guard()
    verify_viewer_freeze()
    labels=Path(args.labels); out=Path(args.output_dir)
    if out.exists(): raise RuntimeError(f"Output already exists: {out}")
    diag=validate_labels(labels)

    out.mkdir(parents=True,exist_ok=False)
    frozen=out/"merge_c_low_hprior_validation_labels_frozen.csv"
    shutil.copyfile(labels,frozen)
    if sha(frozen)!=EXPECTED_LABELS_SHA: raise RuntimeError("Frozen label-copy hash mismatch")

    freeze={
      "schema_version":"akerpuls-merge-c-low-hprior-independent-validation-labels-freeze-v1",
      "status":STATUS,
      "generated_utc":datetime.now(timezone.utc).isoformat(),
      "freeze_git_head":head,
      "viewer_freeze_sha256":EXPECTED_VIEWER_FREEZE_SHA,
      "sh_gated_ranking_freeze_sha256":EXPECTED_RANKING_FREEZE_SHA,
      "sample_population_sha256":EXPECTED_SAMPLE_POPULATION_SHA,
      "matching_sha256":EXPECTED_MATCHING_SHA,
      "blind_key_sha256":EXPECTED_BLIND_KEY_SHA,
      "labels":{
        "rows":EXPECTED_ROWS,
        "sha256":EXPECTED_LABELS_SHA,
        "label_counts_blind_only":diag["counts"],
        "notes_nonempty":diag["notes_nonempty"],
        "frozen_relative_path":frozen.name,
      },
      "contract":{
        "blind_key_contents_revealed":False,
        "matching_diagnostic_contents_revealed":False,
        "arms_joined":False,
        "scores_joined":False,
        "fusion_executed":False,
        "thresholds_tuned":False,
        "automatic_merge":False,
        "cross_block_merge_allowed":False,
        "geometry_mutated":False,
      },
      "next":"REVEAL_C_LOW_HPRIOR_VS_MATCHED_CONTROL_AND_RUN_PREDECLARED_PAIRED_ANALYSIS",
    }
    fp=out/"AKERPULS_MERGE_C_LOW_HPRIOR_INDEPENDENT_VALIDATION_LABELS_FREEZE_V1.json"
    fp.write_text(json.dumps(freeze,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    fsha=sha(fp)
    (out/"AKERPULS_MERGE_C_LOW_HPRIOR_INDEPENDENT_VALIDATION_LABELS_FREEZE_V1.sha256").write_text(
        fsha+"  AKERPULS_MERGE_C_LOW_HPRIOR_INDEPENDENT_VALIDATION_LABELS_FREEZE_V1.json\n",
        encoding="utf-8")

    print("AKERPULS MERGE LOW-HPRIOR C INDEPENDENT VALIDATION LABEL FREEZE")
    print(f"STATUS={STATUS}")
    print(f"FREEZE_GIT_HEAD={head}")
    print(f"VIEWER_FREEZE_SHA256={EXPECTED_VIEWER_FREEZE_SHA}")
    print(f"SAMPLE_POPULATION_SHA256={EXPECTED_SAMPLE_POPULATION_SHA}")
    print(f"MATCHING_SHA256={EXPECTED_MATCHING_SHA}")
    print(f"BLIND_KEY_SHA256={EXPECTED_BLIND_KEY_SHA}")
    print(f"LABELS_SHA256={EXPECTED_LABELS_SHA}")
    print(f"LABELS_FREEZE_SHA256={fsha}")
    print("ROWS=58")
    print("LABEL_COUNTS_BLIND_ONLY="+" | ".join(f"{lab}:{diag['counts'][lab]}" for lab in ALLOWED_LABELS))
    print(f"NOTES_NONEMPTY={diag['notes_nonempty']}")
    print("BLIND_KEY_CONTENTS_REVEALED=FALSE MATCHING_DIAGNOSTIC_CONTENTS_REVEALED=FALSE")
    print("ARMS_JOINED=FALSE SCORES_JOINED=FALSE")
    print("FUSION_EXECUTED=FALSE THRESHOLDS_TUNED=FALSE AUTOMATIC_MERGE=FALSE")
    print("CROSS_BLOCK_MERGE_ALLOWED=FALSE GEOMETRY_MUTATED=FALSE")
    print("NEXT=REVEAL_C_LOW_HPRIOR_VS_MATCHED_CONTROL_AND_RUN_PREDECLARED_PAIRED_ANALYSIS")
    print(f"OUTPUT={out}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
