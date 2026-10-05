#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Formal pre-label freeze for targeted low-Hprior C validation viewer.

Pins:
- exact 29 unseen C + 29 matched controls sample
- deterministic matching identity
- blind-key bytes (hash only, never parsed)
- all 58 rendered images
- predeclared paired analysis
- no operational mutation

The blind key and matching diagnostic are NOT parsed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EXPECTED_BRANCH="feature/akerpuls-prelim-fields-2026-v0a"
EXPECTED_SOURCE_GIT_HEAD="35b2bafdd10a93ba129a44b7676cb93adc6d230e"

SRC=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_c_low_hprior_independent_validation_viewer_v1")
DEFAULT_OUT=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_c_low_hprior_independent_validation_viewer_freeze_v1")
STATUS="FROZEN_AKERPULS_MERGE_C_LOW_HPRIOR_INDEPENDENT_VALIDATION_VIEWER_V1"

EXPECTED_AB_VALIDATION_FREEZE_SHA="333e3c9738cf56f9a3fadf37c46a7883c508ec70bd25975eb214132fb65ffc8d"
EXPECTED_RANKING_FREEZE_SHA="2f98d504c61ba71da396e4d459ffd6b3e5d2feaacbe5a8faaab9635d2882ef26"
EXPECTED_EXCLUSION_SET_SHA="d9bea361f3f84b3aeb439f96d1f45d8e23e8fb0f19824edf4ab04725b092c457"
EXPECTED_SAMPLE_POPULATION_SHA="c0af9da308d6e250eaca7fa149b64f993bfa91d2af6e3eb533cb3a97023fcd45"
EXPECTED_MATCHING_SHA="e19ced20288d334c6e9943df91242f5d1f780ed6b51a26e78c1e205c6c455aec"
EXPECTED_BLIND_KEY_SHA="81c0ea5e69c8cbcc6032cc860d3581447ab514b83bf890be6f0c6938f453d53d"

EXPECTED_C=29
EXPECTED_CONTROL=29
EXPECTED_ROWS=58
EXPECTED_PRIOR_EXCLUDED=200
EXPECTED_REMAINING_CONTROLS=2057


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


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--source-dir",default=str(SRC))
    ap.add_argument("--output-dir",default=str(DEFAULT_OUT))
    args=ap.parse_args()

    head=git_guard()
    src=Path(args.source_dir); out=Path(args.output_dir)
    if out.exists(): raise RuntimeError(f"Freeze output already exists: {out}")

    manifest_path=src/"C_LOW_HPRIOR_VALIDATION_VIEWER_MANIFEST_V1.json"
    html_path=src/"index.html"
    validity_path=src/"validation_pair_validity.json"
    key_path=src/"C_LOW_HPRIOR_VALIDATION_BLIND_KEY_DO_NOT_OPEN.csv"
    matching_path=src/"MATCHING_DIAGNOSTIC_DO_NOT_OPEN_BEFORE_REVIEW.csv"
    imgdir=src/"images"

    for p in (manifest_path,html_path,validity_path,key_path,matching_path):
        if not p.is_file(): raise FileNotFoundError(p)
    if not imgdir.is_dir(): raise FileNotFoundError(imgdir)

    m=json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if m.get("status")!="PASS_TO_C_LOW_HPRIOR_INDEPENDENT_BLIND_VALIDATION":
        raise RuntimeError("Unexpected source status")
    if m.get("git_head")!=EXPECTED_SOURCE_GIT_HEAD:
        raise RuntimeError("Unexpected source git head")

    parents=m.get("parents",{})
    if parents.get("sh_gated_ranking_freeze_sha256")!=EXPECTED_RANKING_FREEZE_SHA:
        raise RuntimeError("Ranking-freeze lineage changed")
    if parents.get("ab_independent_validation_freeze_sha256")!=EXPECTED_AB_VALIDATION_FREEZE_SHA:
        raise RuntimeError("A/B-validation freeze lineage changed")

    s=m.get("sampling",{})
    checks=[
        (s.get("all_remaining_C_used") is True,"all_remaining_C_used"),
        (int(s.get("C_total_frozen",-1))==54,"C_total_frozen"),
        (int(s.get("prior_audit_pairs_excluded",-1))==EXPECTED_PRIOR_EXCLUDED,"prior exclusions"),
        (int(s.get("remaining_C",-1))==EXPECTED_C,"remaining C"),
        (int(s.get("remaining_controls_A_plus_B",-1))==EXPECTED_REMAINING_CONTROLS,"remaining controls"),
        (int(s.get("matched_controls",-1))==EXPECTED_CONTROL,"matched controls"),
        (int(s.get("rows",-1))==EXPECTED_ROWS,"rows"),
        (s.get("exclusion_set_sha256")==EXPECTED_EXCLUSION_SET_SHA,"exclusion set sha"),
        (s.get("sample_population_sha256")==EXPECTED_SAMPLE_POPULATION_SHA,"sample sha"),
        (s.get("matching_sha256")==EXPECTED_MATCHING_SHA,"matching sha"),
        (s.get("human_labels_used_for_sampling") is False,"human labels not used"),
    ]
    for ok,name in checks:
        if not ok: raise RuntimeError(f"Sampling contract changed: {name}")

    # Aggregate matching quality is safe to inspect pre-label.
    p50=float(s.get("match_delta_p50"))
    p90=float(s.get("match_delta_p90"))
    mx=float(s.get("match_delta_max"))
    if not (0<=p50<=p90<=mx):
        raise RuntimeError("Invalid matching-delta ordering")
    if mx>0.05:
        raise RuntimeError(f"Matching unexpectedly loose: max delta {mx}")

    if m.get("blind_key_sha256")!=EXPECTED_BLIND_KEY_SHA:
        raise RuntimeError("Manifest blind-key SHA changed")
    if sha(key_path)!=EXPECTED_BLIND_KEY_SHA:
        raise RuntimeError("Blind-key bytes changed")

    b=m.get("blindness",{})
    for k in ("arm_visible","tier_visible","scores_visible","pair_id_visible","field_ids_visible","match_id_visible"):
        if b.get(k) is not False: raise RuntimeError(f"Blindness contract changed: {k}")
    if b.get("blind_key_must_remain_closed_until_labels_exported_and_frozen") is not True:
        raise RuntimeError("Blind-key closure contract changed")

    p=m.get("predeclared_analysis",{})
    if p.get("primary_endpoint")!="broad_positive = TYDLIG_MERGE + MÖJLIG_MERGE":
        raise RuntimeError("Primary endpoint changed")
    if p.get("primary_contrast")!="CONTROL_NONLOW_HPRIOR vs C_LOW_HPRIOR within S2026>P90":
        raise RuntimeError("Primary contrast changed")
    if p.get("primary_test")!="exact two-sided McNemar on matched broad-positive labels":
        raise RuntimeError("Primary paired test changed")
    if p.get("paired_exclusion")!="exclude matched pair if either member is EJ_BEDÖMBAR":
        raise RuntimeError("Paired exclusion changed")

    pol=m.get("policy",{})
    if pol.get("block_boundary_hard_wall") is not True: raise RuntimeError("Block hard wall changed")
    if pol.get("cross_block_merge_allowed") is not False: raise RuntimeError("Cross-block policy changed")
    if pol.get("automatic_merge") is not False or pol.get("geometry_mutated") is not False:
        raise RuntimeError("Operational policy changed")
    g=m.get("guards",{})
    for k in ("fusion_executed","thresholds_tuned","automatic_merge","geometry_mutated"):
        if g.get(k) is not False: raise RuntimeError(f"Guard changed: {k}")

    if sha(html_path)!=m.get("html_sha256"): raise RuntimeError("HTML changed")
    if sha(validity_path)!=m.get("validity_sha256"): raise RuntimeError("Validity JSON changed")

    image_hashes=m.get("image_hashes",{})
    if len(image_hashes)!=EXPECTED_ROWS: raise RuntimeError("Expected 58 image hashes")
    actual=sorted(p.name for p in imgdir.glob("*.jpg"))
    if len(actual)!=EXPECTED_ROWS or set(actual)!=set(image_hashes):
        raise RuntimeError("Rendered image census/name set changed")
    for name,expected in image_hashes.items():
        if sha(imgdir/name)!=expected: raise RuntimeError(f"Rendered image changed: {name}")

    source_manifest_sha=sha(manifest_path)
    freeze={
      "schema_version":"akerpuls-merge-c-low-hprior-independent-validation-viewer-freeze-v1",
      "status":STATUS,
      "source_git_head":EXPECTED_SOURCE_GIT_HEAD,
      "freeze_git_head":head,
      "parents":{
        "sh_gated_ranking_freeze_sha256":EXPECTED_RANKING_FREEZE_SHA,
        "ab_independent_validation_freeze_sha256":EXPECTED_AB_VALIDATION_FREEZE_SHA,
      },
      "sample":{
        "C_low_hprior":EXPECTED_C,
        "matched_control":EXPECTED_CONTROL,
        "rows":EXPECTED_ROWS,
        "prior_audit_pairs_excluded":EXPECTED_PRIOR_EXCLUDED,
        "exclusion_set_sha256":EXPECTED_EXCLUSION_SET_SHA,
        "sample_population_sha256":EXPECTED_SAMPLE_POPULATION_SHA,
        "matching_sha256":EXPECTED_MATCHING_SHA,
        "matching_delta_p50":p50,
        "matching_delta_p90":p90,
        "matching_delta_max":mx,
      },
      "source_hashes":{
        "source_manifest_sha256":source_manifest_sha,
        "index_html_sha256":sha(html_path),
        "validity_sha256":sha(validity_path),
        "blind_key_sha256":EXPECTED_BLIND_KEY_SHA,
        "matching_diagnostic_sha256":sha(matching_path),
        "rendered_images_verified":EXPECTED_ROWS,
      },
      "predeclared_analysis":p,
      "contract":{
        "viewer_sample_and_matching_frozen_before_human_labels":True,
        "blind_key_contents_revealed":False,
        "matching_diagnostic_contents_revealed":False,
        "human_labels_created":False,
        "arm_visible":False,
        "tier_visible":False,
        "scores_visible":False,
        "ids_visible":False,
        "block_boundary_hard_wall":True,
        "cross_block_merge_allowed":False,
        "fusion_executed":False,
        "thresholds_tuned":False,
        "automatic_merge":False,
        "geometry_mutated":False,
      },
      "next":"COMPLETE_58_BLIND_LABELS_THEN_FREEZE_LABELS_BEFORE_REVEAL",
    }

    out.mkdir(parents=True,exist_ok=False)
    fp=out/"AKERPULS_MERGE_C_LOW_HPRIOR_INDEPENDENT_VALIDATION_VIEWER_FREEZE_V1.json"
    fp.write_text(json.dumps(freeze,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    fsha=sha(fp)
    (out/"AKERPULS_MERGE_C_LOW_HPRIOR_INDEPENDENT_VALIDATION_VIEWER_FREEZE_V1.sha256").write_text(
        fsha+"  AKERPULS_MERGE_C_LOW_HPRIOR_INDEPENDENT_VALIDATION_VIEWER_FREEZE_V1.json\n",
        encoding="utf-8")
    shutil.copyfile(manifest_path,out/"SOURCE_C_LOW_HPRIOR_VALIDATION_VIEWER_MANIFEST_V1.json")

    print("AKERPULS MERGE LOW-HPRIOR C VALIDATION VIEWER FORMAL FREEZE")
    print(f"STATUS={STATUS}")
    print(f"SOURCE_GIT_HEAD={EXPECTED_SOURCE_GIT_HEAD}")
    print(f"FREEZE_GIT_HEAD={head}")
    print(f"C_VALIDATION_VIEWER_FREEZE_SHA256={fsha}")
    print(f"SOURCE_MANIFEST_SHA256={source_manifest_sha}")
    print(f"SAMPLE_POPULATION_SHA256={EXPECTED_SAMPLE_POPULATION_SHA}")
    print(f"MATCHING_SHA256={EXPECTED_MATCHING_SHA}")
    print(f"BLIND_KEY_SHA256={EXPECTED_BLIND_KEY_SHA}")
    print(f"MATCH_S2026_ABS_DELTA=P50:{p50:.8f} | P90:{p90:.8f} | MAX:{mx:.8f}")
    print("SAMPLE=C_LOW_HPRIOR:29 | MATCHED_CONTROL:29 | TOTAL:58")
    print("RENDERED_IMAGES_VERIFIED=58")
    print("BLIND_KEY_CONTENTS_REVEALED=FALSE MATCHING_DIAGNOSTIC_CONTENTS_REVEALED=FALSE")
    print("HUMAN_LABELS_CREATED=FALSE")
    print("BLOCK_BOUNDARY_HARD_WALL=TRUE CROSS_BLOCK_MERGE_ALLOWED=FALSE")
    print("FUSION_EXECUTED=FALSE THRESHOLDS_TUNED=FALSE AUTOMATIC_MERGE=FALSE GEOMETRY_MUTATED=FALSE")
    print("NEXT=COMPLETE_58_BLIND_LABELS_THEN_FREEZE_LABELS_BEFORE_REVEAL")
    print(f"OUTPUT={out}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
