#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D4 — approximate road distance from field entry/road anchor to Bjuv.

Automation-first design:
- downloads/caches a routable Skåne OSM road network in 4x4 tiles,
- builds one directed graph locally,
- runs ONE reverse Dijkstra from the Bjuv processor anchor,
- joins distances to every D0 field with a mapped ordinary-road anchor,
- writes a D2-compatible augmented field table.

This is road-network distance, not turn-by-turn truck navigation. OSM one-way
tags are respected; turn restrictions, dynamic closures, weight/height limits
and traffic are not yet part of D4.
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree

ROOT=Path(__file__).resolve().parents[2]
for p in (ROOT,ROOT/"src"):
    if str(p) not in sys.path:
        sys.path.insert(0,str(p))

from analysis.akeraccess_v0a.entry_discovery_v0a import download_overpass

DEFAULT_D0=ROOT/"work"/"akeraccess_v0a"/"skane_d0"/"skane_akeraccess_road_features_d0.parquet"
DEFAULT_D2=ROOT/"work"/"akeraccess_v0a"/"bestmatch_d2"/"akerfro_akeraccess_d2_fields.parquet"
DEFAULT_C9CFG=ROOT/"config"/"akerfro_ertor_c9.json"
DEFAULT_OSMCFG=ROOT/"config"/"akeraccess_v0a.json"
DEFAULT_RAW=ROOT/"data"/"raw"/"akeraccess_bjuv_route_d4"
DEFAULT_OUT=ROOT/"work"/"akeraccess_v0a"/"bjuv_route_d4"

ROUTE_HIGHWAYS={
    "motorway","motorway_link",
    "trunk","trunk_link",
    "primary","primary_link",
    "secondary","secondary_link",
    "tertiary","tertiary_link",
    "unclassified","residential","living_street","road",
}
BLOCKED_ACCESS={"no","private"}


def load_json(p:Path)->dict[str,Any]:
    return json.loads(p.read_text(encoding="utf-8-sig"))


def route_query(south:float,west:float,north:float,east:float)->str:
    allowed="|".join(sorted(ROUTE_HIGHWAYS))
    b=f"{south:.7f},{west:.7f},{north:.7f},{east:.7f}"
    return f"""[out:json][timeout:180];
way["highway"~"^({allowed})$"]({b});
out body;
>;
out skel qt;
"""


def skane_bounds_from_d0(d0:pd.DataFrame,pad_m:float=10000.0)->tuple[float,float,float,float]:
    x=pd.to_numeric(d0["centroid_x"],errors="coerce").dropna()
    y=pd.to_numeric(d0["centroid_y"],errors="coerce").dropna()
    if x.empty or y.empty:
        raise RuntimeError("D0 lacks usable centroid_x/centroid_y")
    minx,maxx=float(x.min()-pad_m),float(x.max()+pad_m)
    miny,maxy=float(y.min()-pad_m),float(y.max()+pad_m)
    tr=Transformer.from_crs(3006,4326,always_xy=True)
    west,south=tr.transform(minx,miny)
    east,north=tr.transform(maxx,maxy)
    return float(south),float(west),float(north),float(east)


def tile_bounds(bounds:tuple[float,float,float,float],n:int=4):
    south,west,north,east=bounds
    lats=np.linspace(south,north,n+1)
    lons=np.linspace(west,east,n+1)
    for iy in range(n):
        for ix in range(n):
            # Tiny overlap prevents edge precision issues. Whole OSM ways are
            # returned when they intersect a tile, so graph stitching uses IDs.
            eps=0.002
            yield iy,ix,(
                float(lats[iy]-eps),float(lons[ix]-eps),
                float(lats[iy+1]+eps),float(lons[ix+1]+eps)
            )


def load_or_fetch_tiles(
    bounds:tuple[float,float,float,float],
    raw:Path,
    osm_cfg:dict[str,Any],
    refresh:bool,
    ntiles:int=4,
):
    raw.mkdir(parents=True,exist_ok=True)
    payloads=[]
    total=ntiles*ntiles
    for k,(iy,ix,b) in enumerate(tile_bounds(bounds,ntiles),1):
        q=route_query(*b)
        qhash=hashlib.sha256(q.encode("utf-8")).hexdigest()
        p=raw/f"route_tile_{iy}_{ix}.json"
        payload=None
        if p.exists() and not refresh:
            z=load_json(p)
            if (z.get("_akeraccess") or {}).get("query_sha256")==qhash:
                payload=z
                print(f"[{k:02d}/{total:02d}] reuse tile {iy},{ix}")
        if payload is None:
            print(f"[{k:02d}/{total:02d}] fetch tile {iy},{ix} bbox={b}")
            payload,endpoint=download_overpass(
                q,list(osm_cfg["overpass_endpoints"]),
                int(osm_cfg.get("overpass_timeout_s",240))
            )
            payload.setdefault("_akeraccess",{}).update({
                "query_sha256":qhash,
                "endpoint":endpoint,
                "bbox":b,
                "purpose":"akeraccess_bjuv_route_d4"
            })
            p.write_text(json.dumps(payload,ensure_ascii=False),encoding="utf-8")
        payloads.append(payload)
    return payloads


def merge_elements(payloads:list[dict[str,Any]]):
    nodes={}
    ways={}
    for payload in payloads:
        for el in payload.get("elements") or []:
            if el.get("type")=="node" and "id" in el and "lon" in el and "lat" in el:
                nodes[int(el["id"])]=(float(el["lon"]),float(el["lat"]))
            elif el.get("type")=="way" and "id" in el:
                tags=dict(el.get("tags") or {})
                highway=str(tags.get("highway","")).lower()
                if highway in ROUTE_HIGHWAYS:
                    ways[int(el["id"])]={
                        "nodes":[int(n) for n in el.get("nodes") or []],
                        "tags":tags,
                        "highway":highway,
                    }
    return nodes,ways


def oneway_mode(tags:dict[str,Any])->int:
    """1 forward, -1 reverse, 0 bidirectional."""
    v=str(tags.get("oneway","")).strip().casefold()
    if v in {"yes","true","1"}:
        return 1
    if v=="-1":
        return -1
    if str(tags.get("junction","")).casefold()=="roundabout":
        return 1
    return 0


def build_reverse_graph(nodes_ll,ways):
    tr=Transformer.from_crs(4326,3006,always_xy=True)
    ids=list(nodes_ll)
    xs,ys=tr.transform(
        [nodes_ll[n][0] for n in ids],
        [nodes_ll[n][1] for n in ids]
    )
    xy={n:(float(x),float(y)) for n,x,y in zip(ids,xs,ys)}

    # Reverse adjacency: if legal travel is u->v, store v->u so a single
    # Dijkstra from the destination returns distance FROM each node TO Bjuv.
    rev=defaultdict(list)
    kept_ways=0
    for w in ways.values():
        tags=w["tags"]
        access=str(tags.get("access","")).strip().casefold()
        if access in BLOCKED_ACCESS:
            continue
        nids=[n for n in w["nodes"] if n in xy]
        if len(nids)<2:
            continue
        mode=oneway_mode(tags)
        for a,b in zip(nids[:-1],nids[1:]):
            xa,ya=xy[a]; xb,yb=xy[b]
            length=math.hypot(xb-xa,yb-ya)
            if not math.isfinite(length) or length<=0:
                continue
            if mode in {0,1}:      # travel a -> b => reverse b -> a
                rev[b].append((a,length))
            if mode in {0,-1}:     # travel b -> a => reverse a -> b
                rev[a].append((b,length))
        kept_ways+=1
    return rev,xy,kept_ways


def nearest_node(xy:dict[int,tuple[float,float]],x:float,y:float):
    ids=np.array(list(xy.keys()),dtype=np.int64)
    pts=np.array([xy[int(n)] for n in ids],dtype=float)
    tree=cKDTree(pts)
    d,idx=tree.query([x,y],k=1)
    return int(ids[int(idx)]),float(d)


def dijkstra(rev,source:int):
    dist={source:0.0}
    heap=[(0.0,source)]
    while heap:
        d,u=heapq.heappop(heap)
        if d!=dist.get(u):
            continue
        for v,w in rev.get(u,[]):
            nd=d+w
            if nd<dist.get(v,math.inf):
                dist[v]=nd
                heapq.heappush(heap,(nd,v))
    return dist


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--d0",default=str(DEFAULT_D0))
    ap.add_argument("--d2",default=str(DEFAULT_D2))
    ap.add_argument("--c9-config",default=str(DEFAULT_C9CFG))
    ap.add_argument("--osm-config",default=str(DEFAULT_OSMCFG))
    ap.add_argument("--raw",default=str(DEFAULT_RAW))
    ap.add_argument("--out",default=str(DEFAULT_OUT))
    ap.add_argument("--refresh",action="store_true")
    args=ap.parse_args()

    d0_path=Path(args.d0); d2_path=Path(args.d2)
    if not d0_path.exists() or not d2_path.exists():
        raise FileNotFoundError("D4 requires completed D0 and D2")

    d0=pd.read_parquet(d0_path)
    d2=pd.read_parquet(d2_path)
    c9=load_json(Path(args.c9_config))
    osm_cfg=load_json(Path(args.osm_config))
    proc=c9["processor"]
    plat=float(proc["lat"]); plon=float(proc["lon"])

    print("="*118)
    print("ÅkerAccess D4 - ROAD DISTANCE TO BJUV")
    print("="*118)
    print(f"Processor: {proc['name']} · {proc['address']}")
    print("Routing: local OSM graph, one reverse Dijkstra; no per-field routing API calls")

    bounds=skane_bounds_from_d0(d0,10000.0)
    print(f"Skåne route bbox WGS84 (+10 km): {bounds}")
    payloads=load_or_fetch_tiles(bounds,Path(args.raw),osm_cfg,args.refresh,4)

    nodes,ways=merge_elements(payloads)
    print(f"Merged OSM route network: {len(nodes):,} nodes · {len(ways):,} ways")
    rev,xy,kept=build_reverse_graph(nodes,ways)
    print(f"Routable ways after access filter: {kept:,}")

    tr=Transformer.from_crs(4326,3006,always_xy=True)
    bx,by=tr.transform(plon,plat)
    bnode,bsnap=nearest_node(xy,bx,by)
    print(f"Bjuv snapped to OSM node {bnode} at {bsnap:.1f} m")
    dist=dijkstra(rev,bnode)
    print(f"Nodes with directed route to Bjuv: {len(dist):,} / {len(xy):,}")

    anchor=pd.to_numeric(d0.get("path_anchor_node"),errors="coerce")
    lastmile=pd.to_numeric(d0.get("path_last_mile_to_anchor_m"),errors="coerce")
    rows=[]
    for fid,a,lm in zip(d0["field_id"].astype(str),anchor,lastmile):
        if pd.isna(a):
            rows.append((fid,np.nan,np.nan,np.nan,"NO_MAPPED_ANCHOR"))
            continue
        n=int(a)
        rd=dist.get(n)
        if rd is None:
            rows.append((fid,float(lm) if pd.notna(lm) else np.nan,np.nan,np.nan,"ANCHOR_NOT_CONNECTED_TO_BJUV"))
            continue
        lm0=float(lm) if pd.notna(lm) else 0.0
        net=float(rd)+float(bsnap)
        total=lm0+net
        rows.append((fid,lm0,net,total,"ROUTED"))

    route=pd.DataFrame(rows,columns=[
        "field_id","field_last_mile_to_ordinary_road_m",
        "ordinary_road_to_bjuv_m","field_to_bjuv_road_m","bjuv_route_status"
    ])
    route["field_to_bjuv_road_km"]=route["field_to_bjuv_road_m"]/1000.0

    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    rpq=out/"akeraccess_bjuv_route_d4.parquet"
    route.to_parquet(rpq,index=False)

    joined=d2.merge(
        route[["field_id","field_to_bjuv_road_km","bjuv_route_status",
               "field_last_mile_to_ordinary_road_m","ordinary_road_to_bjuv_m"]],
        on="field_id",how="left",validate="one_to_one"
    )
    # Diagnostic road-vs-straight factor; never used when either side missing.
    straight=pd.to_numeric(joined.get("distance_bjuv_km"),errors="coerce")
    road=pd.to_numeric(joined["field_to_bjuv_road_km"],errors="coerce")
    joined["bjuv_road_vs_straight_factor"]=road/straight.where(straight.gt(0))

    jpq=out/"bestmatch_d4_fields.parquet"
    joined.to_parquet(jpq,index=False)

    routed=route["bjuv_route_status"].eq("ROUTED")
    ab=joined["artkandidat_class"].isin(["A_STRONG_CANDIDATE","B_PHYSICAL_CANDIDATE"])
    ab_routed=ab & joined["bjuv_route_status"].eq("ROUTED")
    q=joined.loc[ab_routed,"bjuv_road_vs_straight_factor"].replace([np.inf,-np.inf],np.nan).dropna()

    report={
        "schema_version":"akeraccess-bjuv-route-d4-v0a",
        "processor":proc,
        "route_highways":sorted(ROUTE_HIGHWAYS),
        "semantics":"Approximate OSM road-network distance from mapped field entry via C1 ordinary-road anchor to Bjuv processor. One-way respected; turn restrictions, dynamic closures, traffic and vehicle-specific restrictions not modeled.",
        "network":{"nodes":len(nodes),"ways":len(ways),"routable_ways":kept,"bjuv_snap_m":bsnap},
        "coverage":{
            "d0_fields":int(len(route)),
            "routed_fields":int(routed.sum()),
            "routed_pct":100.0*float(routed.mean()),
            "d2_ab_fields":int(ab.sum()),
            "d2_ab_routed":int(ab_routed.sum()),
            "d2_ab_routed_pct":100.0*float(ab_routed.sum())/float(ab.sum()) if ab.sum() else None,
        },
        "ab_route_factor":{
            "n":int(len(q)),
            "p10":float(q.quantile(.1)) if len(q) else None,
            "p50":float(q.quantile(.5)) if len(q) else None,
            "p90":float(q.quantile(.9)) if len(q) else None,
        },
        "guardrails":[
            "D4 is road-network distance, not certified truck navigation.",
            "C10 BjuvProximity remains frozen/read-only and still uses straight-line distance.",
            "D4 does not yet model turn restrictions, live closures, congestion, legal weight limits or exact factory-gate routing.",
            "The routing graph excludes OSM access=no/private ordinary roads.",
        ],
        "outputs":{"route_table":str(rpq),"d2_augmented":str(jpq)}
    }
    rjson=out/"bjuv_route_d4_report.json"
    rjson.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")

    print("\nRESULT")
    print(f"All D0 routed: {int(routed.sum()):,}/{len(route):,} ({100*routed.mean():.1f}%)")
    print(f"A/B routed: {int(ab_routed.sum()):,}/{int(ab.sum()):,} ({100*ab_routed.sum()/ab.sum():.1f}%)")
    if len(q):
        print(f"A/B road/straight factor p10/p50/p90: {q.quantile(.1):.2f}/{q.quantile(.5):.2f}/{q.quantile(.9):.2f}")
    print(f"Augmented D2: {jpq}")
    print(f"Report: {rjson}")
    print("="*118)
    print("ÅkerAccess D4 ROAD DISTANCE TO BJUV: PASS")
    print("="*118)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
