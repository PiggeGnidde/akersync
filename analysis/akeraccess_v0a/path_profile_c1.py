#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerAccess STOPPUNKT C1 - OSM last-mile path profile, no score."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer

ROOT=Path(__file__).resolve().parents[2]
SRC=ROOT/"src"
for p in (ROOT,SRC):
    if str(p) not in sys.path: sys.path.insert(0,str(p))

from analysis.akeraccess_v0a.core import DRIVABLE_HIGHWAYS
from analysis.akeraccess_v0a.network_core import ANCHOR_HIGHWAYS
from analysis.akeraccess_v0a.path_profile_core import (
    build_tagged_graph,dijkstra_to_anchors,summarize_candidate_path
)

DEFAULT_WORK=ROOT/"work"/"akeraccess_v0a"/"sjobo"
DEFAULT_OSM=ROOT/"data"/"raw"/"akeraccess_osm"/"sjobo_roads_gates.json"


def load_json(p:Path):
    return json.loads(p.read_text(encoding="utf-8-sig"))


def quantiles(s):
    x=pd.to_numeric(s,errors="coerce").dropna()
    if not len(x): return {}
    return {f"p{q}":float(x.quantile(q/100)) for q in [10,25,50,75,90,95]}


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--work",default=str(DEFAULT_WORK))
    ap.add_argument("--osm",default=str(DEFAULT_OSM))
    args=ap.parse_args()
    work=Path(args.work)

    field_net=work/"network_c0"/"sjobo_field_network_c0.csv"
    cand_geo=work/"sjobo_entry_candidates.geojson"
    if not field_net.exists() or not cand_geo.exists():
        raise FileNotFoundError("Run STOPPUNKT C0 first")

    fields=pd.read_csv(field_net,low_memory=False)
    eligible_ids=set(fields["field_id"].astype(str))
    candidates=gpd.read_file(cand_geo).to_crs(3006)
    candidates=candidates[candidates["field_id"].astype(str).isin(eligible_ids)].copy()

    payload=load_json(Path(args.osm))
    transformer=Transformer.from_crs(4326,3006,always_xy=True)
    graph,xy,ways,node_tags,anchors=build_tagged_graph(
        payload,transformer,set(DRIVABLE_HIGHWAYS),set(ANCHOR_HIGHWAYS)
    )
    dist,parent=dijkstra_to_anchors(graph,anchors)

    rows=[]
    for r in candidates.itertuples(index=False):
        if r.geometry is None or r.geometry.is_empty:
            continue
        prof=summarize_candidate_path(
            (float(r.geometry.x),float(r.geometry.y)),
            int(r.osm_way_id),ways,xy,node_tags,dist,parent
        )
        rows.append({
            "field_id":str(r.field_id),
            "candidate_rank":int(r.candidate_rank),
            "candidate_kind":str(r.candidate_kind),
            "geom_evidence":float(r.confidence),
            "osm_way_id":int(r.osm_way_id),
            "candidate_highway":str(r.highway),
            **prof,
        })
    cand=pd.DataFrame(rows)
    out=work/"path_c1"
    out.mkdir(parents=True,exist_ok=True)
    cand_path=out/"sjobo_candidate_path_profile_c1.csv"
    cand.to_csv(cand_path,index=False,encoding="utf-8-sig")

    connected=cand[cand["path_status"].eq("CONNECTED")].copy()
    if connected.empty:
        raise RuntimeError("No connected candidate paths")

    # Discovery choice only: shortest mapped last-mile among candidates, then old candidate rank.
    best=(connected.sort_values(
        ["field_id","has_bad_access","explicit_height_lt_4_5","explicit_width_lt_4_5",
         "last_mile_to_anchor_m","candidate_rank"],
        kind="mergesort"
    ).groupby("field_id",sort=False).head(1).copy())
    best=best.rename(columns={
        c:"path_"+c for c in best.columns if c!="field_id"
    })
    field=fields.merge(best,on="field_id",how="left",validate="one_to_one")
    field_path=out/"sjobo_field_path_profile_c1.csv"
    field.to_csv(field_path,index=False,encoding="utf-8-sig")

    selected=best.copy()
    lm=pd.to_numeric(selected["path_last_mile_to_anchor_m"],errors="coerce")
    bands=pd.cut(lm,[-0.001,50,100,250,500,1000,np.inf],
                 labels=["0-50","50-100","100-250","250-500","500-1000","1000+"])
    band_counts=bands.value_counts(sort=False,dropna=False).to_dict()

    candidate_highways=selected["path_candidate_highway"].value_counts(dropna=False).to_dict()
    report={
        "schema_version":"akeraccess-path-profile-c1-v0a",
        "eligible_fields":int(len(fields)),
        "fields_with_connected_candidate":int(selected["field_id"].nunique()),
        "candidate_rows_profiled":int(len(cand)),
        "selection_note":"Discovery-only path candidate: prefer no explicit access/height/width violation, then shortest mapped last-mile, then old candidate rank.",
        "last_mile_m_quantiles":quantiles(lm),
        "last_mile_band_counts":{str(k):int(v) for k,v in band_counts.items()},
        "selected_candidate_highway_counts":{str(k):int(v) for k,v in candidate_highways.items()},
        "selected_with_known_width":int(selected["path_min_known_width_m"].notna().sum()),
        "selected_with_known_height":int(selected["path_min_known_maxheight_m"].notna().sum()),
        "selected_explicit_width_lt_4_5":int(selected["path_explicit_width_lt_4_5"].fillna(False).sum()),
        "selected_explicit_height_lt_4_5":int(selected["path_explicit_height_lt_4_5"].fillna(False).sum()),
        "selected_bad_access":int(selected["path_has_bad_access"].fillna(False).sum()),
        "selected_soft_access":int(selected["path_has_soft_access"].fillna(False).sum()),
        "selected_with_barrier":int(pd.to_numeric(selected["path_n_barriers"],errors="coerce").fillna(0).gt(0).sum()),
        "important":"C1 is descriptive. No ÅkerAccess score or Apetit PASS/FAIL is frozen."
    }
    rp=out/"sjobo_path_profile_c1_report.json"
    rp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")

    print("="*100)
    print("ÅkerAccess STOPPUNKT C1 - OSM LAST-MILE PATH PROFILE")
    print("="*100)
    print(f"Eligible fields: {len(fields):,}")
    print(f"Fields with connected candidate: {report['fields_with_connected_candidate']:,}")
    print(f"Candidate paths profiled: {len(cand):,}")
    print("\nLAST-MILE TO ORDINARY ROAD")
    for k,v in report["last_mile_m_quantiles"].items(): print(f"  {k}: {v:.1f} m")
    print("Bands:")
    for k,v in report["last_mile_band_counts"].items(): print(f"  {k:10s} {v:6,d}")
    print("\nEXPLICIT OSM CONSTRAINT COVERAGE / FLAGS")
    print(f"  known width:          {report['selected_with_known_width']:,}")
    print(f"  known maxheight:      {report['selected_with_known_height']:,}")
    print(f"  width <4.5 m:         {report['selected_explicit_width_lt_4_5']:,}")
    print(f"  height <4.5 m:        {report['selected_explicit_height_lt_4_5']:,}")
    print(f"  access=no/private:    {report['selected_bad_access']:,}")
    print(f"  soft access tag:      {report['selected_soft_access']:,}")
    print(f"  barrier on path:      {report['selected_with_barrier']:,}")
    print(f"\nReport: {rp}")
    print("="*100)
    print("STOPPUNKT C1: PASS")
    print("="*100)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
