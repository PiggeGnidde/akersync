#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freeze the final 80 blind auto-merge-gate labels before reveal.

Reads only the exported blind-label CSV plus the already-frozen final-gate
viewer metadata. It never parses the blind key.

No reveal, no threshold change, no automatic merge, no geometry mutation.
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

VIEWER_FREEZE=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_final_automerge_gate_viewer_freeze_v1\AKERPULS_MERGE_FINAL_AUTOMERGE_GATE_VIEWER_FREEZE_V1.json")
EXPECTED_VIEWER_FREEZE_SHA="5d2c7be7be353fdcba39ff10f289a4cb0484793c768622e7df6f0bcae951d43e"
EXPECTED_RANKING_FREEZE_SHA="2f98d504c61ba71da396e4d459ffd6b3e5d2feaacbe5a8faaab9635d2882ef26"
EXPECTED_SAMPLE_POPULATION_SHA="2fae45bc19ace2c4a4aa00477e0fa0072f6c8be86b970649e85a8ef8a9849244"
EXPECTED_BLIND_KEY_SHA="00ec0b06dd5b0d909b535b8694d8c6959fc9d3f7ad0e421dddf1facf24e8dfb3"

DEFAULT_LABELS=Path.home()/"Downloads"/"merge_final_automerge_gate_labels.csv"
DEFAULT_OUT=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_final_automerge_gate_labels_freeze_v1")
STATUS="FROZEN_AKERPULS_MERGE_FINAL_AUTOMERGE_GATE_LABELS_V1"
EXPECTED_ROWS=80
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


def verify_parent()->dict:
    if not VIEWER_FREEZE.is_file(): raise FileNotFoundError(VIEWER_FREEZE)
    if sha(VIEWER_FREEZE)!=EXPECTED_VIEWER_FREEZE_SHA:
        raise RuntimeError("Final-gate viewer freeze changed")
    v=json.loads(VIEWER_FREEZE.read_text(encoding="utf-8-sig"))
    if v.get("status")!="FROZEN_AKERPULS_MERGE_FINAL_AUTOMERGE_GATE_VIEWER_V1":
        raise RuntimeError("Unexpected viewer-freeze status")
    if v.get("sample_population_sha256")!=EXPECTED_SAMPLE_POPULATION_SHA:
        raise RuntimeError("Sample population changed")
    if v.get("blind_key_sha256")!=EXPECTED_BLIND_KEY_SHA:
        raise RuntimeError("Blind-key identity changed")
    rule=v.get("candidate_rule",{})
    if float(rule.get("S2026_percentile_gt",-1))!=0.95:
        raise RuntimeError("S2026 gate changed")
    if float(rule.get("Hprior_percentile_gt",-1))!=0.25:
        raise RuntimeError("Hprior veto changed")
    gate=v.get("predeclared_final_gate",{}).get("acceptance",{})
    expected={
        "broad_rate_min":0.90,
        "broad_one_sided_wilson95_lower_min":0.85,
        "behall_rate_max":0.05,
        "ej_bedomdbar_max_count":8,
    }
    for k,e in expected.items():
        if float(gate.get(k,-999))!=float(e):
            raise RuntimeError(f"Acceptance criterion changed: {k}")
    c=v.get("contract",{})
    if c.get("blind_key_contents_revealed") is not False:
        raise RuntimeError("Viewer freeze says blind key was revealed")
    if c.get("human_labels_created") is not False:
        raise RuntimeError("Viewer freeze says labels already existed")
    return v


def validate_labels(path:Path)->tuple[str,dict]:
    if not path.is_file(): raise FileNotFoundError(path)
    d=pd.read_csv(path,encoding="utf-8-sig",dtype=str,keep_default_na=False)
    expected_cols=[
        "sh_gated_ranking_freeze_sha256",
        "blind_key_sha256",
        "blind_index",
        "merge_label",
        "note",
    ]
    if list(d.columns)!=expected_cols:
        raise RuntimeError(f"Unexpected labels schema: {list(d.columns)}")
    if len(d)!=EXPECTED_ROWS:
        raise RuntimeError(f"Expected {EXPECTED_ROWS} rows, got {len(d)}")
    idx=pd.to_numeric(d["blind_index"],errors="raise").astype(int)
    if idx.duplicated().any() or sorted(idx.tolist())!=list(range(1,EXPECTED_ROWS+1)):
        raise RuntimeError("blind_index must be exactly 1..80, once each")
    if not (d["sh_gated_ranking_freeze_sha256"]==EXPECTED_RANKING_FREEZE_SHA).all():
        raise RuntimeError("Labels do not pin expected ranking freeze")
    if not (d["blind_key_sha256"]==EXPECTED_BLIND_KEY_SHA).all():
        raise RuntimeError("Labels do not pin expected blind-key SHA")
    invalid=sorted(set(d["merge_label"])-set(ALLOWED_LABELS))
    if invalid: raise RuntimeError(f"Invalid labels: {invalid}")
    if (d["merge_label"]=="").any():
        raise RuntimeError("All 80 final-gate pairs must be labelled")
    counts={lab:int((d["merge_label"]==lab).sum()) for lab in ALLOWED_LABELS}
    if sum(counts.values())!=EXPECTED_ROWS:
        raise RuntimeError("Label census does not sum to 80")
    return sha(path),{
        "counts":counts,
        "notes_nonempty":int((d["note"].astype(str).str.len()>0).sum()),
    }


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--labels",default=str(DEFAULT_LABELS))
    ap.add_argument("--output-dir",default=str(DEFAULT_OUT))
    args=ap.parse_args()

    head=git_guard()
    verify_parent()
    labels=Path(args.labels); out=Path(args.output_dir)
    if out.exists(): raise RuntimeError(f"Output already exists: {out}")

    labels_sha,diag=validate_labels(labels)

    out.mkdir(parents=True,exist_ok=False)
    frozen=out/"merge_final_automerge_gate_labels_frozen.csv"
    shutil.copyfile(labels,frozen)
    if sha(frozen)!=labels_sha: raise RuntimeError("Frozen label-copy hash mismatch")

    freeze={
        "schema_version":"akerpuls-merge-final-automerge-gate-labels-freeze-v1",
        "status":STATUS,
        "generated_utc":datetime.now(timezone.utc).isoformat(),
        "freeze_git_head":head,
        "viewer_freeze_sha256":EXPECTED_VIEWER_FREEZE_SHA,
        "sh_gated_ranking_freeze_sha256":EXPECTED_RANKING_FREEZE_SHA,
        "sample_population_sha256":EXPECTED_SAMPLE_POPULATION_SHA,
        "blind_key_sha256":EXPECTED_BLIND_KEY_SHA,
        "labels":{
            "rows":EXPECTED_ROWS,
            "sha256":labels_sha,
            "label_counts_blind_only":diag["counts"],
            "notes_nonempty":diag["notes_nonempty"],
            "frozen_relative_path":frozen.name,
        },
        "frozen_final_gate":{
            "candidate_rule":"S2026>P95 AND Hprior>P25",
            "broad_rate_min":0.90,
            "broad_one_sided_wilson95_lower_min":0.85,
            "behall_rate_max":0.05,
            "ej_bedomdbar_max_count":8,
            "final_blind_test_for_current_signal_family":True,
            "no_posthoc_threshold_chase":True,
        },
        "contract":{
            "blind_key_contents_revealed":False,
            "scores_joined":False,
            "thresholds_changed":False,
            "automatic_merge":False,
            "geometry_mutated":False,
            "cross_block_merge_allowed":False,
        },
        "next":"REVEAL_FINAL_GATE_AND_APPLY_PREDECLARED_PASS_FAIL_RULE",
    }
    fp=out/"AKERPULS_MERGE_FINAL_AUTOMERGE_GATE_LABELS_FREEZE_V1.json"
    fp.write_text(json.dumps(freeze,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    fsha=sha(fp)
    (out/"AKERPULS_MERGE_FINAL_AUTOMERGE_GATE_LABELS_FREEZE_V1.sha256").write_text(
        fsha+"  AKERPULS_MERGE_FINAL_AUTOMERGE_GATE_LABELS_FREEZE_V1.json\n",
        encoding="utf-8")

    print("AKERPULS MERGE FINAL AUTOMERGE GATE LABEL FREEZE")
    print(f"STATUS={STATUS}")
    print(f"FREEZE_GIT_HEAD={head}")
    print(f"VIEWER_FREEZE_SHA256={EXPECTED_VIEWER_FREEZE_SHA}")
    print(f"SAMPLE_POPULATION_SHA256={EXPECTED_SAMPLE_POPULATION_SHA}")
    print(f"BLIND_KEY_SHA256={EXPECTED_BLIND_KEY_SHA}")
    print(f"LABELS_SHA256={labels_sha}")
    print(f"LABELS_FREEZE_SHA256={fsha}")
    print("ROWS=80")
    print("LABEL_COUNTS_BLIND_ONLY="+" | ".join(f"{lab}:{diag['counts'][lab]}" for lab in ALLOWED_LABELS))
    print(f"NOTES_NONEMPTY={diag['notes_nonempty']}")
    print("FINAL_GATE_RULE=S2026_GT_P95_AND_HPRIOR_GT_P25")
    print("ACCEPT_BROAD_RATE_MIN=0.90")
    print("ACCEPT_BROAD_ONE_SIDED_WILSON95_LOWER_MIN=0.85")
    print("ACCEPT_BEHALL_RATE_MAX=0.05")
    print("ACCEPT_EJ_BEDOMBAR_MAX_COUNT=8")
    print("BLIND_KEY_CONTENTS_REVEALED=FALSE SCORES_JOINED=FALSE")
    print("THRESHOLDS_CHANGED=FALSE AUTOMATIC_MERGE=FALSE GEOMETRY_MUTATED=FALSE")
    print("NEXT=REVEAL_FINAL_GATE_AND_APPLY_PREDECLARED_PASS_FAIL_RULE")
    print(f"OUTPUT={out}")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
