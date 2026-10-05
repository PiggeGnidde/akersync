#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freeze final merge-v1 auto-merge gate decision from already-frozen blind labels.

No blind-key reveal is needed: all 80 rows belong to the same prospectively
frozen candidate rule S2026>P95 AND Hprior>P25.

Predeclared acceptance requires ALL:
  broad >= 0.90
  one-sided Wilson 95% lower bound for broad >= 0.85
  BEHALL_GRANS rate <= 0.05 among assessable
  EJ_BEDOMBAR <= 8/80

If any fails: proposal-only, no automatic boundary removal.
"""
from __future__ import annotations
import hashlib, json, math, subprocess
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
EXPECTED_BRANCH="feature/akerpuls-prelim-fields-2026-v0a"
LABEL_FREEZE=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_final_automerge_gate_labels_freeze_v1\AKERPULS_MERGE_FINAL_AUTOMERGE_GATE_LABELS_FREEZE_V1.json")
LABELS=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_final_automerge_gate_labels_freeze_v1\merge_final_automerge_gate_labels_frozen.csv")
EXPECTED_LABEL_FREEZE_SHA="b45074558cdc63188b5ff0bd28aff437787d1970c7081c9774900dd44488a685"
EXPECTED_LABELS_SHA="ece6775bf4651ce48e00f5c78aa65edb896a5fd4261bc042b626f96c8c1c2b02"
EXPECTED_VIEWER_FREEZE_SHA="5d2c7be7be353fdcba39ff10f289a4cb0484793c768622e7df6f0bcae951d43e"
OUT=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_final_automerge_gate_decision_freeze_v1")
STATUS="FROZEN_AKERPULS_MERGE_FINAL_AUTOMERGE_GATE_DECISION_V1"

def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def guard():
    b=subprocess.check_output(["git","branch","--show-current"],cwd=ROOT,text=True).strip()
    if b!=EXPECTED_BRANCH: raise RuntimeError(f"Expected {EXPECTED_BRANCH}, got {b}")
    if subprocess.check_output(["git","status","--short"],cwd=ROOT,text=True).strip():
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()

def wilson_lower_one_sided(k,n,z=1.6448536269514722):
    p=k/n
    den=1+z*z/n
    center=(p+z*z/(2*n))/den
    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return max(0.0,center-half)

def main():
    head=guard()
    if OUT.exists(): raise RuntimeError(f"Output already exists: {OUT}")
    if not LABEL_FREEZE.is_file() or sha(LABEL_FREEZE)!=EXPECTED_LABEL_FREEZE_SHA:
        raise RuntimeError("Label freeze missing or changed")
    if not LABELS.is_file() or sha(LABELS)!=EXPECTED_LABELS_SHA:
        raise RuntimeError("Frozen labels missing or changed")

    lf=json.loads(LABEL_FREEZE.read_text(encoding="utf-8-sig"))
    if lf.get("viewer_freeze_sha256")!=EXPECTED_VIEWER_FREEZE_SHA:
        raise RuntimeError("Viewer-freeze lineage changed")
    gate=lf["frozen_final_gate"]
    if gate["candidate_rule"]!="S2026>P95 AND Hprior>P25":
        raise RuntimeError("Candidate rule changed")
    if gate["no_posthoc_threshold_chase"] is not True:
        raise RuntimeError("Final-test contract changed")

    d=pd.read_csv(LABELS,encoding="utf-8-sig",dtype=str,keep_default_na=False)
    if len(d)!=80: raise RuntimeError("Expected 80 labels")
    counts=d["merge_label"].value_counts().to_dict()
    ej=int(counts.get("EJ_BEDÖMBAR",0))
    assess=d.loc[d["merge_label"]!="EJ_BEDÖMBAR"]
    n=len(assess)
    broad=int(assess["merge_label"].isin(["TYDLIG_MERGE","MÖJLIG_MERGE"]).sum())
    strict=int((assess["merge_label"]=="TYDLIG_MERGE").sum())
    behall=int((assess["merge_label"]=="BEHÅLL_GRÄNS").sum())
    broad_rate=broad/n
    strict_rate=strict/n
    behall_rate=behall/n
    lower=wilson_lower_one_sided(broad,n)

    checks={
      "broad_rate_ge_0_90": broad_rate>=0.90-1e-15,
      "broad_one_sided_wilson95_lower_ge_0_85": lower>=0.85-1e-15,
      "behall_rate_le_0_05": behall_rate<=0.05+1e-15,
      "ej_bedomdbar_le_8": ej<=8,
    }
    passed=all(checks.values())
    decision="ALLOW_HIGH_CONFIDENCE_AUTOMERGE_TIER" if passed else "MERGE_V1_PROPOSAL_ONLY_NO_AUTOMATIC_BOUNDARY_REMOVAL"

    freeze={
      "schema_version":"akerpuls-merge-final-automerge-gate-decision-freeze-v1",
      "status":STATUS,
      "generated_utc":datetime.now(timezone.utc).isoformat(),
      "freeze_git_head":head,
      "parents":{
        "labels_freeze_sha256":EXPECTED_LABEL_FREEZE_SHA,
        "labels_sha256":EXPECTED_LABELS_SHA,
        "viewer_freeze_sha256":EXPECTED_VIEWER_FREEZE_SHA,
      },
      "candidate_rule":"S2026>P95 AND Hprior>P25",
      "result":{
        "n_total":80,"n_assessable":n,
        "TYDLIG_MERGE":int(counts.get("TYDLIG_MERGE",0)),
        "MÖJLIG_MERGE":int(counts.get("MÖJLIG_MERGE",0)),
        "TVEKSAM":int(counts.get("TVEKSAM",0)),
        "BEHÅLL_GRÄNS":behall,"EJ_BEDÖMBAR":ej,
        "broad_n":broad,"broad_rate":broad_rate,
        "strict_n":strict,"strict_rate":strict_rate,
        "behall_rate":behall_rate,
        "broad_one_sided_wilson95_lower":lower,
      },
      "acceptance_checks":checks,
      "overall_pass":passed,
      "decision":decision,
      "interpretation_lock":{
        "final_blind_test_for_current_signal_family_complete":True,
        "no_more_threshold_search_with_same_signals":True,
        "merge_v1_auto_boundary_removal_allowed":passed,
        "merge_v1_proposal_only":not passed,
      },
      "contract":{
        "blind_key_contents_revealed":False,
        "thresholds_changed":False,
        "automatic_merge_executed":False,
        "geometry_mutated":False,
        "cross_block_merge_allowed":False,
      },
      "next":"FREEZE_MERGE_V1_POLICY_AND_BUILD_PROPOSAL_ONLY_2026_GEOMETRY",
    }
    OUT.mkdir(parents=True,exist_ok=False)
    fp=OUT/"AKERPULS_MERGE_FINAL_AUTOMERGE_GATE_DECISION_FREEZE_V1.json"
    fp.write_text(json.dumps(freeze,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    fsha=sha(fp)
    (OUT/"AKERPULS_MERGE_FINAL_AUTOMERGE_GATE_DECISION_FREEZE_V1.sha256").write_text(
        fsha+"  AKERPULS_MERGE_FINAL_AUTOMERGE_GATE_DECISION_FREEZE_V1.json\n",encoding="utf-8")

    print("AKERPULS MERGE FINAL AUTOMERGE GATE DECISION")
    print(f"STATUS={STATUS}")
    print(f"FREEZE_GIT_HEAD={head}")
    print(f"LABELS_FREEZE_SHA256={EXPECTED_LABEL_FREEZE_SHA}")
    print("CANDIDATE_RULE=S2026_GT_P95_AND_HPRIOR_GT_P25")
    print(f"N_TOTAL=80 ASSESSABLE={n}")
    print(f"TYDLIG={counts.get('TYDLIG_MERGE',0)} MOJLIG={counts.get('MÖJLIG_MERGE',0)} TVEKSAM={counts.get('TVEKSAM',0)} BEHALL={behall} EJ={ej}")
    print(f"BROAD={broad}/{n}={broad_rate:.6f}")
    print(f"STRICT={strict}/{n}={strict_rate:.6f}")
    print(f"BROAD_ONE_SIDED_WILSON95_LOWER={lower:.6f}")
    for k,v in checks.items(): print(f"CHECK_{k.upper()}={'PASS' if v else 'FAIL'}")
    print(f"OVERALL_FINAL_GATE={'PASS' if passed else 'FAIL'}")
    print(f"DECISION={decision}")
    print("BLIND_KEY_CONTENTS_REVEALED=FALSE")
    print("THRESHOLDS_CHANGED=FALSE AUTOMATIC_MERGE_EXECUTED=FALSE GEOMETRY_MUTATED=FALSE")
    print(f"DECISION_FREEZE_SHA256={fsha}")
    print("NEXT=FREEZE_MERGE_V1_POLICY_AND_BUILD_PROPOSAL_ONLY_2026_GEOMETRY")
    print(f"OUTPUT={OUT}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
