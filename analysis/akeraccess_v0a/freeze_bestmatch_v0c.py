#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Formal freeze for ÅkerFrö × ÅkerAccess BestMatch v0c."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
POLICY=ROOT/"config"/"akerfro_akeraccess_bestmatch_v0c_freeze.json"
FREEZE_DIR=ROOT/"work"/"akeraccess_v0a"/"bestmatch_v0c_freeze"
MANIFEST=FREEZE_DIR/"bestmatch_v0c_freeze_manifest.json"
ROT_FREEZE=ROOT/"work"/"akerfro_rotation_v1a"/"freeze"/"akerfro_rotation_v1a_freeze_manifest.json"
V0B_FREEZE=ROOT/"work"/"akeraccess_v0a"/"bestmatch_v0b_freeze"/"bestmatch_v0b_freeze_manifest.json"

FILES=[
    "config/akerfro_akeraccess_bestmatch_v0c_freeze.json",
    "analysis/akeraccess_v0a/build_bestmatch_v0c_product.py",
    "analysis/akeraccess_v0a/verify_bestmatch_v0c.py",
    "analysis/akeraccess_v0a/BESTMATCH_V0C_FREEZE.md",
    "data/derived/akerfro_akeraccess_bestmatch_v0c/bestmatch_v0c_fields.parquet",
    "data/derived/akerfro_akeraccess_bestmatch_v0c/bestmatch_v0c_top5000.csv",
    "data/derived/akerfro_akeraccess_bestmatch_v0c/bestmatch_v0c_vs_v0b_topn.csv",
    "data/derived/akerfro_akeraccess_bestmatch_v0c/bestmatch_v0c_summary.json",
]

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def fp(path:Path)->dict:
    return {"path":str(path),"bytes":int(path.stat().st_size),"sha256":sha256(path)}

def git_value(*args:str)->str:
    try:
        return subprocess.check_output(["git",*args],cwd=ROOT,text=True).strip()
    except Exception:
        return "UNKNOWN"

def validate(policy:dict)->dict:
    prod=pd.read_parquet(ROOT/"data"/"derived"/"akerfro_akeraccess_bestmatch_v0c"/"bestmatch_v0c_fields.parquet")
    summary=json.loads(
        (ROOT/"data"/"derived"/"akerfro_akeraccess_bestmatch_v0c"/"bestmatch_v0c_summary.json")
        .read_text(encoding="utf-8-sig")
    )
    comp=pd.read_csv(ROOT/"data"/"derived"/"akerfro_akeraccess_bestmatch_v0c"/"bestmatch_v0c_vs_v0b_topn.csv")

    n=int(policy["expected_candidate_fields"])
    if len(prod)!=n: raise RuntimeError(f"candidate drift: {len(prod)} != {n}")
    counts={str(k):int(v) for k,v in prod["artkandidat_class"].value_counts().items()}
    if counts!={str(k):int(v) for k,v in policy["expected_class_counts"].items()}:
        raise RuntimeError(f"class drift: {counts}")
    if prod["bestmatch_v0c_rank"].astype(int).tolist()!=list(range(1,n+1)):
        raise RuntimeError("rank sequence drift")
    if float(summary["score_identity_max_abs_diff_vs_frozen_d5_balanced"])>1e-9:
        raise RuntimeError("score identity drift")
    if int(summary["vs_v0b"]["new_candidates"])!=37 or int(summary["vs_v0b"]["dropped_candidates"])!=0:
        raise RuntimeError("v0b set regression drift")

    got_churn={str(int(r.top_n)):int(r.new_v0c_entrants) for r in comp.itertuples(index=False)}
    exp_churn={str(k):int(v) for k,v in policy["expected_topn_churn"].items()}
    if got_churn!=exp_churn:
        raise RuntimeError(f"top-N churn drift: {got_churn}")
    got_hits={str(int(r.top_n)):int(r.new_historical_positive_hits) for r in comp.itertuples(index=False)}
    exp_hits={str(k):int(v) for k,v in policy["expected_balanced_historical_hits"].items()}
    if got_hits!=exp_hits:
        raise RuntimeError(f"top-N historical hits drift: {got_hits}")

    routed=int(prod["bjuv_proximity_d5_source"].astype(str).eq("ROAD_NETWORK_D4").sum())
    fallback=int(prod["bjuv_proximity_d5_source"].astype(str).eq("C10_STRAIGHTLINE_FALLBACK").sum())
    top800=prod.head(800)
    return {
        "candidate_fields":len(prod),
        "class_counts":counts,
        "new_candidates_vs_v0b":37,
        "dropped_candidates_vs_v0b":0,
        "new_A":int(summary["vs_v0b"]["new_A"]),
        "new_B":int(summary["vs_v0b"]["new_B"]),
        "routed_fields":routed,
        "straightline_fallback_fields":fallback,
        "route_coverage_pct":100.0*routed/len(prod),
        "historical_positive_fields":int(prod["historical_conservart_positive"].fillna(False).astype(bool).sum()),
        "top800_area_ha":float(pd.to_numeric(top800["field_area_ha"],errors="coerce").sum()),
        "top800_historical_positive_hits":int(top800["historical_conservart_positive"].fillna(False).astype(bool).sum()),
        "topn_churn":got_churn,
        "topn_historical_hits":got_hits,
        "score_identity_max_abs_diff":float(summary["score_identity_max_abs_diff_vs_frozen_d5_balanced"]),
    }

def main()->int:
    policy=json.loads(POLICY.read_text(encoding="utf-8-sig"))
    branch=git_value("branch","--show-current")
    if branch!="feature/akerfro-bestmatch-v0c":
        raise RuntimeError(f"Freeze must run on feature/akerfro-bestmatch-v0c; got {branch}")
    if git_value("status","--porcelain"):
        raise RuntimeError("Tracked working tree is not clean; commit/stash before freeze")

    missing=[rel for rel in FILES if not (ROOT/rel).is_file()]
    if missing:
        raise FileNotFoundError("Cannot freeze v0c; missing:\n  "+"\n  ".join(missing))
    for p in [ROT_FREEZE,V0B_FREEZE]:
        if not p.is_file(): raise FileNotFoundError(p)

    rotm=json.loads(ROT_FREEZE.read_text(encoding="utf-8-sig"))
    v0bm=json.loads(V0B_FREEZE.read_text(encoding="utf-8-sig"))
    if rotm.get("status")!="FORMALLY_FROZEN_LOCAL_ARTIFACT_SET":
        raise RuntimeError("Rotation v1.1 upstream is not formally frozen")
    if v0bm.get("status")!="FORMALLY_FROZEN_LOCAL_ARTIFACT_SET":
        raise RuntimeError("BestMatch v0b upstream is not formally frozen")

    anchors=validate(policy)
    entries={rel:fp(ROOT/rel) for rel in FILES}
    FREEZE_DIR.mkdir(parents=True,exist_ok=True)

    manifest={
        "schema_version":"akerfro-akeraccess-bestmatch-v0c-freeze-manifest-v1",
        "freeze_name":policy["freeze_name"],
        "status":"FORMALLY_FROZEN_LOCAL_ARTIFACT_SET",
        "git":{
            "repository":"PiggeGnidde/akersync",
            "branch":branch,
            "head_at_freeze":git_value("rev-parse","HEAD")
        },
        "selected_product":{
            "rotation_eligibility":"akerfro-rotation-v1a",
            "policy":"balanced_50_25_25",
            "hard_class_order":["A_STRONG_CANDIDATE","B_PHYSICAL_CANDIDATE"],
            "weights":policy["policy_weights"],
            "score":"0.50 ÄrtMatch + 0.25 road-based AreaLogistik + 0.25 ÅkerAccess v0a",
            "rank":"A before B; score descending within class; field_id tie-break",
        },
        "lineage":{
            "akerfro_rotation_v1a_freeze":fp(ROT_FREEZE),
            "bestmatch_v0b_freeze":fp(V0B_FREEZE),
            "v0b_role":"frozen policy/regression baseline; not modified",
            "eligibility_change_only":"37 lineage-released Rotation v1.1 fields enter D5/BestMatch; no v0b candidates are dropped"
        },
        "anchors":anchors,
        "guardrails":policy["guardrails"],
        "files":entries
    }
    MANIFEST.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    print("="*116)
    print("ÅkerFrö × ÅkerAccess BestMatch v0c · FORMAL FREEZE")
    print("="*116)
    print(f"Git HEAD: {manifest['git']['head_at_freeze']}")
    print(f"Candidates: {anchors['candidate_fields']:,}")
    print(f"A/B: {anchors['class_counts']}")
    print(f"vs v0b: +{anchors['new_candidates_vs_v0b']} new · {anchors['dropped_candidates_vs_v0b']} dropped")
    print(f"New A/B: {anchors['new_A']}/{anchors['new_B']}")
    print(f"Bjuv routes: {anchors['routed_fields']:,} routed · {anchors['straightline_fallback_fields']:,} fallback · {anchors['route_coverage_pct']:.2f}%")
    print(f"Top800: {anchors['top800_area_ha']:.1f} ha · historical positives {anchors['top800_historical_positive_hits']}")
    print(f"Manifest: {MANIFEST}")
    print("="*116)
    print("BESTMATCH v0c FORMAL FREEZE: PASS")
    print("="*116)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
