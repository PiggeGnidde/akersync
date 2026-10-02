#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Formal freeze for ÅkerFrö × ÅkerAccess BestMatch v0b."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
for p in (ROOT,ROOT/"src"):
    if str(p) not in sys.path:
        sys.path.insert(0,str(p))

from analysis.akeraccess_v0a.akerfro_access_bestmatch_d2 import discover_c10

POLICY=ROOT/"config"/"akerfro_akeraccess_bestmatch_v0b_freeze.json"
FREEZE_DIR=ROOT/"work"/"akeraccess_v0a"/"bestmatch_v0b_freeze"
MANIFEST=FREEZE_DIR/"bestmatch_v0b_freeze_manifest.json"

FILES=[
    "config/akerfro_akeraccess_bestmatch_v0b_freeze.json",
    "config/akerfro_akeraccess_d5.json",
    "config/akerfro_akeraccess_d2.json",
    "config/akerfro_ertor_c10.json",
    "analysis/akeraccess_v0a/akerfro_access_bestmatch_d2.py",
    "analysis/akeraccess_v0a/bjuv_route_distance_d4.py",
    "analysis/akeraccess_v0a/bestmatch_roadlogistics_d5.py",
    "analysis/akeraccess_v0a/build_bestmatch_v0b_product.py",
    "work/akeraccess_v0a/bjuv_route_d4/bestmatch_d4_fields.parquet",
    "work/akeraccess_v0a/bestmatch_d5/bestmatch_d5_fields.parquet",
    "work/akeraccess_v0a/bestmatch_d5/bestmatch_d5_policy_comparison.csv",
    "work/akeraccess_v0a/bestmatch_d5/bestmatch_d5_report.json",
    "data/derived/akeraccess_v0a/akeraccess_v0a_fields.parquet",
    "work/akeraccess_v0a/freeze_v0a/akeraccess_v0a_freeze_manifest.json",
    "data/derived/akerfro_akeraccess_bestmatch_v0b/bestmatch_v0b_fields.parquet",
    "data/derived/akerfro_akeraccess_bestmatch_v0b/bestmatch_v0b_top5000.csv",
    "data/derived/akerfro_akeraccess_bestmatch_v0b/bestmatch_v0b_summary.json"
]


def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(path:Path)->dict:
    return {"path":str(path),"bytes":path.stat().st_size,"sha256":sha256(path)}


def git_head()->str:
    try:
        return subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    except Exception:
        return "UNKNOWN"


def validate(policy:dict)->dict:
    prodp=ROOT/"data/derived/akerfro_akeraccess_bestmatch_v0b/bestmatch_v0b_fields.parquet"
    d5p=ROOT/"work/akeraccess_v0a/bestmatch_d5/bestmatch_d5_fields.parquet"
    evp=ROOT/"work/akeraccess_v0a/bestmatch_d5/bestmatch_d5_policy_comparison.csv"

    prod=pd.read_parquet(prodp)
    d5=pd.read_parquet(d5p)
    ev=pd.read_csv(evp)

    n=int(policy["expected_candidate_fields"])
    if len(prod)!=n:
        raise RuntimeError(f"Product candidate count drift: {len(prod):,} != {n:,}")
    if prod["field_id"].astype(str).duplicated().any():
        raise RuntimeError("Duplicate field_id in frozen BestMatch product")

    classes={str(k):int(v) for k,v in prod["artkandidat_class"].value_counts().items()}
    if classes!=policy["expected_class_counts"]:
        raise RuntimeError(f"Class count drift: {classes}")

    route=policy["expected_bjuv_route_coverage"]
    routed=int(prod["bjuv_proximity_d5_source"].eq("ROAD_NETWORK_D4").sum())
    fallback=int(prod["bjuv_proximity_d5_source"].eq("C10_STRAIGHTLINE_FALLBACK").sum())
    if routed!=int(route["routed"]) or fallback!=int(route["straightline_fallback"]):
        raise RuntimeError(f"Bjuv route/fallback drift: {routed}/{fallback}")

    hist=int(prod["historical_conservart_positive"].sum())
    if hist!=int(policy["expected_historical_positive_fields"]):
        raise RuntimeError(f"Historical-positive count drift: {hist}")

    if not prod.iloc[:7421]["artkandidat_class"].eq("A_STRONG_CANDIDATE").all():
        raise RuntimeError("Hard A-before-B rank contract failed")
    if not prod.iloc[7421:]["artkandidat_class"].eq("B_PHYSICAL_CANDIDATE").all():
        raise RuntimeError("Hard A-before-B rank contract failed")

    top800=prod.head(800)
    area=float(pd.to_numeric(top800["field_area_ha"],errors="coerce").sum())
    lo,hi=map(float,policy["expected_top800_area_ha_range"])
    if not lo<=area<=hi:
        raise RuntimeError(f"Top800 area drift: {area}")
    hits800=int(top800["historical_conservart_positive"].sum())
    if hits800!=int(policy["expected_balanced_hits"]["800"]):
        raise RuntimeError(f"Top800 historical hits drift: {hits800}")

    # Freeze all requested top-N historical hit anchors from the D5 diagnostic table.
    q=ev[ev["ranking"].eq("rank_d5_balanced")].copy()
    got={str(int(r.top_n)):int(r.historical_positive_hits) for r in q.itertuples(index=False)}
    exp={str(k):int(v) for k,v in policy["expected_balanced_hits"].items()}
    if got!=exp:
        raise RuntimeError(f"Balanced diagnostic hit anchors drift: got={got}, expected={exp}")

    # D5 chosen score/rank must be identical to the canonical frozen aliases.
    src=d5[d5["d5_candidate"].fillna(False).astype(bool)][
        ["field_id","bestmatch_d5_balanced_score","rank_d5_balanced"]
    ].copy()
    src["field_id"]=src["field_id"].astype(str)
    chk=prod[["field_id","bestmatch_v0b_score","bestmatch_v0b_rank"]].merge(
        src,on="field_id",how="left",validate="one_to_one"
    )
    score_delta=(
        pd.to_numeric(chk["bestmatch_v0b_score"],errors="coerce")
        -pd.to_numeric(chk["bestmatch_d5_balanced_score"],errors="coerce")
    ).abs().max()
    rank_equal=(
        pd.to_numeric(chk["bestmatch_v0b_rank"],errors="coerce")
        .eq(pd.to_numeric(chk["rank_d5_balanced"],errors="coerce"))
        .all()
    )
    if float(score_delta)>1e-12 or not rank_equal:
        raise RuntimeError("Canonical v0b product is not identical to selected D5 balanced policy")

    return {
        "candidate_fields":len(prod),
        "class_counts":classes,
        "routed_fields":routed,
        "straightline_fallback_fields":fallback,
        "route_coverage_pct":100.0*routed/len(prod),
        "historical_positive_fields":hist,
        "top800_area_ha":area,
        "top800_historical_positive_hits":hits800,
        "balanced_topn_historical_hits":got,
        "score_alias_max_abs_diff":float(score_delta),
    }


def main()->int:
    policy=json.loads(POLICY.read_text(encoding="utf-8-sig"))
    missing=[rel for rel in FILES if not (ROOT/rel).exists()]
    if missing:
        raise FileNotFoundError("Cannot freeze BestMatch v0b; missing:\n  "+"\n  ".join(missing))

    # Explicitly require and fingerprint the already-frozen external ÅkerFrö C10 input.
    c10=discover_c10(None)
    if not c10.exists():
        raise FileNotFoundError(c10)

    anchors=validate(policy)
    entries={rel:fingerprint(ROOT/rel) for rel in FILES}
    c10_fp=fingerprint(c10)

    FREEZE_DIR.mkdir(parents=True,exist_ok=True)
    manifest={
        "schema_version":"akerfro-akeraccess-bestmatch-v0b-freeze-manifest-v1",
        "freeze_name":policy["freeze_name"],
        "status":"FORMALLY_FROZEN_LOCAL_ARTIFACT_SET",
        "git":{
            "repository":"PiggeGnidde/akersync",
            "branch":"feature/akeraccess-mvp-v0a",
            "head_at_freeze":git_head()
        },
        "selected_product":{
            "policy":"balanced",
            "hard_class_order":["A_STRONG_CANDIDATE","B_PHYSICAL_CANDIDATE"],
            "weights":policy["policy_weights"],
            "score":"0.50 ÄrtMatch + 0.25 road-based AreaLogistik + 0.25 ÅkerAccess v0a",
            "rank":"A before B; score descending within class; field_id tie-break",
        },
        "lineage":{
            "akerfro_c10":c10_fp,
            "akeraccess_v0a_manifest":fingerprint(ROOT/"work/akeraccess_v0a/freeze_v0a/akeraccess_v0a_freeze_manifest.json"),
            "bjuv_route_distance":"D4 approximate OSM road-network distance",
            "bjuv_missing_route_policy":"explicit frozen-C10 straight-line fallback",
        },
        "anchors":anchors,
        "guardrails":[
            "BestMatch v0b is a screening/ranking product, not an agronomic guarantee.",
            "Road/logistics cannot promote C/D fields into the A/B candidate universe.",
            "A/B class order is hard before the weighted score.",
            "D4 road distance is approximate OSM network distance, not certified truck navigation.",
            "D4 respects OSM one-way tags but not turn restrictions, dynamic closures, vehicle weight/height limits or traffic.",
            "24.38% of A/B candidates currently use explicit straight-line Bjuv fallback because D4 route is missing.",
            "Historical clean CONSERVART enrichment is diagnostic only and is not used to fit the selected 50/25/25 weights.",
            "NVDB Slitlager is excluded from the selected product.",
            "Estimated field entrance is machine-estimated from mapped geometry and not field-verified."
        ],
        "outside_freeze":[
            "ÅkerKombinatorik portfolio/year grouping",
            "customer-specific hard truck clearance gates",
            "future live traffic/road closure routing",
            "verified legal right-of-way/ownership",
            "verified physical entrance width/turning radius",
            "D5 match-first and logistics-forward policies as product defaults"
        ],
        "files":entries
    }
    MANIFEST.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    print("="*114)
    print("ÅkerFrö × ÅkerAccess BestMatch v0b FORMAL FREEZE")
    print("="*114)
    print(f"Freeze: {manifest['freeze_name']}")
    print(f"Git HEAD: {manifest['git']['head_at_freeze']}")
    print(f"Files frozen: {len(entries)} + external C10 fingerprint")
    print(f"Candidates: {anchors['candidate_fields']:,}")
    print(f"A/B: {anchors['class_counts']}")
    print(f"Bjuv route coverage: {anchors['routed_fields']:,}/{anchors['candidate_fields']:,} = {anchors['route_coverage_pct']:.2f}%")
    print(f"Straight-line fallback: {anchors['straightline_fallback_fields']:,}")
    print(f"Top800: {anchors['top800_area_ha']:.1f} ha · historical positives {anchors['top800_historical_positive_hits']}")
    print(f"Manifest: {MANIFEST}")
    print("="*114)
    print("BestMatch v0b FORMAL FREEZE: PASS")
    print("="*114)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
