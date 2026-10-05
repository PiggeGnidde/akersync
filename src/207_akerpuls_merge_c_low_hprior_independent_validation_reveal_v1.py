#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reveal low-Hprior C vs matched controls after formal label freeze.

Primary predeclared endpoint:
  broad positive = TYDLIG_MERGE + MÖJLIG_MERGE

Primary predeclared test:
  exact two-sided McNemar on the 29 matched C/control pairs,
  excluding a matched pair if either member is EJ_BEDÖMBAR.

Secondary endpoint/test:
  strict positive = TYDLIG_MERGE, same paired McNemar framework.

Also reports descriptive group rates, Wilson 95% CIs, unpaired Fisher exact and
risk differences. No fusion, no threshold tuning, no automatic merge, no
cross-block merge, no geometry mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
EXPECTED_BRANCH="feature/akerpuls-prelim-fields-2026-v0a"

LABEL_FREEZE_DIR=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_c_low_hprior_independent_validation_labels_freeze_v1")
LABEL_FREEZE_JSON=LABEL_FREEZE_DIR/"AKERPULS_MERGE_C_LOW_HPRIOR_INDEPENDENT_VALIDATION_LABELS_FREEZE_V1.json"
LABELS=LABEL_FREEZE_DIR/"merge_c_low_hprior_validation_labels_frozen.csv"

VIEWER_DIR=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_c_low_hprior_independent_validation_viewer_v1")
BLIND_KEY=VIEWER_DIR/"C_LOW_HPRIOR_VALIDATION_BLIND_KEY_DO_NOT_OPEN.csv"
MATCH_DIAG=VIEWER_DIR/"MATCHING_DIAGNOSTIC_DO_NOT_OPEN_BEFORE_REVIEW.csv"

EXPECTED_LABEL_FREEZE_SHA="d8143e47bb1ab9b8056f0b93e32250caeac5397c2b483d60e167a28cef0d3899"
EXPECTED_LABELS_SHA="8d769eb915a32f0b2f73be3c58ee28e2921d1357261f46c4fd09c118e90c3dd6"
EXPECTED_VIEWER_FREEZE_SHA="b5c621cb6e3cd80a3906ad489a8ab05d8abd37cfeca090f6f7a777fa89f899ed"
EXPECTED_SAMPLE_POPULATION_SHA="c0af9da308d6e250eaca7fa149b64f993bfa91d2af6e3eb533cb3a97023fcd45"
EXPECTED_MATCHING_SHA="e19ced20288d334c6e9943df91242f5d1f780ed6b51a26e78c1e205c6c455aec"
EXPECTED_BLIND_KEY_SHA="81c0ea5e69c8cbcc6032cc860d3581447ab514b83bf890be6f0c6938f453d53d"

DEFAULT_OUT=Path(r"C:\AkerSyncRepo\work\akerpuls_merge_c_low_hprior_independent_validation_reveal_v1")
STATUS="PASS_TO_C_LOW_HPRIOR_INDEPENDENT_VALIDATION_REVIEW"

EXPECTED_ROWS=58
EXPECTED_MATCHES=29
EXPECTED_ARMS={"C_LOW_HPRIOR":29,"CONTROL_NONLOW_HPRIOR":29}
LABEL_ORDER=["TYDLIG_MERGE","MÖJLIG_MERGE","TVEKSAM","BEHÅLL_GRÄNS","EJ_BEDÖMBAR"]


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


def wilson(k:int,n:int,z:float=1.959963984540054):
    if n<=0: return (None,None)
    p=k/n
    den=1+z*z/n
    center=(p+z*z/(2*n))/den
    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return max(0.0,center-half),min(1.0,center+half)


def fisher_two_sided(a:int,b:int,c:int,d:int)->float:
    r1,r2=a+b,c+d
    c1=a+c
    n=r1+r2
    lo=max(0,c1-r2)
    hi=min(r1,c1)
    def prob(x:int)->float:
        return (math.comb(c1,x)*math.comb(n-c1,r1-x))/math.comb(n,r1)
    pobs=prob(a)
    return min(1.0,sum(prob(x) for x in range(lo,hi+1) if prob(x)<=pobs+1e-12))


def mcnemar_exact_two_sided(control_pos_cneg:int, control_neg_cpos:int)->float:
    n=control_pos_cneg+control_neg_cpos
    if n==0: return 1.0
    k=min(control_pos_cneg,control_neg_cpos)
    lower=sum(math.comb(n,i) for i in range(0,k+1))/(2**n)
    return min(1.0,2.0*lower)


def arm_metrics(g:pd.DataFrame)->dict:
    counts={lab:int((g["merge_label"]==lab).sum()) for lab in LABEL_ORDER}
    a=g.loc[g["merge_label"]!="EJ_BEDÖMBAR"].copy()
    n=len(a)
    strict=int((a["merge_label"]=="TYDLIG_MERGE").sum())
    broad=int(a["merge_label"].isin(["TYDLIG_MERGE","MÖJLIG_MERGE"]).sum())
    sci=wilson(strict,n); bci=wilson(broad,n)
    return {
        "n_total":int(len(g)),
        "n_assessable":int(n),
        "label_counts":counts,
        "strict_positive_n":strict,
        "strict_positive_rate":strict/n if n else None,
        "strict_wilson95":[sci[0],sci[1]],
        "broad_positive_n":broad,
        "broad_positive_rate":broad/n if n else None,
        "broad_wilson95":[bci[0],bci[1]],
    }


def unpaired_contrast(metrics:dict,endpoint:str)->dict:
    C=metrics["C_LOW_HPRIOR"]
    K=metrics["CONTROL_NONLOW_HPRIOR"]
    key=f"{endpoint}_positive_n"
    cp=int(C[key]); cn=int(C["n_assessable"]-cp)
    kp=int(K[key]); kn=int(K["n_assessable"]-kp)
    cr=cp/C["n_assessable"]; kr=kp/K["n_assessable"]
    return {
        "endpoint":endpoint,
        "C_rate":cr,
        "CONTROL_rate":kr,
        "risk_difference_CONTROL_minus_C":kr-cr,
        "fisher_two_sided_p":fisher_two_sided(kp,kn,cp,cn),
    }


def paired_contrast(j:pd.DataFrame,endpoint:str)->dict:
    if endpoint=="broad":
        pos=lambda s:s.isin(["TYDLIG_MERGE","MÖJLIG_MERGE"])
    elif endpoint=="strict":
        pos=lambda s:s.eq("TYDLIG_MERGE")
    else:
        raise ValueError(endpoint)

    rows=[]
    for mid,g in j.groupby("match_id",sort=True):
        if len(g)!=2 or set(g["arm"])!={"C_LOW_HPRIOR","CONTROL_NONLOW_HPRIOR"}:
            raise RuntimeError(f"Malformed match_id {mid}")
        c=g.loc[g["arm"]=="C_LOW_HPRIOR"].iloc[0]
        k=g.loc[g["arm"]=="CONTROL_NONLOW_HPRIOR"].iloc[0]
        valid=(c["merge_label"]!="EJ_BEDÖMBAR") and (k["merge_label"]!="EJ_BEDÖMBAR")
        rows.append({
            "match_id":int(mid),
            "valid_for_paired":bool(valid),
            "C_positive":bool(pos(pd.Series([c["merge_label"]])).iloc[0]) if valid else None,
            "CONTROL_positive":bool(pos(pd.Series([k["merge_label"]])).iloc[0]) if valid else None,
        })
    p=pd.DataFrame(rows)
    v=p.loc[p["valid_for_paired"]].copy()
    both_pos=int((v["C_positive"] & v["CONTROL_positive"]).sum())
    both_neg=int((~v["C_positive"] & ~v["CONTROL_positive"]).sum())
    control_pos_cneg=int((~v["C_positive"] & v["CONTROL_positive"]).sum())
    control_neg_cpos=int((v["C_positive"] & ~v["CONTROL_positive"]).sum())
    n=len(v)
    c_rate=float(v["C_positive"].mean()) if n else None
    k_rate=float(v["CONTROL_positive"].mean()) if n else None
    return {
        "endpoint":endpoint,
        "matched_pairs_total":EXPECTED_MATCHES,
        "matched_pairs_valid":int(n),
        "matched_pairs_excluded_due_EJ":int(EXPECTED_MATCHES-n),
        "both_positive":both_pos,
        "both_negative":both_neg,
        "discordant_CONTROL_positive_C_negative":control_pos_cneg,
        "discordant_CONTROL_negative_C_positive":control_neg_cpos,
        "paired_C_rate":c_rate,
        "paired_CONTROL_rate":k_rate,
        "paired_risk_difference_CONTROL_minus_C":(k_rate-c_rate) if n else None,
        "mcnemar_exact_two_sided_p":mcnemar_exact_two_sided(control_pos_cneg,control_neg_cpos),
    },p


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--output-dir",default=str(DEFAULT_OUT))
    args=ap.parse_args()
    head=git_guard(); out=Path(args.output_dir)
    if out.exists(): raise RuntimeError(f"Output already exists: {out}")

    if not LABEL_FREEZE_JSON.is_file() or sha(LABEL_FREEZE_JSON)!=EXPECTED_LABEL_FREEZE_SHA:
        raise RuntimeError("Label freeze missing or changed")
    lf=json.loads(LABEL_FREEZE_JSON.read_text(encoding="utf-8-sig"))
    if lf.get("status")!="FROZEN_AKERPULS_MERGE_C_LOW_HPRIOR_INDEPENDENT_VALIDATION_LABELS_V1":
        raise RuntimeError("Unexpected label-freeze status")
    if lf.get("viewer_freeze_sha256")!=EXPECTED_VIEWER_FREEZE_SHA:
        raise RuntimeError("Viewer-freeze lineage changed")
    if lf.get("sample_population_sha256")!=EXPECTED_SAMPLE_POPULATION_SHA:
        raise RuntimeError("Sample population lineage changed")
    if lf.get("matching_sha256")!=EXPECTED_MATCHING_SHA:
        raise RuntimeError("Matching lineage changed")
    if lf.get("blind_key_sha256")!=EXPECTED_BLIND_KEY_SHA:
        raise RuntimeError("Blind-key lineage changed")

    if not LABELS.is_file() or sha(LABELS)!=EXPECTED_LABELS_SHA:
        raise RuntimeError("Frozen labels missing or changed")
    if not BLIND_KEY.is_file() or sha(BLIND_KEY)!=EXPECTED_BLIND_KEY_SHA:
        raise RuntimeError("Blind key missing or changed")
    if not MATCH_DIAG.is_file():
        raise RuntimeError("Matching diagnostic missing")

    print("AKERPULS MERGE LOW-HPRIOR C INDEPENDENT VALIDATION REVEAL V1")
    print(f"GIT_HEAD={head}")
    print(f"LABELS_FREEZE_SHA256={EXPECTED_LABEL_FREEZE_SHA}")
    print(f"BLIND_KEY_SHA256={EXPECTED_BLIND_KEY_SHA}")
    print("BLIND_KEY_REVEAL_AUTHORIZED_BY_FROZEN_LABELS=TRUE")
    print("PROGRESS=LOAD_FROZEN_LABELS_AND_REVEAL_MATCHED_ARMS")

    labels=pd.read_csv(LABELS,encoding="utf-8-sig",dtype=str,keep_default_na=False)
    key=pd.read_csv(BLIND_KEY,encoding="utf-8-sig",keep_default_na=False)
    match=pd.read_csv(MATCH_DIAG,encoding="utf-8-sig",keep_default_na=False)

    if len(labels)!=EXPECTED_ROWS or len(key)!=EXPECTED_ROWS:
        raise RuntimeError("Expected 58 rows in labels and key")
    labels["blind_index"]=pd.to_numeric(labels["blind_index"],errors="raise").astype(int)
    key["blind_index"]=pd.to_numeric(key["blind_index"],errors="raise").astype(int)
    key["match_id"]=pd.to_numeric(key["match_id"],errors="raise").astype(int)
    if labels["blind_index"].nunique()!=EXPECTED_ROWS or key["blind_index"].nunique()!=EXPECTED_ROWS:
        raise RuntimeError("blind_index not unique")

    joined=labels.merge(key,on="blind_index",how="outer",validate="one_to_one",indicator=True)
    if len(joined)!=EXPECTED_ROWS or not (joined["_merge"]=="both").all():
        raise RuntimeError("Labels and blind key did not join 1:1")
    joined=joined.drop(columns=["_merge"])

    got=joined["arm"].value_counts().to_dict()
    if got!=EXPECTED_ARMS:
        raise RuntimeError(f"Arm census changed: {got}")
    if joined["match_id"].nunique()!=EXPECTED_MATCHES:
        raise RuntimeError("Expected 29 match ids")
    if len(match)!=EXPECTED_MATCHES:
        raise RuntimeError("Expected 29 matching-diagnostic rows")

    # Verify matching diagnostic is consistent with revealed key.
    mkey=joined.pivot(index="match_id",columns="arm",values="pair_key")
    for r in match.itertuples(index=False):
        mid=int(r.match_id)
        if str(mkey.loc[mid,"C_LOW_HPRIOR"])!=str(r.c_pair_key):
            raise RuntimeError(f"C pair mismatch in match {mid}")
        if str(mkey.loc[mid,"CONTROL_NONLOW_HPRIOR"])!=str(r.control_pair_key):
            raise RuntimeError(f"Control pair mismatch in match {mid}")

    metrics={arm:arm_metrics(joined.loc[joined["arm"]==arm]) for arm in EXPECTED_ARMS}
    broad_paired,broad_pair_rows=paired_contrast(joined,"broad")
    strict_paired,strict_pair_rows=paired_contrast(joined,"strict")
    broad_unpaired=unpaired_contrast(metrics,"broad")
    strict_unpaired=unpaired_contrast(metrics,"strict")

    out.mkdir(parents=True,exist_ok=False)
    joined_path=out/"MERGE_C_LOW_HPRIOR_VALIDATION_REVEALED_JOIN.csv"
    paired_path=out/"MERGE_C_LOW_HPRIOR_VALIDATION_MATCHED_PAIR_OUTCOMES.csv"
    summary_path=out/"MERGE_C_LOW_HPRIOR_VALIDATION_SUMMARY_V1.json"
    by_arm_path=out/"MERGE_C_LOW_HPRIOR_VALIDATION_BY_ARM.csv"

    joined.to_csv(joined_path,index=False,encoding="utf-8-sig")
    pair_out=broad_pair_rows.rename(columns={
        "valid_for_paired":"broad_valid",
        "C_positive":"broad_C_positive",
        "CONTROL_positive":"broad_CONTROL_positive",
    }).merge(
        strict_pair_rows.rename(columns={
            "valid_for_paired":"strict_valid",
            "C_positive":"strict_C_positive",
            "CONTROL_positive":"strict_CONTROL_positive",
        }),on="match_id",validate="one_to_one"
    )
    pair_out.to_csv(paired_path,index=False,encoding="utf-8")

    arm_rows=[]
    for arm in ["C_LOW_HPRIOR","CONTROL_NONLOW_HPRIOR"]:
        m=metrics[arm]
        arm_rows.append({
            "arm":arm,
            "n_total":m["n_total"],
            "n_assessable":m["n_assessable"],
            **{f"label__{k}":v for k,v in m["label_counts"].items()},
            "strict_positive_n":m["strict_positive_n"],
            "strict_positive_rate":m["strict_positive_rate"],
            "strict_ci95_low":m["strict_wilson95"][0],
            "strict_ci95_high":m["strict_wilson95"][1],
            "broad_positive_n":m["broad_positive_n"],
            "broad_positive_rate":m["broad_positive_rate"],
            "broad_ci95_low":m["broad_wilson95"][0],
            "broad_ci95_high":m["broad_wilson95"][1],
        })
    pd.DataFrame(arm_rows).to_csv(by_arm_path,index=False,encoding="utf-8")

    summary={
      "schema_version":"akerpuls-merge-c-low-hprior-independent-validation-reveal-v1",
      "status":STATUS,
      "generated_utc":datetime.now(timezone.utc).isoformat(),
      "git_head":head,
      "parents":{
        "labels_freeze_sha256":EXPECTED_LABEL_FREEZE_SHA,
        "labels_sha256":EXPECTED_LABELS_SHA,
        "viewer_freeze_sha256":EXPECTED_VIEWER_FREEZE_SHA,
        "sample_population_sha256":EXPECTED_SAMPLE_POPULATION_SHA,
        "matching_sha256":EXPECTED_MATCHING_SHA,
        "blind_key_sha256":EXPECTED_BLIND_KEY_SHA,
      },
      "predeclared_analysis":{
        "primary_endpoint":"broad_positive = TYDLIG_MERGE + MÖJLIG_MERGE",
        "secondary_endpoint":"strict_positive = TYDLIG_MERGE",
        "primary_contrast":"CONTROL_NONLOW_HPRIOR vs C_LOW_HPRIOR within S2026>P90",
        "primary_test":"exact two-sided McNemar on matched broad-positive labels",
        "secondary_test":"exact two-sided McNemar on matched strict-positive labels",
        "paired_exclusion":"exclude matched pair if either member is EJ_BEDÖMBAR",
        "TVEKSAM_is_nonpositive":True,
      },
      "by_arm":metrics,
      "primary_broad_paired":broad_paired,
      "secondary_strict_paired":strict_paired,
      "descriptive_broad_unpaired":broad_unpaired,
      "descriptive_strict_unpaired":strict_unpaired,
      "interpretation_limits":[
        "This is a targeted independent validation using all 29 previously unseen C-tier pairs.",
        "Each C pair was matched 1:1 to a previously unseen A/B control on frozen S2026 percentile before labels.",
        "The test addresses whether very low Hprior adds veto information within S2026>P90.",
        "No operational threshold, fusion weight, or automatic merge policy is selected in this stage.",
      ],
      "guards":{
        "fusion_executed":False,
        "thresholds_tuned":False,
        "automatic_merge":False,
        "cross_block_merge_allowed":False,
        "geometry_mutated":False,
      },
      "next":"REVIEW_LOW_HPRIOR_VETO_RESULT_AND_DECIDE_OPERATIONAL_MERGE_POLICY",
    }
    summary_path.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    print(f"STATUS={STATUS}")
    print("REVEALED_ARMS=C_LOW_HPRIOR:29 | CONTROL_NONLOW_HPRIOR:29")
    for arm in ["C_LOW_HPRIOR","CONTROL_NONLOW_HPRIOR"]:
        m=metrics[arm]; lc=m["label_counts"]
        print(
            f"ARM={arm} N={m['n_total']} ASSESSABLE={m['n_assessable']} "
            f"TYDLIG={lc['TYDLIG_MERGE']} MOJLIG={lc['MÖJLIG_MERGE']} "
            f"TVEKSAM={lc['TVEKSAM']} BEHALL={lc['BEHÅLL_GRÄNS']} EJ={lc['EJ_BEDÖMBAR']} "
            f"STRICT={m['strict_positive_rate']:.6f} BROAD={m['broad_positive_rate']:.6f}"
        )
    print(
        "PRIMARY_BROAD_MATCHED="
        f"VALID_PAIRS:{broad_paired['matched_pairs_valid']} "
        f"CONTROL_POS_C_NEG:{broad_paired['discordant_CONTROL_positive_C_negative']} "
        f"CONTROL_NEG_C_POS:{broad_paired['discordant_CONTROL_negative_C_positive']} "
        f"RD_CONTROL_MINUS_C:{broad_paired['paired_risk_difference_CONTROL_minus_C']:.6f} "
        f"MCNEMAR_P:{broad_paired['mcnemar_exact_two_sided_p']:.8g}"
    )
    print(
        "SECONDARY_STRICT_MATCHED="
        f"VALID_PAIRS:{strict_paired['matched_pairs_valid']} "
        f"CONTROL_POS_C_NEG:{strict_paired['discordant_CONTROL_positive_C_negative']} "
        f"CONTROL_NEG_C_POS:{strict_paired['discordant_CONTROL_negative_C_positive']} "
        f"RD_CONTROL_MINUS_C:{strict_paired['paired_risk_difference_CONTROL_minus_C']:.6f} "
        f"MCNEMAR_P:{strict_paired['mcnemar_exact_two_sided_p']:.8g}"
    )
    print(f"SUMMARY_SHA256={sha(summary_path)}")
    print(f"JOIN_SHA256={sha(joined_path)}")
    print(f"PAIRED_OUTCOMES_SHA256={sha(paired_path)}")
    print("FUSION_EXECUTED=FALSE THRESHOLDS_TUNED=FALSE AUTOMATIC_MERGE=FALSE")
    print("CROSS_BLOCK_MERGE_ALLOWED=FALSE GEOMETRY_MUTATED=FALSE")
    print("NEXT=REVIEW_LOW_HPRIOR_VETO_RESULT_AND_DECIDE_OPERATIONAL_MERGE_POLICY")
    print(f"OUTPUT={out}")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
