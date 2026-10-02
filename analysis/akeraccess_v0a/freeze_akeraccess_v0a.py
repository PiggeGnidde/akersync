#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Formal local freeze for ÅkerAccess v0a."""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
POLICY=ROOT/"config"/"akeraccess_v0a_freeze.json"
FREEZE_DIR=ROOT/"work"/"akeraccess_v0a"/"freeze_v0a"
MANIFEST=FREEZE_DIR/"akeraccess_v0a_freeze_manifest.json"

FILES=[
    # Freeze contract / core implementation.
    "config/akeraccess_v0a_freeze.json",
    "config/akeraccess_v0a.json",
    "config/akeraccess_skane_d0.json",
    "config/akeraccess_skane_d1.json",
    "analysis/akeraccess_v0a/core.py",
    "analysis/akeraccess_v0a/entry_discovery_v0a.py",
    "analysis/akeraccess_v0a/network_core.py",
    "analysis/akeraccess_v0a/path_profile_core.py",
    "analysis/akeraccess_v0a/nvdb_anchor_match_c2.py",
    "analysis/akeraccess_v0a/skane_road_features_d0.py",
    "analysis/akeraccess_v0a/skane_pea_replication_d1.py",
    "analysis/akeraccess_v0a/build_akeraccess_product_v0a.py",
    # Frozen D0 Skåne feature layer.
    "work/akeraccess_v0a/skane_d0/skane_akeraccess_road_features_d0.parquet",
    "work/akeraccess_v0a/skane_d0/skane_akeraccess_d0_municipality_summary.csv",
    "work/akeraccess_v0a/skane_d0/skane_akeraccess_d0_report.json",
    # Independent D1 replication / validation evidence.
    "work/akeraccess_v0a/skane_d1/skane_d1_positive_counts.csv",
    "work/akeraccess_v0a/skane_d1/skane_d1_positive_counts_by_municipality.csv",
    "work/akeraccess_v0a/skane_d1/skane_d1_neartwin_summary.csv",
    "work/akeraccess_v0a/skane_d1/skane_d1_matches.parquet",
    "work/akeraccess_v0a/skane_d1/skane_d1_report.json",
    # Frozen generic ÅkerAccess product table.
    "data/derived/akeraccess_v0a/akeraccess_v0a_fields.parquet",
    "data/derived/akeraccess_v0a/akeraccess_v0a_summary.json",
]

EXPECTED={
    "population":67073,
    "connected":46633,
    "no_drivable_50m":11216,
    "public_50":27686,
    "public_100":31058,
    "public_250":40527,
}


def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def git_head()->str:
    try:
        return subprocess.check_output(
            ["git","rev-parse","HEAD"],cwd=ROOT,text=True
        ).strip()
    except Exception:
        return "UNKNOWN"


def in_range(x:float,lo:float,hi:float)->bool:
    return math.isfinite(x) and lo<=x<=hi


def validate()->dict:
    policy=json.loads(POLICY.read_text(encoding="utf-8"))
    d0p=ROOT/"work/akeraccess_v0a/skane_d0/skane_akeraccess_road_features_d0.parquet"
    d1p=ROOT/"work/akeraccess_v0a/skane_d1/skane_d1_neartwin_summary.csv"
    prodp=ROOT/"data/derived/akeraccess_v0a/akeraccess_v0a_fields.parquet"

    d0=pd.read_parquet(d0p)
    if len(d0)!=EXPECTED["population"]:
        raise RuntimeError(f"D0 population anchor failed: {len(d0):,}")
    if int(d0["network_access_status"].eq("CONNECTED_TO_ROAD_NETWORK").sum())!=EXPECTED["connected"]:
        raise RuntimeError("D0 connected anchor failed")
    if int(d0["no_drivable_50m"].fillna(False).astype(bool).sum())!=EXPECTED["no_drivable_50m"]:
        raise RuntimeError("D0 no_drivable_50m anchor failed")
    pub=pd.to_numeric(d0["nearest_statlig_kommunal_nvdb_m"],errors="coerce")
    for t,key in [(50,"public_50"),(100,"public_100"),(250,"public_250")]:
        got=int(pub.le(t).sum())
        if got!=EXPECTED[key]:
            raise RuntimeError(f"D0 public-roadkeeper <= {t} m anchor failed: {got:,}")

    d1=pd.read_csv(d1p)
    label="skane_excluding_sjobo__recent_2023_2025__strict_never_pea"
    q=d1[d1["match_label"].eq(label)&d1["metric"].eq("no_drivable_50m")]
    if len(q)!=1:
        raise RuntimeError("D1 primary replication row missing/duplicated")
    r=q.iloc[0]
    a=policy["known_validation_anchor"]
    pos=float(r["positive_mean"]); ctrl=float(r["matched_control_mean"])
    diff=float(r["paired_difference"]); hi=float(r["bootstrap95_hi"])
    if not in_range(pos,*map(float,a["expected_positive_mean_range"])):
        raise RuntimeError(f"D1 positive anchor out of range: {pos}")
    if not in_range(ctrl,*map(float,a["expected_control_mean_range"])):
        raise RuntimeError(f"D1 control anchor out of range: {ctrl}")
    if not in_range(diff,*map(float,a["expected_difference_range"])):
        raise RuntimeError(f"D1 difference anchor out of range: {diff}")
    if bool(a["require_bootstrap95_hi_below_zero"]) and not hi<0:
        raise RuntimeError(f"D1 primary bootstrap CI no longer excludes zero: hi={hi}")

    prod=pd.read_parquet(prodp)
    if len(prod)!=EXPECTED["population"] or prod["field_id"].astype(str).duplicated().any():
        raise RuntimeError("Frozen product population/uniqueness anchor failed")
    score=pd.to_numeric(prod["akeraccess_score_v0a"],errors="coerce")
    if int(score.notna().sum())<65000:
        raise RuntimeError("Unexpectedly low ÅkerAccess score coverage")

    return {
        "population_fields":int(len(d0)),
        "connected_mapped_entry_to_ordinary_road":EXPECTED["connected"],
        "no_mapped_drivable_way_within_50m":EXPECTED["no_drivable_50m"],
        "nearest_statlig_kommunal_within_50m":EXPECTED["public_50"],
        "nearest_statlig_kommunal_within_100m":EXPECTED["public_100"],
        "nearest_statlig_kommunal_within_250m":EXPECTED["public_250"],
        "scored_fields":int(score.notna().sum()),
        "score_quantiles":{
            "p10":float(score.quantile(.10)),
            "p50":float(score.quantile(.50)),
            "p90":float(score.quantile(.90)),
        },
        "d1_primary":{
            "match_label":label,
            "positive_mean":pos,
            "matched_control_mean":ctrl,
            "paired_difference":diff,
            "bootstrap95_lo":float(r["bootstrap95_lo"]),
            "bootstrap95_hi":hi,
            "valid_positive_sets":int(r["valid_positive_sets"]),
        }
    }


def main()->int:
    missing=[rel for rel in FILES if not (ROOT/rel).exists()]
    if missing:
        raise FileNotFoundError("Cannot freeze; missing required files:\n  "+"\n  ".join(missing))

    anchors=validate()
    entries={}
    for rel in FILES:
        p=ROOT/rel
        entries[rel]={"bytes":p.stat().st_size,"sha256":sha256(p)}

    FREEZE_DIR.mkdir(parents=True,exist_ok=True)
    manifest={
        "schema_version":"akeraccess-v0a-freeze-manifest-v1",
        "freeze_name":"akeraccess-v0a",
        "status":"FORMALLY_FROZEN_LOCAL_ARTIFACT_SET",
        "scope":"generic Skåne ÅkerAccess feature layer + v0a screening score + D1 independent validation",
        "git":{
            "repository":"PiggeGnidde/akersync",
            "branch":"feature/akeraccess-mvp-v0a",
            "head_at_freeze":git_head(),
        },
        "lineage":{
            "current_field_geometry":"Jordbruksverket 2025 current fields",
            "eligibility":"field area >=1 ha; explicit pasture/slåtteräng excluded using ÅkerMinne 2025 crop name",
            "road_geometry":"OpenStreetMap cached road/gate extracts",
            "road_attributes":"Trafikverket NVDB v1.2",
            "historical_validation":"ÅkerMinne v1 clean CONSERVART history",
        },
        "anchors":anchors,
        "product_contract":{
            "score":"50% inverse percentile nearest mapped drivable OSM way + 50% inverse percentile nearest statlig/kommunal NVDB roadkeeper geometry",
            "ranking":"descending ÅkerAccess score; field_id tie-break",
            "entry":"selected field entry is machine-estimated from mapped geometry; not field-verified",
            "missing_evidence":"CHECK/UNKNOWN, never physical FAIL",
            "public_roadkeeper_label":"Till statligt/kommunalt väghållen väg",
            "nearest_drivable_label":"Till närmaste körbara väg",
            "slitlager":"excluded from v0a product score after visual QA false negative",
        },
        "validation_contract":{
            "primary":"Skåne excluding Sjöbo; historical clean CONSERVART 2023-2025; strict-never-pea spatial/area near-twins",
            "endpoint":"no mapped drivable OSM way within 50 m",
            "interpretation":"historical selection evidence for screening usefulness; not causal yield/access proof",
        },
        "outside_freeze":[
            "ÅkerFrö/BestMatch weights and Bjuv-specific road distance",
            "Apetit-specific truck/harvester clearance policy",
            "NVDB Slitlager as product truth",
            "hard 4.5 m width gate",
            "functional-road-class 4-or-7 grouping",
            "legal access/right-of-way or ownership",
            "certified truck navigation",
            "exact verified field entrance",
        ],
        "guardrails":[
            "ÅkerAccess v0a is a screening/ranking product, not a pass/fail classifier.",
            "OSM absence or weak evidence is unknown/check, not proof of no physical access.",
            "Statlig/kommunal is roadkeeper responsibility and does not imply asphalt or legal allmän väg.",
            "NVDB width is road width, not entrance width.",
            "Missing NVDB bearing/height/width attributes remain unknown.",
            "Estimated entrance is visual/operational guidance only and can be metres off.",
            "D1 historical non-use is positive-unlabeled and not a true negative.",
        ],
        "files":entries,
    }
    MANIFEST.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    print("="*108)
    print("ÅkerAccess v0a FORMAL FREEZE")
    print("="*108)
    print(f"Freeze: {manifest['freeze_name']}")
    print(f"Git HEAD: {manifest['git']['head_at_freeze']}")
    print(f"Files frozen: {len(entries)}")
    print(f"Population: {anchors['population_fields']:,}")
    print(f"Scored: {anchors['scored_fields']:,}")
    p=anchors["d1_primary"]
    print(
        "D1 primary no_drivable_50m: "
        f"pea={100*p['positive_mean']:.2f}% ctrl={100*p['matched_control_mean']:.2f}% "
        f"diff={100*p['paired_difference']:+.2f} pp "
        f"boot95=[{100*p['bootstrap95_lo']:+.2f},{100*p['bootstrap95_hi']:+.2f}]"
    )
    print(f"Manifest: {MANIFEST}")
    print("="*108)
    print("ÅkerAccess v0a FORMAL FREEZE: PASS")
    print("="*108)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
