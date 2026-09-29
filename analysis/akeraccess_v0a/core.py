from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

DRIVABLE_HIGHWAYS = {
    "track", "service", "unclassified", "residential", "living_street",
    "tertiary", "secondary", "primary", "road",
}

@dataclass(frozen=True)
class CandidateAssessment:
    kind: str
    confidence: float
    line_distance_m: float
    endpoint_distance_m: float
    inside_length_m: float
    gate_near: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def text_id(value: Any) -> str:
    if value is None:
        return ""
    try:
        import pandas as pd
        if pd.isna(value):
            return ""
    except Exception:
        pass
    s = str(value).strip()
    return s[:-2] if s.endswith(".0") else s


def field_key(block_id: Any, skifte_id: Any) -> str:
    return f"{text_id(block_id)}|{text_id(skifte_id)}"


def _endpoints(line):
    coords = list(line.coords)
    return coords[0], coords[-1]


def _point_distance_to_boundary(boundary, xy) -> float:
    from shapely.geometry import Point
    return float(boundary.distance(Point(float(xy[0]), float(xy[1]))))


def classify_road_candidate(field_geometry, line_geometry, highway: str | None, gate_near: bool,
                            thresholds: dict[str, float]) -> CandidateAssessment | None:
    """Classify one OSM road/track relative to one field polygon.

    The penetration test uses a small negative field buffer so a road merely
    digitised along the field boundary is not mistaken for an entrance.
    """
    if field_geometry is None or field_geometry.is_empty or line_geometry is None or line_geometry.is_empty:
        return None
    highway = (highway or "").strip().lower()
    if highway not in DRIVABLE_HIGHWAYS:
        return None

    boundary = field_geometry.boundary
    line_distance = float(boundary.distance(line_geometry))
    try:
        first, last = _endpoints(line_geometry)
        endpoint_distance = min(
            _point_distance_to_boundary(boundary, first),
            _point_distance_to_boundary(boundary, last),
        )
    except Exception:
        endpoint_distance = math.inf

    interior_probe = float(thresholds.get("interior_probe_m", 0.75))
    probe = field_geometry.buffer(-interior_probe)
    inside_length = 0.0 if probe.is_empty else float(line_geometry.intersection(probe).length)
    enter_min = float(thresholds.get("enter_inside_min_m", 2.0))
    strong_ep = float(thresholds.get("endpoint_strong_m", 5.0))
    possible_ep = float(thresholds.get("endpoint_possible_m", 15.0))
    adjacency = float(thresholds.get("adjacency_m", 5.0))

    if inside_length >= enter_min:
        kind = "OSM_LINE_ENTERS_FIELD"
        confidence = 0.95 if highway in {"track", "service"} else 0.85
    elif endpoint_distance <= strong_ep:
        kind = "OSM_ENDPOINT_WITHIN_5M"
        confidence = 0.85 if highway in {"track", "service"} else 0.72
    elif endpoint_distance <= possible_ep:
        kind = "OSM_ENDPOINT_WITHIN_15M"
        confidence = 0.65 if highway in {"track", "service"} else 0.52
    elif line_distance <= adjacency:
        kind = "ROAD_ADJACENT_ONLY"
        confidence = 0.35
    else:
        return None

    if gate_near:
        if kind == "OSM_LINE_ENTERS_FIELD":
            kind = "OSM_LINE_ENTERS_FIELD_WITH_GATE"
            confidence = 1.00
        else:
            kind = kind + "_WITH_GATE"
            confidence = min(0.97, confidence + 0.12)

    return CandidateAssessment(
        kind=kind,
        confidence=confidence,
        line_distance_m=line_distance,
        endpoint_distance_m=endpoint_distance,
        inside_length_m=inside_length,
        gate_near=bool(gate_near),
    )


def parse_overpass(payload: dict[str, Any]):
    """Parse Overpass JSON into drivable way records and gate records."""
    elements = payload.get("elements") or []
    nodes: dict[int, tuple[float, float]] = {}
    node_tags: dict[int, dict[str, Any]] = {}
    ways: list[dict[str, Any]] = []
    for el in elements:
        etype = el.get("type")
        if etype == "node" and "id" in el and "lat" in el and "lon" in el:
            node_id = int(el["id"])
            nodes[node_id] = (float(el["lon"]), float(el["lat"]))
            if el.get("tags"):
                node_tags[node_id] = dict(el.get("tags") or {})
        elif etype == "way" and el.get("tags", {}).get("highway"):
            ways.append(el)

    roads = []
    for way in ways:
        node_ids = [int(n) for n in way.get("nodes") or []]
        if len(node_ids) < 2 or any(n not in nodes for n in node_ids):
            continue
        tags = dict(way.get("tags") or {})
        highway = str(tags.get("highway", "")).lower()
        if highway not in DRIVABLE_HIGHWAYS:
            continue
        roads.append({
            "osm_way_id": int(way["id"]),
            "highway": highway,
            "tags": tags,
            "coords": [nodes[n] for n in node_ids],
        })

    gates = []
    for node_id, tags in node_tags.items():
        barrier = str(tags.get("barrier", "")).lower()
        if barrier in {"gate", "lift_gate", "swing_gate"}:
            lon, lat = nodes[node_id]
            gates.append({
                "osm_node_id": node_id,
                "barrier": barrier,
                "tags": tags,
                "coord": (lon, lat),
            })
    return roads, gates
