from __future__ import annotations

import heapq
import math
import re
from collections import defaultdict
from typing import Any

BAD_ACCESS = {"no", "private"}
SOFT_ACCESS = {"destination", "customers", "delivery", "permit"}
AG_OK_ACCESS = {"agricultural", "forestry"}


def parse_metric_m(value: Any) -> float | None:
    if value is None:
        return None
    s=str(value).strip().lower().replace(",", ".")
    if not s:
        return None
    # Conservative parser: first numeric value, metres by default.
    m=re.search(r"[-+]?\d+(?:\.\d+)?",s)
    if not m:
        return None
    x=float(m.group(0))
    if "cm" in s:
        x/=100.0
    elif "mm" in s:
        x/=1000.0
    elif "ft" in s or "'" in s:
        x*=0.3048
    return x if math.isfinite(x) and x>=0 else None


def build_tagged_graph(payload: dict[str,Any], transformer, drivable_highways:set[str], anchor_highways:set[str]):
    nodes_ll={}
    node_tags={}
    ways={}
    for el in payload.get("elements") or []:
        if el.get("type")=="node" and "id" in el and "lon" in el and "lat" in el:
            nid=int(el["id"])
            nodes_ll[nid]=(float(el["lon"]),float(el["lat"]))
            node_tags[nid]=dict(el.get("tags") or {})
        elif el.get("type")=="way":
            tags=dict(el.get("tags") or {})
            highway=str(tags.get("highway","")).lower()
            if highway in drivable_highways:
                ways[int(el["id"])]={
                    "nodes":[int(n) for n in el.get("nodes") or []],
                    "highway":highway,
                    "tags":tags,
                }

    ids=list(nodes_ll)
    if ids:
        xs,ys=transformer.transform([nodes_ll[n][0] for n in ids],[nodes_ll[n][1] for n in ids])
        xy={n:(float(x),float(y)) for n,x,y in zip(ids,xs,ys)}
    else:
        xy={}

    graph=defaultdict(list)
    anchors=set()
    for wid,w in ways.items():
        nids=[n for n in w["nodes"] if n in xy]
        w["nodes"]=nids
        if w["highway"] in anchor_highways:
            anchors.update(nids)
        for a,b in zip(nids[:-1],nids[1:]):
            xa,ya=xy[a]; xb,yb=xy[b]
            length=math.hypot(xb-xa,yb-ya)
            if length>0 and math.isfinite(length):
                graph[a].append((b,length,wid))
                graph[b].append((a,length,wid))
    return graph,xy,ways,node_tags,anchors


def dijkstra_to_anchors(graph, anchors:set[int]):
    dist={}
    parent={}
    heap=[]
    for n in anchors:
        dist[n]=0.0
        parent[n]=None
        heapq.heappush(heap,(0.0,n))
    while heap:
        d,u=heapq.heappop(heap)
        if d!=dist.get(u):
            continue
        for v,w,wid in graph.get(u,[]):
            nd=d+w
            if nd<dist.get(v,math.inf):
                dist[v]=nd
                parent[v]=(u,wid,w)
                heapq.heappush(heap,(nd,v))
    return dist,parent


def _way_cumulative(way_nodes:list[int], xy:dict[int,tuple[float,float]]):
    cum={}
    total=0.0
    prev=None
    for n in way_nodes:
        if n not in xy:
            continue
        if prev is not None:
            total+=math.hypot(xy[n][0]-xy[prev][0],xy[n][1]-xy[prev][1])
        cum[n]=total
        prev=n
    return cum,total


def candidate_start_node(entry_xy, way:dict[str,Any], xy, dist_to_anchor):
    """Approximate exact along-way cost from entry point to each way node.

    Project entry point onto the candidate LineString, then use cumulative
    distance along the OSM way rather than Euclidean node distance.
    """
    from shapely.geometry import LineString, Point
    nodes=[n for n in way["nodes"] if n in xy]
    if not nodes:
        return None
    line=LineString([xy[n] for n in nodes])
    if line.is_empty or line.length<=0:
        return None
    p=Point(entry_xy)
    s=float(line.project(p))
    cum,_=_way_cumulative(nodes,xy)
    best=None
    for n in nodes:
        da=dist_to_anchor.get(n,math.inf)
        if not math.isfinite(da):
            continue
        start_cost=abs(cum[n]-s)
        total=start_cost+da
        cand=(total,start_cost,n,s)
        if best is None or cand[:2]<best[:2]:
            best=cand
    if best is None:
        return None
    return {"node":best[2],"entry_along_way_m":best[1],"total_to_anchor_m":best[0],"project_m":best[3]}


def reconstruct_to_anchor(start_node:int,parent:dict[int,Any]):
    edges=[]
    u=start_node
    seen=set()
    while u in parent and parent[u] is not None:
        if u in seen:
            raise RuntimeError("Cycle in Dijkstra parent tree")
        seen.add(u)
        v,wid,length=parent[u]
        edges.append((u,v,wid,float(length)))
        u=v
    return edges,u


def summarize_candidate_path(entry_xy, way_id:int, ways, xy, node_tags, dist, parent):
    wid=int(way_id)
    way=ways.get(wid)
    if way is None:
        return {"path_status":"WAY_NOT_IN_GRAPH"}

    start=candidate_start_node(entry_xy,way,xy,dist)
    if start is None:
        return {"path_status":"NOT_CONNECTED"}

    edges,anchor_node=reconstruct_to_anchor(int(start["node"]),parent)
    traversed_way_ids=[wid]+[int(e[2]) for e in edges]
    # Deduplicate while preserving order.
    unique=[]
    seen=set()
    for x in traversed_way_ids:
        if x not in seen:
            seen.add(x); unique.append(x)

    highway_m=defaultdict(float)
    for _u,_v,ewid,length in edges:
        highway_m[ways[ewid]["highway"]]+=float(length)
    # Entry-to-start-node lies on candidate way.
    highway_m[way["highway"]]+=float(start["entry_along_way_m"])

    way_tags=[ways[x]["tags"] for x in unique if x in ways]
    access_vals=[str(t.get("access","")).strip().lower() for t in way_tags if str(t.get("access","")).strip()]
    bad_access=sorted({x for x in access_vals if x in BAD_ACCESS})
    soft_access=sorted({x for x in access_vals if x in SOFT_ACCESS})
    ag_access=sorted({x for x in access_vals if x in AG_OK_ACCESS})

    widths=[]
    heights=[]
    surfaces=[]
    tracktypes=[]
    for t in way_tags:
        for k in ("width","maxwidth"):
            x=parse_metric_m(t.get(k))
            if x is not None: widths.append(x)
        x=parse_metric_m(t.get("maxheight"))
        if x is not None: heights.append(x)
        if t.get("surface"): surfaces.append(str(t.get("surface")))
        if t.get("tracktype"): tracktypes.append(str(t.get("tracktype")))

    path_nodes={int(start["node"]),int(anchor_node)}
    for u,v,_wid,_l in edges:
        path_nodes.add(int(u)); path_nodes.add(int(v))
    barriers=[]
    for n in path_nodes:
        tags=node_tags.get(n,{})
        b=str(tags.get("barrier","")).lower()
        if b:
            barriers.append((n,b,str(tags.get("access",""))))

    total=float(start["total_to_anchor_m"])
    return {
        "path_status":"CONNECTED",
        "anchor_node":int(anchor_node),
        "entry_along_candidate_way_m":float(start["entry_along_way_m"]),
        "last_mile_to_anchor_m":total,
        "track_m":float(highway_m.get("track",0.0)),
        "service_m":float(highway_m.get("service",0.0)),
        "other_local_m":float(sum(v for k,v in highway_m.items() if k not in {"track","service"})),
        "n_path_ways":int(len(unique)),
        "path_way_ids":";".join(map(str,unique)),
        "path_highways":";".join(ways[x]["highway"] for x in unique if x in ways),
        "surface_values":";".join(sorted(set(surfaces))),
        "tracktype_values":";".join(sorted(set(tracktypes))),
        "min_known_width_m":min(widths) if widths else None,
        "min_known_maxheight_m":min(heights) if heights else None,
        "explicit_width_lt_4_5":bool(widths and min(widths)<4.5),
        "explicit_height_lt_4_5":bool(heights and min(heights)<4.5),
        "bad_access_values":";".join(bad_access),
        "soft_access_values":";".join(soft_access),
        "ag_access_values":";".join(ag_access),
        "has_bad_access":bool(bad_access),
        "has_soft_access":bool(soft_access),
        "n_barriers":int(len(barriers)),
        "barrier_values":";".join(sorted({b for _n,b,_a in barriers})),
        "path_geometry_note":"OSM shortest mapped last-mile to first ordinary-road anchor",
    }
