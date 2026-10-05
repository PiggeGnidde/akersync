#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reveal and analyze the independent blind A/B merge validation.

Authorized only after the 100 human labels have been formally frozen.

Primary endpoint:
  broad positive = TYDLIG_MERGE + MÖJLIG_MERGE among assessable
Secondary endpoint:
  strict positive = TYDLIG_MERGE among assessable
Primary contrast:
  A_CONFIRMED_HIGH vs B_SAT_HIGH_H_MID

No fusion, no threshold tuning, no automatic merge, no cross-block merge,
no geometry mutation.
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

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"

LABEL_FREEZE_DIR = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_ab_independent_blind_validation_labels_freeze_v1")
LABEL_FREEZE_JSON = LABEL_FREEZE_DIR / "AKERPULS_MERGE_AB_INDEPENDENT_BLIND_VALIDATION_LABELS_FREEZE_V1.json"
LABELS = LABEL_FREEZE_DIR / "merge_ab_independent_validation_labels_frozen.csv"

VIEWER_DIR = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_ab_independent_blind_validation_viewer_v1")
BLIND_KEY = VIEWER_DIR / "AB_VALIDATION_BLIND_KEY_DO_NOT_OPEN.csv"

EXPECTED_LABEL_FREEZE_SHA = "9c9183fe720eea38e59384a1cf63a6cda9c1fc7bebfce09a362b71431e212b1a"
EXPECTED_LABELS_SHA = "a33763d81b50db263fed265866cca7b6cd3dbe6740ed72cfb4967063c7aab2a4"
EXPECTED_VIEWER_FREEZE_SHA = "c7b7173314255074e0f34c9efbe35a9a464119fa4621ff924dbbbdd500f96fb1"
EXPECTED_RANKING_FREEZE_SHA = "2f98d504c61ba71da396e4d459ffd6b3e5d2feaacbe5a8faaab9635d2882ef26"
EXPECTED_SAMPLE_POPULATION_SHA = "f5df348a57660df3eadbd8ab7c0bc35b90985b9f22f5540735e2cf56bf0ed677"
EXPECTED_BLIND_KEY_SHA = "fec621243d0b7cefc33d345be6ee361bd06cdba802a2d72b3925fa3257f7dc5f"

DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_ab_independent_validation_reveal_v1")
STATUS = "PASS_TO_AB_INDEPENDENT_VALIDATION_REVIEW"
EXPECTED_ROWS = 100
EXPECTED_TIERS = {"A_CONFIRMED_HIGH": 50, "B_SAT_HIGH_H_MID": 50}
LABEL_ORDER = ["TYDLIG_MERGE","MÖJLIG_MERGE","TVEKSAM","BEHÅLL_GRÄNS","EJ_BEDÖMBAR"]


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


def fisher_two_sided(a:int,b:int,c:int,d:int) -> float:
    r1,r2=a+b,c+d
    c1=a+c
    n=r1+r2
    lo=max(0,c1-r2)
    hi=min(r1,c1)
    def prob(x:int)->float:
        return (math.comb(c1,x)*math.comb(n-c1,r1-x))/math.comb(n,r1)
    pobs=prob(a)
    return min(1.0,sum(prob(x) for x in range(lo,hi+1) if prob(x) <= pobs + 1e-12))


def odds_ratio(a:int,b:int,c:int,d:int):
    den=b*c
    num=a*d
    if den==0:
        if num==0:
            return None
        return float("inf")
    return float(num/den)


def wilson(k:int,n:int,z:float=1.959963984540054):
    if n<=0:
        return (None,None)
    p=k/n
    den=1+z*z/n
    center=(p+z*z/(2*n))/den
    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return max(0.0,center-half),min(1.0,center+half)


def tier_metrics(g:pd.DataFrame)->dict:
    counts={lab:int((g["merge_label"]==lab).sum()) for lab in LABEL_ORDER}
    assess=g.loc[g["merge_label"]!="EJ_BEDÖMBAR"]
    n=len(assess)
    strict=int((assess["merge_label"]=="TYDLIG_MERGE").sum())
    broad=int(assess["merge_label"].isin(["TYDLIG_MERGE","MÖJLIG_MERGE"]).sum())
    sci=wilson(strict,n)
    bci=wilson(broad,n)
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


def contrast(metrics:dict,endpoint:str)->dict:
    A=metrics["A_CONFIRMED_HIGH"]
    B=metrics["B_SAT_HIGH_H_MID"]
    key=f"{endpoint}_positive_n"
    a=int(A[key]); b=int(A["n_assessable"]-a)
    c=int(B[key]); d=int(B["n_assessable"]-c)
    ar=a/A["n_assessable"]; br=c/B["n_assessable"]
    return {
        "endpoint":endpoint,
        "A_positive":a,
        "A_n":A["n_assessable"],
        "A_rate":ar,
        "B_positive":c,
        "B_n":B["n_assessable"],
        "B_rate":br,
        "risk_difference_A_minus_B":ar-br,
        "odds_ratio":odds_ratio(a,b,c,d),
        "fisher_two_sided_p":fisher_two_sided(a,b,c,d),
    }


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--output-dir",default=str(DEFAULT_OUT))
    args=ap.parse_args()

    head=git_guard()
    out=Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Reveal output already exists: {out}")

    if not LABEL_FREEZE_JSON.is_file() or sha256_file(LABEL_FREEZE_JSON)!=EXPECTED_LABEL_FREEZE_SHA:
        raise RuntimeError("Label freeze missing or changed")
    lf=json.loads(LABEL_FREEZE_JSON.read_text(encoding="utf-8-sig"))
    if lf.get("status")!="FROZEN_AKERPULS_MERGE_AB_INDEPENDENT_BLIND_VALIDATION_LABELS_V1":
        raise RuntimeError("Unexpected label-freeze status")
    if lf.get("viewer_freeze_sha256")!=EXPECTED_VIEWER_FREEZE_SHA:
        raise RuntimeError("Viewer-freeze lineage changed")
    if lf.get("sh_gated_ranking_freeze_sha256")!=EXPECTED_RANKING_FREEZE_SHA:
        raise RuntimeError("Ranking-freeze lineage changed")
    if lf.get("sample_population_sha256")!=EXPECTED_SAMPLE_POPULATION_SHA:
        raise RuntimeError("Sample lineage changed")
    if lf.get("blind_key_sha256")!=EXPECTED_BLIND_KEY_SHA:
        raise RuntimeError("Blind-key lineage changed")

    if not LABELS.is_file() or sha256_file(LABELS)!=EXPECTED_LABELS_SHA:
        raise RuntimeError("Frozen labels missing or changed")
    if not BLIND_KEY.is_file() or sha256_file(BLIND_KEY)!=EXPECTED_BLIND_KEY_SHA:
        raise RuntimeError("Blind key missing or changed")

    print("AKERPULS MERGE A/B INDEPENDENT VALIDATION REVEAL V1")
    print(f"GIT_HEAD={head}")
    print(f"LABELS_FREEZE_SHA256={EXPECTED_LABEL_FREEZE_SHA}")
    print(f"BLIND_KEY_SHA256={EXPECTED_BLIND_KEY_SHA}")
    print("BLIND_KEY_REVEAL_AUTHORIZED_BY_FROZEN_LABELS=TRUE")
    print("PROGRESS=LOAD_FROZEN_LABELS_AND_REVEAL_A_B")

    labels=pd.read_csv(LABELS,encoding="utf-8-sig",dtype=str,keep_default_na=False)
    key=pd.read_csv(BLIND_KEY,encoding="utf-8-sig",dtype=str,keep_default_na=False)
    if len(labels)!=EXPECTED_ROWS or len(key)!=EXPECTED_ROWS:
        raise RuntimeError("Expected exactly 100 rows in labels and key")
    labels["blind_index"]=pd.to_numeric(labels["blind_index"],errors="raise").astype(int)
    key["blind_index"]=pd.to_numeric(key["blind_index"],errors="raise").astype(int)
    if labels["blind_index"].nunique()!=EXPECTED_ROWS or key["blind_index"].nunique()!=EXPECTED_ROWS:
        raise RuntimeError("blind_index not unique")
    if sorted(labels["blind_index"])!=list(range(1,101)) or sorted(key["blind_index"])!=list(range(1,101)):
        raise RuntimeError("blind_index sets must be 1..100")

    joined=labels.merge(key,on="blind_index",how="outer",validate="one_to_one",indicator=True)
    if len(joined)!=EXPECTED_ROWS or not (joined["_merge"]=="both").all():
        raise RuntimeError("Frozen labels and blind key did not join 1:1")
    joined=joined.drop(columns=["_merge"])

    got=joined["sh_tier"].value_counts().to_dict()
    if got!=EXPECTED_TIERS:
        raise RuntimeError(f"Tier census changed: {got}")

    metrics={tier:tier_metrics(joined.loc[joined["sh_tier"]==tier]) for tier in EXPECTED_TIERS}
    broad=contrast(metrics,"broad")
    strict=contrast(metrics,"strict")

    out.mkdir(parents=True,exist_ok=False)
    joined_path=out/"MERGE_AB_INDEPENDENT_VALIDATION_REVEALED_JOIN.csv"
    by_tier_path=out/"MERGE_AB_INDEPENDENT_VALIDATION_BY_TIER.csv"
    contrast_path=out/"MERGE_AB_INDEPENDENT_VALIDATION_CONTRASTS.csv"
    summary_path=out/"MERGE_AB_INDEPENDENT_VALIDATION_SUMMARY_V1.json"

    joined.to_csv(joined_path,index=False,encoding="utf-8-sig")
    rows=[]
    for tier in ["A_CONFIRMED_HIGH","B_SAT_HIGH_H_MID"]:
        m=metrics[tier]
        rows.append({
            "tier":tier,
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
    pd.DataFrame(rows).to_csv(by_tier_path,index=False,encoding="utf-8")
    pd.DataFrame([
        {"priority":"PRIMARY",**broad},
        {"priority":"SECONDARY",**strict},
    ]).to_csv(contrast_path,index=False,encoding="utf-8")

    summary={
        "schema_version":"akerpuls-merge-ab-independent-validation-reveal-v1",
        "status":STATUS,
        "generated_utc":datetime.now(timezone.utc).isoformat(),
        "git_head":head,
        "parents":{
            "labels_freeze_sha256":EXPECTED_LABEL_FREEZE_SHA,
            "labels_sha256":EXPECTED_LABELS_SHA,
            "viewer_freeze_sha256":EXPECTED_VIEWER_FREEZE_SHA,
            "sh_gated_ranking_freeze_sha256":EXPECTED_RANKING_FREEZE_SHA,
            "sample_population_sha256":EXPECTED_SAMPLE_POPULATION_SHA,
            "blind_key_sha256":EXPECTED_BLIND_KEY_SHA,
        },
        "predeclared_analysis":{
            "primary_endpoint":"broad_positive = TYDLIG_MERGE + MÖJLIG_MERGE among assessable",
            "secondary_endpoint":"strict_positive = TYDLIG_MERGE among assessable",
            "primary_contrast":"A_CONFIRMED_HIGH vs B_SAT_HIGH_H_MID",
            "EJ_BEDÖMBAR_excluded":True,
            "TVEKSAM_is_nonpositive":True,
        },
        "by_tier":metrics,
        "primary_broad_contrast":broad,
        "secondary_strict_contrast":strict,
        "interpretation_limits":[
            "This is an independent validation sample with the first 100 audit pairs excluded.",
            "A and B were sampled 50/50 by design, so pooled 81% broad rate is not a population prevalence estimate.",
            "The A-vs-B contrast tests incremental value of Hprior within S2026>P90, not the absolute correctness of all merge candidates.",
            "No operational threshold, fusion weight, or automatic merge decision is selected in this stage.",
        ],
        "guards":{
            "fusion_executed":False,
            "fusion_weight_selected":False,
            "thresholds_tuned":False,
            "automatic_merge":False,
            "cross_block_merge_allowed":False,
            "geometry_mutated":False,
        },
        "next":"REVIEW_INDEPENDENT_A_VS_B_RESULTS_AND_DECIDE_OPERATIONAL_MERGE_POLICY",
    }
    summary_path.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    print(f"STATUS={STATUS}")
    print("REVEALED_TIERS=A_CONFIRMED_HIGH:50 | B_SAT_HIGH_H_MID:50")
    for tier in ["A_CONFIRMED_HIGH","B_SAT_HIGH_H_MID"]:
        m=metrics[tier]; lc=m["label_counts"]
        print(
            f"TIER={tier} N={m['n_total']} ASSESSABLE={m['n_assessable']} "
            f"TYDLIG={lc['TYDLIG_MERGE']} MOJLIG={lc['MÖJLIG_MERGE']} "
            f"TVEKSAM={lc['TVEKSAM']} BEHALL={lc['BEHÅLL_GRÄNS']} EJ={lc['EJ_BEDÖMBAR']} "
            f"STRICT={m['strict_positive_rate']:.6f} BROAD={m['broad_positive_rate']:.6f}"
        )
    print(
        f"PRIMARY_BROAD_A_MINUS_B_RD={broad['risk_difference_A_minus_B']:.6f} "
        f"OR={broad['odds_ratio']} FISHER_P={broad['fisher_two_sided_p']:.8g}"
    )
    print(
        f"SECONDARY_STRICT_A_MINUS_B_RD={strict['risk_difference_A_minus_B']:.6f} "
        f"OR={strict['odds_ratio']} FISHER_P={strict['fisher_two_sided_p']:.8g}"
    )
    print(f"SUMMARY_SHA256={sha256_file(summary_path)}")
    print(f"JOIN_SHA256={sha256_file(joined_path)}")
    print("FUSION_EXECUTED=FALSE THRESHOLDS_TUNED=FALSE AUTOMATIC_MERGE=FALSE")
    print("CROSS_BLOCK_MERGE_ALLOWED=FALSE GEOMETRY_MUTATED=FALSE")
    print("NEXT=REVIEW_INDEPENDENT_A_VS_B_RESULTS_AND_DECIDE_OPERATIONAL_MERGE_POLICY")
    print(f"OUTPUT={out}")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
