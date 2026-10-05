#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse, hashlib, json, shutil, subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EXPECTED_BRANCH="feature/akerpuls-prelim-fields-2026-v0a"
EXPECTED_SOURCE_GIT_HEAD="aed472d7d16b919ae6d55b8908beb17fd8cb4125"
SRC=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_ab_independent_validation_reveal_v1")
DEFAULT_OUT=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_ab_independent_validation_reveal_freeze_v1")
STATUS="FROZEN_AKERPULS_MERGE_AB_INDEPENDENT_VALIDATION_REVEAL_V1"

EXPECTED_LABEL_FREEZE_SHA="9c9183fe720eea38e59384a1cf63a6cda9c1fc7bebfce09a362b71431e212b1a"
EXPECTED_SUMMARY_SHA="8b0fa1b5e6965a02bb11ed29df8f43c161603f81b5a75ceeef219bf7e22d3295"
EXPECTED_JOIN_SHA="ef17c26b588428895c6e0e158b2d91edbdf4a75e50cc997aa1584fde00ec51b5"

EXPECTED={
 "A_CONFIRMED_HIGH":{"n":50,"assessable":49,"strict":0.30612244897959184,"broad":0.8163265306122449},
 "B_SAT_HIGH_H_MID":{"n":50,"assessable":50,"strict":0.42,"broad":0.82},
}
EXPECTED_BROAD_RD=-0.003673469387755102
EXPECTED_BROAD_P=1.0
EXPECTED_STRICT_RD=-0.11387755102040816
EXPECTED_STRICT_P=0.29756037

def sha(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def guard()->str:
    b=subprocess.check_output(["git","branch","--show-current"],cwd=ROOT,text=True).strip()
    if b!=EXPECTED_BRANCH: raise RuntimeError(f"Expected {EXPECTED_BRANCH}, got {b}")
    if subprocess.check_output(["git","status","--short"],cwd=ROOT,text=True).strip():
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()

def close(a,b,tol=1e-9): return abs(float(a)-float(b))<=tol

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--output-dir",default=str(DEFAULT_OUT))
    args=ap.parse_args()
    head=guard(); out=Path(args.output_dir)
    if out.exists(): raise RuntimeError(f"Freeze output already exists: {out}")
    sp=SRC/"MERGE_AB_INDEPENDENT_VALIDATION_SUMMARY_V1.json"
    jp=SRC/"MERGE_AB_INDEPENDENT_VALIDATION_REVEALED_JOIN.csv"
    cp=SRC/"MERGE_AB_INDEPENDENT_VALIDATION_CONTRASTS.csv"
    bp=SRC/"MERGE_AB_INDEPENDENT_VALIDATION_BY_TIER.csv"
    for p in (sp,jp,cp,bp):
        if not p.is_file(): raise FileNotFoundError(p)
    if sha(sp)!=EXPECTED_SUMMARY_SHA: raise RuntimeError("Summary SHA changed")
    if sha(jp)!=EXPECTED_JOIN_SHA: raise RuntimeError("Join SHA changed")
    s=json.loads(sp.read_text(encoding="utf-8-sig"))
    if s.get("status")!="PASS_TO_AB_INDEPENDENT_VALIDATION_REVIEW":
        raise RuntimeError("Unexpected source status")
    if s.get("git_head")!=EXPECTED_SOURCE_GIT_HEAD:
        raise RuntimeError("Unexpected source git head")
    if s.get("parents",{}).get("labels_freeze_sha256")!=EXPECTED_LABEL_FREEZE_SHA:
        raise RuntimeError("Label-freeze lineage changed")
    by=s.get("by_tier",{})
    for tier,e in EXPECTED.items():
        g=by.get(tier,{})
        if int(g.get("n_total",-1))!=e["n"] or int(g.get("n_assessable",-1))!=e["assessable"]:
            raise RuntimeError(f"Tier census changed: {tier}")
        if not close(g.get("strict_positive_rate"),e["strict"]): raise RuntimeError(f"Strict changed: {tier}")
        if not close(g.get("broad_positive_rate"),e["broad"]): raise RuntimeError(f"Broad changed: {tier}")
    br=s["primary_broad_contrast"]; sr=s["secondary_strict_contrast"]
    if not close(br["risk_difference_A_minus_B"],EXPECTED_BROAD_RD): raise RuntimeError("Broad RD changed")
    if not close(br["fisher_two_sided_p"],EXPECTED_BROAD_P): raise RuntimeError("Broad p changed")
    if not close(sr["risk_difference_A_minus_B"],EXPECTED_STRICT_RD): raise RuntimeError("Strict RD changed")
    if abs(float(sr["fisher_two_sided_p"])-EXPECTED_STRICT_P)>1e-8: raise RuntimeError("Strict p changed")
    for k in ("fusion_executed","fusion_weight_selected","thresholds_tuned","automatic_merge","cross_block_merge_allowed","geometry_mutated"):
        if s.get("guards",{}).get(k) is not False: raise RuntimeError(f"Guard changed: {k}")

    freeze={
      "schema_version":"akerpuls-merge-ab-independent-validation-reveal-freeze-v1",
      "status":STATUS,
      "source_git_head":EXPECTED_SOURCE_GIT_HEAD,
      "freeze_git_head":head,
      "labels_freeze_sha256":EXPECTED_LABEL_FREEZE_SHA,
      "source_hashes":{
        "summary_sha256":EXPECTED_SUMMARY_SHA,
        "join_sha256":EXPECTED_JOIN_SHA,
        "contrasts_sha256":sha(cp),
        "by_tier_sha256":sha(bp),
      },
      "result":{
        "A_broad":EXPECTED["A_CONFIRMED_HIGH"]["broad"],
        "B_broad":EXPECTED["B_SAT_HIGH_H_MID"]["broad"],
        "broad_A_minus_B":EXPECTED_BROAD_RD,
        "broad_fisher_p":EXPECTED_BROAD_P,
        "A_strict":EXPECTED["A_CONFIRMED_HIGH"]["strict"],
        "B_strict":EXPECTED["B_SAT_HIGH_H_MID"]["strict"],
        "strict_A_minus_B":EXPECTED_STRICT_RD,
        "strict_fisher_p":EXPECTED_STRICT_P,
      },
      "interpretation_lock":{
        "Hprior_high_outperforms_mid_within_S2026_high":False,
        "independent_validation_supports_P75_confirmation_bonus":False,
        "low_Hprior_veto_not_yet_independently_validated":True,
      },
      "contract":{
        "policy_selected":False,
        "fusion_executed":False,
        "thresholds_tuned":False,
        "automatic_merge":False,
        "cross_block_merge_allowed":False,
        "geometry_mutated":False,
      },
      "next":"TARGETED_INDEPENDENT_VALIDATION_OF_LOW_HPRIOR_C_TIER_BEFORE_OPERATIONAL_POLICY",
    }
    out.mkdir(parents=True,exist_ok=False)
    fp=out/"AKERPULS_MERGE_AB_INDEPENDENT_VALIDATION_REVEAL_FREEZE_V1.json"
    fp.write_text(json.dumps(freeze,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    fsha=sha(fp)
    (out/"AKERPULS_MERGE_AB_INDEPENDENT_VALIDATION_REVEAL_FREEZE_V1.sha256").write_text(
      fsha+"  AKERPULS_MERGE_AB_INDEPENDENT_VALIDATION_REVEAL_FREEZE_V1.json\n",encoding="utf-8")
    shutil.copyfile(sp,out/"SOURCE_AB_INDEPENDENT_VALIDATION_SUMMARY_V1.json")

    print("AKERPULS MERGE A/B INDEPENDENT VALIDATION FORMAL FREEZE")
    print(f"STATUS={STATUS}")
    print(f"SOURCE_GIT_HEAD={EXPECTED_SOURCE_GIT_HEAD}")
    print(f"FREEZE_GIT_HEAD={head}")
    print(f"AB_VALIDATION_FREEZE_SHA256={fsha}")
    print(f"SUMMARY_SHA256={EXPECTED_SUMMARY_SHA}")
    print(f"JOIN_SHA256={EXPECTED_JOIN_SHA}")
    print("A_BROAD=0.816327 B_BROAD=0.820000 RD=-0.003673 P=1")
    print("A_STRICT=0.306122 B_STRICT=0.420000 RD=-0.113878 P=0.29756037")
    print("HPRIOR_P75_CONFIRMATION_BONUS_SUPPORTED=FALSE")
    print("LOW_HPRIOR_VETO_INDEPENDENTLY_VALIDATED=FALSE")
    print("POLICY_SELECTED=FALSE AUTOMATIC_MERGE=FALSE GEOMETRY_MUTATED=FALSE")
    print("NEXT=TARGETED_INDEPENDENT_VALIDATION_OF_LOW_HPRIOR_C_TIER_BEFORE_OPERATIONAL_POLICY")
    print(f"OUTPUT={out}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
