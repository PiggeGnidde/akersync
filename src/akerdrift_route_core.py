#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic geometry-only route engine for the ÅkerDrift pilot.

The public Fast score is deliberately left untouched.  This module replaces
only its P/A geometry proxy with parallel working swaths and explicit
non-productive transitions.  Terrain is applied by the pilot runner using the
already calculated Fast V1 terrain factor, which makes the comparison easy to
interpret.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


MODEL_VERSION = "akerdrift-route-pilot-v1a-rc0"
ENGINE_VERSION = "shapely-parallel-swath-v1"


@dataclass(frozen=True)
class RouteConfig:
    work_width_m: float = 9.0
    headland_width_m: float = 24.0
    min_turn_radius_m: float = 8.0
    work_speed_m_s: float = 1.0
    turn_speed_m_s: float = 0.5
    coarse_heading_step_deg: int = 5
    refine_best_count: int = 3
    refine_half_window_deg: int = 5
    refine_step_deg: int = 1
    long_run_threshold_m: float = 100.0


@dataclass(frozen=True)
class RouteCandidate:
    heading_deg: float
    productive_distance_m: float
    productive_distance_raw_m: float
    interior_distance_m: float
    headland_distance_m: float
    nonproductive_distance_m: float
    turn_count: int
    segment_count: int
    long_run_count: int
    short_run_count: int
    coverage_ratio_estimate: float
    ideal_time_s: float
    work_time_s: float
    turn_time_s: float
    equivalent_time_s: float
    geometry_score: float


def load_route_config(path: str | Path) -> tuple[dict[str, Any], RouteConfig]:
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if raw.get("model_version") != MODEL_VERSION:
        raise ValueError(f"Okänd ruttpilotversion: {raw.get('model_version')!r}")
    if raw.get("route_engine") != ENGINE_VERSION:
        raise ValueError(f"Okänd ruttmotor: {raw.get('route_engine')!r}")
    config = RouteConfig(**(raw.get("route") or {}))
    validate_route_config(config)
    return raw, config


def validate_route_config(config: RouteConfig) -> None:
    positive = (
        "work_width_m", "headland_width_m", "min_turn_radius_m",
        "work_speed_m_s", "turn_speed_m_s", "coarse_heading_step_deg",
        "refine_best_count", "refine_step_deg", "long_run_threshold_m",
    )
    for name in positive:
        if float(getattr(config, name)) <= 0:
            raise ValueError(f"route.{name} måste vara positiv")
    if config.coarse_heading_step_deg >= 180:
        raise ValueError("coarse_heading_step_deg måste vara mindre än 180")
    if config.refine_half_window_deg < 0:
        raise ValueError("refine_half_window_deg får inte vara negativ")


def config_hash(raw_config: dict[str, Any]) -> str:
    payload = json.dumps(raw_config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _line_parts(geometry: Any) -> list[Any]:
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry] if geometry.length > 1e-9 else []
    if geometry.geom_type in {"MultiLineString", "GeometryCollection"}:
        parts: list[Any] = []
        for child in geometry.geoms:
            parts.extend(_line_parts(child))
        return parts
    return []


def _oriented_endpoints(line: Any, left_to_right: bool) -> tuple[tuple[float, float], tuple[float, float]]:
    coordinates = list(line.coords)
    first = (float(coordinates[0][0]), float(coordinates[0][1]))
    last = (float(coordinates[-1][0]), float(coordinates[-1][1]))
    if (first[0] <= last[0]) != left_to_right:
        first, last = last, first
    return first, last


def _row_positions(minimum: float, maximum: float, width: float) -> list[float]:
    height = maximum - minimum
    if height <= 0:
        return []
    count = max(1, int(round(height / width)))
    span = (count - 1) * width
    start = (minimum + maximum - span) / 2.0
    return [start + index * width for index in range(count)]


def _candidate(geometry: Any, heading_deg: float, config: RouteConfig) -> RouteCandidate:
    try:
        from shapely import affinity
        from shapely.geometry import LineString
    except ImportError as exc:
        raise RuntimeError("Ruttpiloten kräver shapely. Kör INSTALL_REQUIREMENTS.bat.") from exc

    rotated = affinity.rotate(geometry, -heading_deg, origin="centroid", use_radians=False)
    min_x, min_y, max_x, max_y = rotated.bounds
    margin = max(max_x - min_x, max_y - min_y, config.work_width_m) + config.headland_width_m
    interior = rotated.buffer(-config.headland_width_m)
    if interior.is_empty:
        interior = None

    rows: list[list[Any]] = []
    for y in _row_positions(min_y, max_y, config.work_width_m):
        cutter = LineString([(min_x - margin, y), (max_x + margin, y)])
        parts = sorted(_line_parts(rotated.intersection(cutter)), key=lambda item: (item.bounds[0], item.bounds[2]))
        if parts:
            rows.append(parts)

    productive_raw = 0.0
    interior_raw = 0.0
    segment_lengths: list[float] = []
    nonproductive = 0.0
    previous_end: tuple[float, float] | None = None
    segment_count = 0

    for row_index, parts in enumerate(rows):
        left_to_right = row_index % 2 == 0
        ordered = parts if left_to_right else list(reversed(parts))
        for part in ordered:
            start, end = _oriented_endpoints(part, left_to_right)
            length = float(part.length)
            if length <= 1e-9:
                continue
            if previous_end is not None:
                direct = math.hypot(start[0] - previous_end[0], start[1] - previous_end[1])
                # A transition is never cheaper than a half-circle at the frozen
                # minimum turning radius.  Extra fragments caused by holes or
                # concavities therefore receive an explicit route penalty.
                nonproductive += max(direct, math.pi * config.min_turn_radius_m)
            productive_raw += length
            if interior is not None:
                interior_raw += float(part.intersection(interior).length)
            segment_lengths.append(length)
            segment_count += 1
            previous_end = end

    if productive_raw <= 0 or segment_count == 0:
        raise ValueError("Inga körbara parallellspår kunde skapas")

    area_m2 = float(geometry.area)
    ideal_productive = area_m2 / config.work_width_m
    productive = max(ideal_productive, productive_raw)
    scale = productive / productive_raw
    interior_distance = min(productive, max(0.0, interior_raw * scale))
    headland_distance = max(0.0, productive - interior_distance)
    ideal_time = ideal_productive / config.work_speed_m_s
    work_time = productive / config.work_speed_m_s
    turn_time = nonproductive / config.turn_speed_m_s
    equivalent_time = max(ideal_time, work_time + turn_time)
    score = 100.0 * ideal_time / equivalent_time if equivalent_time > 0 else 0.0
    score = min(100.0, max(0.0, score))
    long_runs = sum(length >= config.long_run_threshold_m for length in segment_lengths)

    return RouteCandidate(
        heading_deg=float(heading_deg % 180.0),
        productive_distance_m=productive,
        productive_distance_raw_m=productive_raw,
        interior_distance_m=interior_distance,
        headland_distance_m=headland_distance,
        nonproductive_distance_m=nonproductive,
        turn_count=max(0, segment_count - 1),
        segment_count=segment_count,
        long_run_count=int(long_runs),
        short_run_count=int(segment_count - long_runs),
        coverage_ratio_estimate=float(productive_raw * config.work_width_m / area_m2),
        ideal_time_s=ideal_time,
        work_time_s=work_time,
        turn_time_s=turn_time,
        equivalent_time_s=equivalent_time,
        geometry_score=score,
    )


def _heading_range(step: int) -> Iterable[int]:
    return range(0, 180, step)


def simulate_route(geometry: Any, config: RouteConfig) -> dict[str, Any]:
    """Return the best deterministic parallel-swath route for one polygon."""
    if geometry is None or geometry.is_empty or float(geometry.area) <= 0:
        raise ValueError("Tom eller ogiltig skiftesgeometri")
    coarse = [_candidate(geometry, heading, config) for heading in _heading_range(config.coarse_heading_step_deg)]
    coarse.sort(key=lambda item: (item.equivalent_time_s, item.heading_deg))
    headings = {int(item.heading_deg) for item in coarse}
    for seed in coarse[: config.refine_best_count]:
        start = -config.refine_half_window_deg
        stop = config.refine_half_window_deg + 1
        for delta in range(start, stop, config.refine_step_deg):
            headings.add(int(round(seed.heading_deg + delta)) % 180)
    candidates = [_candidate(geometry, heading, config) for heading in sorted(headings)]
    best = min(candidates, key=lambda item: (item.equivalent_time_s, item.heading_deg))
    result = asdict(best)
    result.update({
        "route_model_version": MODEL_VERSION,
        "route_engine": ENGINE_VERSION,
        "candidate_heading_count": len(candidates),
        "area_m2": float(geometry.area),
        "area_ha": float(geometry.area) / 10_000.0,
    })
    return result
