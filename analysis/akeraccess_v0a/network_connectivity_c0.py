#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerAccess STOPPUNKT C0 - network connectivity screen for eligible Sjöbo fields."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer

ROOT=Path(__file__).resolve().parents[2]
SRC=ROOT/"src"
for p in (ROOT,SRC):
    if str(p) not in sys.path: sys.path.insert(0,str(p))

from analysis.akeraccess_v0a.core import DRIVABLE_HIGHWAYS
from analysis.akeraccess_v0a.network_core import (
    ANCHOR_HIGHWAYS, build_node_graph, candidate_connectivity, multisource_dijkstra
)
from analysis.akeraccess_v0a.prepare_review_b2 import find_akerminne_2025, is_pasture_name
from analysis.akeraccess_v0a.entry_discovery_v0a import discover_field_inputs, load_fields

DEFAULT_WORK=ROOT/"work"/"akeraccess_v0a"/"sjobo"
DEFAULT_OSM=ROOT/"data"/"raw"/"akeraccess_osm"/"sjobo_roads_gates.json"
DEFAULT_B2=ROOT/"config"/"akeraccess_b2.json"


def load_json(p:Path)->dict[str,Any]:
    return json.loads(p.read_text(encoding="utf-8-sig"))


def eligible_fields(work:Path,cfg:dict[str,Any])->pd.DataFrame:
    summary=pd.read_csv(work/"sjobo_field_entry_summary.csv",low_memory=False)
    field_ids=set(summary["field_id"].astype(str))
    crop,_=find_akerminne_2025(Path(r"C:\AkerSync-Minne"),"Sjöbo",field_ids)
    crop=crop[["field_id","dominant_crop_name"]].rename(columns={"dominant_crop_name":"crop2025_name"})
    d=summary.merge(crop,on="field_id",how="left",validate="one_to_one")
    d["area_ha"]=pd.to_numeric(d["area_ha"],errors="coerce")
    d["is_pasture_2025"]=d["crop2025_name"].map(
        lambda x:is_pasture_name(x,list(cfg["pasture_name_tokens"]))
    )
    return d[d["area_ha"].ge(float(cfg["minimum_area_ha"])) & ~d["is_pasture_2025"]].copy()


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--work",default=str(DEFAULT_WORK))
    ap.add_argument("--osm",default=str(DEFAULT_OSM))
    args=ap.parse_args()
    work=Path(args.work)
    cfg=load_json(DEFAULT_B2)
    eligible=eligible_fields(work,cfg)
    if len(eligible)!=4324:
        print(f"WARNING: expected current B2 eligible anchor 4,324, got {len(eligible):,}")

    cand_path=work/"sjobo_entry_candidates.geojson"
    if not cand_path.exists(): raise FileNotFoundError(cand_path)
    candidates=gpd.read_file(cand_path).to_crs(3006)
    candidates=candidates[candidates["field_id"].astype(str).isin(set(eligible["field_id"].astype(str)))].copy()

    osm=load_json(Path(args.osm))
    transformer=Transformer.from_crs(4326,3006,always_xy=True)
    graph,nodes_xy,way_nodes,way_highway,anchors=build_node_graph(
        osm,transformer,set(DRIVABLE_HIGHWAYS),set(ANCHOR_HIGHWAYS)
    )
    dist=multisource_dijkstra(graph,anchors)

    rows=[]
    for r in candidates.itertuples(index=False):
        wid=int(r.osm_way_id)
        xy=(float(r.geometry.x),float(r.geometry.y)) if r.geometry is not None else None
        c=candidate_connectivity(wid,xy,way_nodes,nodes_xy,dist,way_highway)
        rows.append({
            "field_id":str(r.field_id),
            "candidate_rank":int(r.candidate_rank),
            "candidate_kind":str(r.candidate_kind),
            "geom_evidence":float(r.confidence),
            "osm_way_id":wid,
            "highway":str(r.highway),
            **c,
        })
    cand_net=pd.DataFrame(rows)
    cand_out=work/"network_c0"
    cand_out.mkdir(parents=True,exist_ok=True)
    cand_net.to_csv(cand_out/"sjobo_candidate_network_c0.csv",index=False,encoding="utf-8-sig")

    field_rows=[]
    grouped={k:g for k,g in cand_net.groupby("field_id")} if len(cand_net) else {}
    for r in eligible.itertuples(index=False):
        fid=str(r.field_id)
        g=grouped.get(fid)
        if g is None or len(g)==0:
            field_rows.append({
                "field_id":fid,
                "area_ha":float(r.area_ha),
                "entry_status":r.entry_status,
                "crop2025_name":getattr(r,"crop2025_name",""),
                "n_candidates":0,
                "n_network_connected_candidates":0,
                "best_connected_candidate_rank":None,
                "best_network_total_screen_m":None,
                "network_access_status":"NO_ENTRY_CANDIDATE",
                "akerfro_proactive_gate":"HOLD_MANUAL_CHECK",
            })
            continue
        connected=g[g["network_connected"].fillna(False).astype(bool)].copy()
        if len(connected):
            connected=connected.sort_values(
                ["candidate_rank","network_total_screen_m"],kind="mergesort"
            )
            best=connected.iloc[0]
            status="CONNECTED_TO_ROAD_NETWORK"
            gate="PASS_NETWORK_SCREEN"
            br=int(best["candidate_rank"])
            bd=float(best["network_total_screen_m"])
        else:
            status="LOCAL_OSM_COMPONENT_ONLY"
            gate="HOLD_MANUAL_CHECK"
            br=None;bd=None
        field_rows.append({
            "field_id":fid,
            "area_ha":float(r.area_ha),
            "entry_status":r.entry_status,
            "crop2025_name":getattr(r,"crop2025_name",""),
            "n_candidates":int(len(g)),
            "n_network_connected_candidates":int(len(connected)),
            "best_connected_candidate_rank":br,
            "best_network_total_screen_m":bd,
            "network_access_status":status,
            "akerfro_proactive_gate":gate,
        })
    fields=pd.DataFrame(field_rows)
    fields.to_csv(cand_out/"sjobo_field_network_c0.csv",index=False,encoding="utf-8-sig")

    counts=fields["network_access_status"].value_counts().to_dict()
    gate_counts=fields["akerfro_proactive_gate"].value_counts().to_dict()
    report={
        "schema_version":"akeraccess-network-c0-v0a",
        "eligible_fields":int(len(fields)),
        "anchor_highways":sorted(ANCHOR_HIGHWAYS),
        "osm_graph_nodes":int(len(graph)),
        "osm_anchor_nodes":int(len(anchors)),
        "status_counts":{str(k):int(v) for k,v in counts.items()},
        "gate_counts":{str(k):int(v) for k,v in gate_counts.items()},
        "policy":{
            "PASS_NETWORK_SCREEN":"At least one mapped entry candidate connects through OSM drivable network to an ordinary road anchor.",
            "HOLD_MANUAL_CHECK":"No entry candidate or mapped local component does not reach an ordinary road anchor. This is not proof of physical inaccessibility.",
        },
    }
    rp=cand_out/"sjobo_network_c0_report.json"
    rp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")

    print("="*96)
    print("ÅkerAccess STOPPUNKT C0 - ROAD NETWORK CONNECTIVITY")
    print("="*96)
    print(f"Eligible fields: {len(fields):,}")
    print(f"OSM graph nodes: {len(graph):,}")
    print(f"Anchor-road nodes: {len(anchors):,}")
    print("\nNETWORK STATUS")
    for k,v in counts.items(): print(f"  {k:28s} {v:6,d}  {100*v/len(fields):6.2f}%")
    print("\nÅKERFRÖ PROACTIVE GATE")
    for k,v in gate_counts.items(): print(f"  {k:28s} {v:6,d}  {100*v/len(fields):6.2f}%")
    print(f"\nReport: {rp}")
    print("="*96)
    print("STOPPUNKT C0: PASS")
    print("="*96)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
