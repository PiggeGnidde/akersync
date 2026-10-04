#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Formal freeze for ÅkerFrö Rotation v1.1 downstream of frozen v0a/C8."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
FREEZE_DIR=ROOT/"work"/"akerfro_rotation_v1a"/"freeze"
MANIFEST=FREEZE_DIR/"akerfro_rotation_v1a_freeze_manifest.json"

FILES=[
    "config/akerfro_rotation_v1a.json",
    "analysis/akerfro_ertor_v0a/build_rotation_v1a.py",
    "analysis/akerfro_ertor_v0a/verify_rotation_v1a.py",
    "analysis/akerfro_ertor_v0a/audit_rotation_v1a_final.py",
    "analysis/akerfro_ertor_v0a/ROTATION_V1A_CANDIDATE.md",
    "data/derived/akerfro_rotation_v1a/akerfro_rotation_v1a_fields.parquet",
    "data/derived/akerfro_rotation_v1a/akerfro_rotation_v1a_released_fields.csv",
    "data/derived/akerfro_rotation_v1a/akerfro_rotation_v1a_summary.json",
    "work/akerfro_rotation_v1a/bestmatch_impact/topn_comparison.csv",
    "work/akerfro_rotation_v1a/bestmatch_impact/bestmatch_rotation_v1a_impact_summary.json",
]

EXPECTED={
    "population":128636,
    "released":43,
    "to_A":28,
    "to_B":15,
    "classes":{
        "A_STRONG_CANDIDATE":7875,
        "B_PHYSICAL_CANDIDATE":14897,
        "C_ROTATION_CAUTION":1381,
        "D_NOT_HIGH_PHYSICAL_MATCH":104483,
    },
}

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def git_value(*args:str)->str:
    try:
        return subprocess.check_output(["git",*args],cwd=ROOT,text=True).strip()
    except Exception:
        return "UNKNOWN"

def validate()->dict:
    p=ROOT/"data"/"derived"/"akerfro_rotation_v1a"/"akerfro_rotation_v1a_fields.parquet"
    df=pd.read_parquet(p)
    if len(df)!=EXPECTED["population"]:
        raise RuntimeError(f"Population drift: {len(df):,}")
    counts={str(k):int(v) for k,v in df["artkandidat_class_v1a"].value_counts().items()}
    if counts!=EXPECTED["classes"]:
        raise RuntimeError(f"Class drift: {counts}")
    rel=df[df["rotation_v1a_release_candidate"].fillna(False).astype(bool)].copy()
    if len(rel)!=EXPECTED["released"]:
        raise RuntimeError(f"Released drift: {len(rel)}")
    a=int(rel["artkandidat_class_v1a"].astype(str).eq("A_STRONG_CANDIDATE").sum())
    b=int(rel["artkandidat_class_v1a"].astype(str).eq("B_PHYSICAL_CANDIDATE").sum())
    if (a,b)!=(EXPECTED["to_A"],EXPECTED["to_B"]):
        raise RuntimeError(f"Release split drift: A={a}, B={b}")

    # Only legal class transitions are C -> A/B.
    changed=df["artkandidat_class_v0a"].astype(str).ne(df["artkandidat_class_v1a"].astype(str))
    bad=df.loc[changed & ~(
        df["artkandidat_class_v0a"].astype(str).eq("C_ROTATION_CAUTION")
        & df["artkandidat_class_v1a"].astype(str).isin(["A_STRONG_CANDIDATE","B_PHYSICAL_CANDIDATE"])
    )]
    if len(bad):
        raise RuntimeError("Illegal class transition outside C -> A/B")

    # Discovery-case regression anchors.
    by=df.set_index(df["current_field_id"].astype(str))
    anchors={
        "61723351559|2A":("C_ROTATION_CAUTION","A_STRONG_CANDIDATE","ROTATION_OK_BOUNDARY_SPILL"),
        "61723351559|2B":("C_ROTATION_CAUTION","A_STRONG_CANDIDATE","ROTATION_OK_BOUNDARY_SPILL"),
        "61723353349|94A":("C_ROTATION_CAUTION","C_ROTATION_CAUTION","CAUTION_RECENT_CONSERVART"),
    }
    for fid,(old,new,status) in anchors.items():
        if fid not in by.index:
            raise RuntimeError(f"Missing anchor {fid}")
        r=by.loc[fid]
        got=(str(r["artkandidat_class_v0a"]),str(r["artkandidat_class_v1a"]),str(r["rotation_status_v1a"]))
        if got!=(old,new,status):
            raise RuntimeError(f"Anchor failed {fid}: {got}")

    impact=json.loads(
        (ROOT/"work"/"akerfro_rotation_v1a"/"bestmatch_impact"/"bestmatch_rotation_v1a_impact_summary.json")
        .read_text(encoding="utf-8-sig")
    )
    if int(impact["old_bestmatch_candidate_fields"])!=15967:
        raise RuntimeError("BestMatch old-candidate anchor drift")
    if int(impact["new_bestmatch_candidate_fields"])!=16004:
        raise RuntimeError("BestMatch v1.1-impact candidate anchor drift")
    if int(impact["released_rotation_fields_present_in_d5"])!=37:
        raise RuntimeError("BestMatch D5-present release anchor drift")
    if int(impact["released_rotation_fields_outside_d5"])!=6:
        raise RuntimeError("BestMatch D5-outside release anchor drift")

    top=pd.read_csv(ROOT/"work"/"akerfro_rotation_v1a"/"bestmatch_impact"/"topn_comparison.csv")
    hit_delta=(pd.to_numeric(top["new_historical_positive_hits"],errors="coerce")
               -pd.to_numeric(top["old_historical_positive_hits"],errors="coerce"))
    if not hit_delta.fillna(999).eq(0).all():
        raise RuntimeError("Historical-positive top-N hit regression changed")

    return {
        "population_fields":len(df),
        "released_fields":len(rel),
        "released_to_A":a,
        "released_to_B":b,
        "class_counts":counts,
        "bestmatch_impact":{
            "old_candidates":15967,
            "new_candidates":16004,
            "released_present_in_d5":37,
            "released_outside_d5":6,
            "topn_historical_hit_delta_all_zero":True,
        },
        "staffanstorp_regression_anchors":"PASS",
    }

def main()->int:
    branch=git_value("branch","--show-current")
    if branch!="feature/akerfro-rotation-v1a":
        raise RuntimeError(f"Freeze must run on feature/akerfro-rotation-v1a; got {branch}")
    if git_value("status","--porcelain"):
        raise RuntimeError("Tracked working tree is not clean; commit/stash before freeze")

    missing=[rel for rel in FILES if not (ROOT/rel).is_file()]
    if missing:
        raise FileNotFoundError("Cannot freeze; missing:\n  "+"\n  ".join(missing))

    anchors=validate()
    entries={}
    for rel in FILES:
        p=ROOT/rel
        entries[rel]={"bytes":int(p.stat().st_size),"sha256":sha256(p)}

    FREEZE_DIR.mkdir(parents=True,exist_ok=True)
    manifest={
        "schema_version":"akerfro-rotation-v1a-freeze-manifest-v1",
        "freeze_name":"akerfro-rotation-v1a",
        "status":"FORMALLY_FROZEN_LOCAL_ARTIFACT_SET",
        "scope":"lineage-aware rotation correction downstream of frozen ÅkerFrö v0a/C8",
        "git":{
            "repository":"PiggeGnidde/akersync",
            "branch":branch,
            "head_at_freeze":git_value("rev-parse","HEAD"),
        },
        "lineage":{
            "akerfro_v0a":"frozen upstream; read-only",
            "akerminne":"frozen ÅkerMinne v1 component lineage; read-only",
            "bestmatch_v0b":"used only for impact diagnostics; not modified",
        },
        "policy_summary":{
            "recent_window":"2021-2025 for candidate year 2026",
            "strict_boundary_spill":"another current field >=99.9% of historical CONSERVART polygon AND this field <0.1%, with same_admin_key/historical-primary/mutual-primary all false",
            "field_release":"all recent CONSERVART components must be strict spill; no recent clean CONSERVART/OTHER_PEA/FABA may remain",
            "released_status":"ROTATION_OK_BOUNDARY_SPILL",
            "A_B_split":"unchanged predecessor prior from frozen v0a",
        },
        "anchors":anchors,
        "guardrails":[
            "No frozen ÅkerFrö v0a/C8 artifact is modified.",
            "No ÄrtMatch or predecessor model is retuned.",
            "Boundary spill is lineage evidence, not proof that crop never touched any part of the current polygon.",
            "Mixed/partial CONSERVART remains caution unless every recent target component satisfies the strict spill rule.",
            "Recent clean other pea or faba continues to block release.",
            "BestMatch v0b remains separately frozen and unchanged.",
        ],
        "files":entries,
    }
    MANIFEST.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    print("="*108)
    print("ÅkerFrö Rotation v1.1 · FORMAL FREEZE")
    print("="*108)
    print(f"Git HEAD: {manifest['git']['head_at_freeze']}")
    print(f"Files frozen: {len(entries)}")
    print(f"Population: {anchors['population_fields']:,}")
    print(f"Released: {anchors['released_fields']} = A {anchors['released_to_A']} + B {anchors['released_to_B']}")
    print(f"Classes: {anchors['class_counts']}")
    print(f"Manifest: {MANIFEST}")
    print("="*108)
    print("AKERFRO ROTATION V1.1 FORMAL FREEZE: PASS")
    print("="*108)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
