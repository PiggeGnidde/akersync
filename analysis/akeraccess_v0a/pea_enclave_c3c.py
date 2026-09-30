#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerAccess STOPPUNKT C3c — test geometric/mapped enclave fields.

Question:
  Are historical conservärt fields underrepresented among fields with no direct
  mapped drivable-road frontage, especially fields geometrically interior to
  their Jordbruksverket block?

C3c reuses the already frozen C3b near-twin matches. It does not rematch.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
for p in (ROOT,ROOT/"src"):
    if str(p) not in sys.path:
        sys.path.insert(0,str(p))

from analysis.akeraccess_v0a.core import text_id
from analysis.akeraccess_v0a.entry_discovery_v0a import (
    discover_field_inputs, load_fields, load_json, osm_geodataframes
)

DEFAULT_WORK=ROOT/"work"/"akeraccess_v0a"/"sjobo"
DEFAULT_OSM=ROOT/"data"/"raw"/"akeraccess_osm"/"sjobo_roads_gates.json"


def norm_id(x:Any)->str:
    if x is None:
        return ""
    s=str(x).strip()
    if s.endswith(".0"):
        try:
            return str(int(float(s)))
        except Exception:
            pass
    return s


def bootstrap_ci(x:np.ndarray,reps:int=10000,seed:int=20260930)->tuple[float,float,float]:
    a=np.asarray(x,dtype=float)
    a=a[np.isfinite(a)]
    if not len(a):
        return math.nan,math.nan,math.nan
    mean=float(a.mean())
    if len(a)==1:
        return mean,math.nan,math.nan
    rng=np.random.default_rng(seed)
    ix=rng.integers(0,len(a),size=(reps,len(a)))
    b=a[ix].mean(axis=1)
    return mean,float(np.quantile(b,.025)),float(np.quantile(b,.975))


def field_block_metrics(fields:gpd.GeoDataFrame, blocks_path:Path)->pd.DataFrame:
    block_ids=set(fields["blockid"].map(text_id))
    blocks=gpd.read_file(blocks_path).to_crs(3006)
    if "blockid" not in blocks.columns:
        raise RuntimeError("Block geometry lacks blockid")
    blocks["blockid"]=blocks["blockid"].map(text_id)
    blocks=blocks[blocks["blockid"].isin(block_ids)][["blockid","geometry"]].copy()
    if blocks["blockid"].duplicated().any():
        blocks=blocks.dissolve(by="blockid",as_index=False)

    bg={str(r.blockid):r.geometry for r in blocks.itertuples(index=False)}
    rows=[]
    for r in fields.itertuples(index=False):
        f=r.geometry
        b=bg.get(str(r.blockid))
        if b is None or b.is_empty or f is None or f.is_empty:
            rows.append({"field_id":r.field_id,"outer_block_boundary_share":math.nan})
            continue
        per=float(f.boundary.length)
        if per<=0:
            share=math.nan
        else:
            # 2 m tolerance handles small digitisation mismatch between skifte and block.
            outer=float(f.boundary.intersection(b.boundary.buffer(2.0)).length)
            share=max(0.0,min(1.0,outer/per))
        rows.append({"field_id":r.field_id,"outer_block_boundary_share":share})
    return pd.DataFrame(rows)


def nearest_road_metrics(fields:gpd.GeoDataFrame, roads:gpd.GeoDataFrame)->pd.DataFrame:
    if roads.empty:
        raise RuntimeError("No OSM drivable roads")
    f=fields[["field_id","geometry"]].copy()
    r=roads[["osm_way_id","highway","geometry"]].copy()
    j=gpd.sjoin_nearest(f,r,how="left",distance_col="nearest_drivable_m")
    # Equidistant ties can duplicate rows; keep deterministic nearest/min.
    j["nearest_drivable_m"]=pd.to_numeric(j["nearest_drivable_m"],errors="coerce")
    j=j.sort_values(["field_id","nearest_drivable_m","osm_way_id"],kind="mergesort")
    j=j.drop_duplicates("field_id",keep="first")
    return pd.DataFrame(j[["field_id","nearest_drivable_m","osm_way_id","highway"]]).rename(
        columns={"osm_way_id":"nearest_osm_way_id","highway":"nearest_highway"}
    )


def build_enclave_metrics(work:Path, osm_path:Path)->tuple[pd.DataFrame,dict[str,Any]]:
    c3=work/"pea_validation_c3"/"sjobo_akeraccess_pea_c3_fields.csv"
    if not c3.exists():
        raise FileNotFoundError(c3)
    base=pd.read_csv(c3,low_memory=False)
    base["field_id"]=base["field_id"].map(norm_id)
    eligible=set(base["field_id"])

    blocks_path,skiften_path,local_cfg=discover_field_inputs()
    fields=load_fields("Sjöbo",blocks_path,skiften_path)
    fields["field_id"]=fields["field_id"].map(norm_id)
    fields=fields[fields["field_id"].isin(eligible)].copy()
    if len(fields)!=len(base):
        raise RuntimeError(f"Geometry population mismatch: {len(fields):,} vs C3 {len(base):,}")

    payload=load_json(osm_path)
    roads,_gates=osm_geodataframes(payload)

    rm=nearest_road_metrics(fields,roads)
    bm=field_block_metrics(fields,blocks_path)
    m=base[["field_id","entry_status"]].merge(rm,on="field_id",how="left",validate="one_to_one")
    m=m.merge(bm,on="field_id",how="left",validate="one_to_one")

    d=pd.to_numeric(m["nearest_drivable_m"],errors="coerce")
    share=pd.to_numeric(m["outer_block_boundary_share"],errors="coerce")

    # Independent, transparent geometric definitions.
    m["no_drivable_within_5m"]=d.gt(5.0)
    m["no_drivable_within_15m"]=d.gt(15.0)
    m["no_drivable_within_50m"]=d.gt(50.0)

    # "Interior" means essentially no field perimeter lies on the agricultural
    # block outer boundary. This captures skiften surrounded by the same block.
    m["interior_skifte"]=share.lt(0.01)
    m["mapped_enclave_15m"]=m["interior_skifte"] & m["no_drivable_within_15m"]
    m["mapped_enclave_50m"]=m["interior_skifte"] & m["no_drivable_within_50m"]
    m["no_osm_entry_evidence"]=m["entry_status"].eq("NO_OSM_ENTRY_EVIDENCE")

    diag={
        "eligible_fields":int(len(m)),
        "osm_drivable_ways":int(len(roads)),
        "median_nearest_drivable_m":float(d.median()),
        "interior_skifte_n":int(m["interior_skifte"].sum()),
        "no_drivable_within_15m_n":int(m["no_drivable_within_15m"].sum()),
        "no_drivable_within_50m_n":int(m["no_drivable_within_50m"].sum()),
        "mapped_enclave_15m_n":int(m["mapped_enclave_15m"].sum()),
        "mapped_enclave_50m_n":int(m["mapped_enclave_50m"].sum()),
        "geometry_config":str(local_cfg),
        "osm_source":str(osm_path),
    }
    return m,diag


METRICS=[
    "no_osm_entry_evidence",
    "no_drivable_within_5m",
    "no_drivable_within_15m",
    "no_drivable_within_50m",
    "interior_skifte",
    "mapped_enclave_15m",
    "mapped_enclave_50m",
]


def compare_from_matches(metrics:pd.DataFrame,matches:pd.DataFrame)->pd.DataFrame:
    mm=metrics.set_index("field_id")
    rows=[]
    for label,g in matches.groupby("match_label",sort=False):
        positives=sorted(g["positive_field_id"].astype(str).unique())
        for metric in METRICS:
            diffs=[]; pvals=[]; cvals=[]
            for pid in positives:
                if pid not in mm.index:
                    continue
                pg=g[g["positive_field_id"].astype(str).eq(pid)]
                cids=pg["control_field_id"].astype(str).tolist()
                cids=[x for x in cids if x in mm.index]
                if not cids:
                    continue
                pv=float(bool(mm.at[pid,metric]))
                cv=float(mm.loc[cids,metric].astype(bool).mean())
                pvals.append(pv); cvals.append(cv); diffs.append(pv-cv)
            mean,lo,hi=bootstrap_ci(np.asarray(diffs),seed=20260930+len(rows))
            rows.append({
                "match_label":label,
                "metric":metric,
                "positive_sets_n":len(diffs),
                "positive_rate":float(np.mean(pvals)) if pvals else math.nan,
                "matched_control_rate":float(np.mean(cvals)) if cvals else math.nan,
                "paired_diff":mean,
                "bootstrap95_lo":lo,
                "bootstrap95_hi":hi,
            })
    return pd.DataFrame(rows)


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--work",default=str(DEFAULT_WORK))
    ap.add_argument("--osm",default=str(DEFAULT_OSM))
    args=ap.parse_args()
    work=Path(args.work)

    matches_path=work/"pea_validation_c3b"/"sjobo_akeraccess_pea_c3b_matches.csv"
    if not matches_path.exists():
        raise FileNotFoundError(f"Run C3b first: {matches_path}")
    matches=pd.read_csv(matches_path,low_memory=False)
    matches["positive_field_id"]=matches["positive_field_id"].map(norm_id)
    matches["control_field_id"]=matches["control_field_id"].map(norm_id)

    metrics,diag=build_enclave_metrics(work,Path(args.osm))
    result=compare_from_matches(metrics,matches)

    out=work/"pea_validation_c3c_enclave"
    out.mkdir(parents=True,exist_ok=True)
    mp=out/"sjobo_akeraccess_c3c_enclave_fields.csv"
    rp=out/"sjobo_akeraccess_c3c_enclave_neartwin.csv"
    jp=out/"sjobo_akeraccess_c3c_enclave_report.json"
    metrics.to_csv(mp,index=False,encoding="utf-8-sig")
    result.to_csv(rp,index=False,encoding="utf-8-sig")
    report={
        "schema_version":"akeraccess-enclave-c3c-v0a",
        "definitions":{
            "interior_skifte":"<1% of current field perimeter lies within 2 m of its Jordbruksverket block outer boundary",
            "mapped_enclave_15m":"interior_skifte AND nearest mapped OSM drivable way >15 m from field",
            "mapped_enclave_50m":"interior_skifte AND nearest mapped OSM drivable way >50 m from field",
            "warning":"Mapped enclave is evidence from current geometry/OSM, not proof that no private/farm access exists."
        },
        "diagnostics":diag,
        "outputs":{"fields":str(mp),"near_twin":str(rp)},
        "guardrail":"C3c is diagnostic only; no exclusion rule is frozen."
    }
    jp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")

    print("="*112)
    print("ÅkerAccess STOPPUNKT C3c - ENCLAVE / NO-DIRECT-ROAD TEST, SJÖBO")
    print("="*112)
    print(f"Eligible fields: {diag['eligible_fields']:,}")
    print(f"Interior skiften: {diag['interior_skifte_n']:,}")
    print(f"No drivable OSM within 15 m: {diag['no_drivable_within_15m_n']:,}")
    print(f"No drivable OSM within 50 m: {diag['no_drivable_within_50m_n']:,}")
    print(f"Mapped enclave 15 m: {diag['mapped_enclave_15m_n']:,}")
    print(f"Mapped enclave 50 m: {diag['mapped_enclave_50m_n']:,}")
    print()
    for label,g in result.groupby("match_label",sort=False):
        print("-"*112)
        print(label)
        for r in g.itertuples(index=False):
            print(
                f"  {r.metric:26s} pea={100*r.positive_rate:6.1f}% "
                f"ctrl={100*r.matched_control_rate:6.1f}% "
                f"diff={100*r.paired_diff:+6.1f}pp "
                f"boot95=[{100*r.bootstrap95_lo:+6.1f},{100*r.bootstrap95_hi:+6.1f}]"
            )
    print(f"\nReport: {jp}")
    print("="*112)
    print("STOPPUNKT C3c: PASS")
    print("="*112)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
