from __future__ import annotations

import heapq
import math
from collections import defaultdict
from typing import Any

ANCHOR_HIGHWAYS = {
    "road", "unclassified", "residential", "living_street",
    "tertiary", "secondary", "primary",
}


def build_node_graph(
    payload: dict[str, Any],
    transformer,
    drivable_highways: set[str],
    anchor_highways: set[str] = ANCHOR_HIGHWAYS,
):
    """Build an undirected OSM node graph and multi-source anchor set.

    This C0 screen deliberately asks only whether a mapped local way can reach a
    mapped ordinary road. One-way rules are ignored because agricultural access
    screening is not turn-by-turn routing.
    """
    nodes_ll: dict[int, tuple[float, float]] = {}
    ways: list[dict[str, Any]] = []
    for el in payload.get("elements") or []:
        if el.get("type") == "node" and "id" in el and "lon" in el and "lat" in el:
            nodes_ll[int(el["id"])] = (float(el["lon"]), float(el["lat"]))
        elif el.get("type") == "way":
            highway = str((el.get("tags") or {}).get("highway", "")).lower()
            if highway in drivable_highways:
                ways.append(el)

    ids = list(nodes_ll)
    if ids:
        xs, ys = transformer.transform(
            [nodes_ll[n][0] for n in ids],
            [nodes_ll[n][1] for n in ids],
        )
        nodes_xy = {n: (float(x), float(y)) for n, x, y in zip(ids, xs, ys)}
    else:
        nodes_xy = {}

    graph: dict[int, list[tuple[int, float, int, str]]] = defaultdict(list)
    way_nodes: dict[int, list[int]] = {}
    way_highway: dict[int, str] = {}
    anchors: set[int] = set()

    for way in ways:
        wid = int(way["id"])
        highway = str((way.get("tags") or {}).get("highway", "")).lower()
        nids = [int(n) for n in way.get("nodes") or [] if int(n) in nodes_xy]
        if len(nids) < 2:
            continue
        way_nodes[wid] = nids
        way_highway[wid] = highway
        if highway in anchor_highways:
            anchors.update(nids)
        for a, b in zip(nids[:-1], nids[1:]):
            xa, ya = nodes_xy[a]
            xb, yb = nodes_xy[b]
            w = math.hypot(xb - xa, yb - ya)
            if not math.isfinite(w) or w <= 0:
                continue
            graph[a].append((b, w, wid, highway))
            graph[b].append((a, w, wid, highway))
    return graph, nodes_xy, way_nodes, way_highway, anchors


def multisource_dijkstra(graph, sources: set[int]) -> dict[int, float]:
    dist: dict[int, float] = {}
    heap: list[tuple[float, int]] = []
    for node in sources:
        dist[node] = 0.0
        heapq.heappush(heap, (0.0, node))
    while heap:
        d, u = heapq.heappop(heap)
        if d != dist.get(u):
            continue
        for v, weight, _wid, _highway in graph.get(u, []):
            nd = d + weight
            if nd < dist.get(v, math.inf):
                dist[v] = nd
                heapq.heappush(heap, (nd, v))
    return dist


def candidate_connectivity(
    way_id: int,
    entry_xy: tuple[float, float] | None,
    way_nodes: dict[int, list[int]],
    nodes_xy: dict[int, tuple[float, float]],
    distance_to_anchor: dict[int, float],
    way_highway: dict[int, str],
) -> dict[str, Any]:
    nodes = way_nodes.get(int(way_id), [])
    if not nodes:
        return {
            "network_connected": False,
            "network_to_anchor_m": None,
            "entry_to_nearest_way_node_m": None,
            "network_total_screen_m": None,
            "candidate_highway": way_highway.get(int(way_id)),
            "network_reason": "CANDIDATE_WAY_NOT_IN_GRAPH",
        }

    best = math.inf
    entry_offset = math.inf
    for n in nodes:
        d = distance_to_anchor.get(n, math.inf)
        if entry_xy is None:
            offset = 0.0
        else:
            x, y = nodes_xy[n]
            offset = math.hypot(x - entry_xy[0], y - entry_xy[1])
        entry_offset = min(entry_offset, offset)
        best = min(best, d + offset)

    connected = math.isfinite(best)
    anchor_dist = min((distance_to_anchor.get(n, math.inf) for n in nodes), default=math.inf)
    return {
        "network_connected": bool(connected),
        "network_to_anchor_m": float(anchor_dist) if math.isfinite(anchor_dist) else None,
        "entry_to_nearest_way_node_m": float(entry_offset) if math.isfinite(entry_offset) else None,
        "network_total_screen_m": float(best) if connected else None,
        "candidate_highway": way_highway.get(int(way_id)),
        "network_reason": "CONNECTED_TO_ANCHOR_ROAD" if connected else "LOCAL_COMPONENT_WITHOUT_ANCHOR",
    }
