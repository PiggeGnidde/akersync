#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from shapely.geometry import LineString, Polygon

from analysis.akeraccess_v0a.core import (
    classify_road_candidate,
    field_key,
    parse_overpass,
)

TH = {
    "interior_probe_m": 0.75,
    "enter_inside_min_m": 2.0,
    "endpoint_strong_m": 5.0,
    "endpoint_possible_m": 15.0,
    "adjacency_m": 5.0,
}


class TestAkerAccessEntryDiscoveryV0A(unittest.TestCase):
    def setUp(self):
        self.field = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])

    def test_track_entering_field_is_strong(self):
        result = classify_road_candidate(
            self.field, LineString([(-10, 50), (20, 50)]), "track", False, TH
        )
        self.assertEqual(result.kind, "OSM_LINE_ENTERS_FIELD")
        self.assertAlmostEqual(result.confidence, 0.95)

    def test_boundary_line_is_not_called_entering(self):
        result = classify_road_candidate(
            self.field, LineString([(0, 10), (0, 90)]), "track", False, TH
        )
        self.assertNotEqual(result.kind, "OSM_LINE_ENTERS_FIELD")

    def test_gate_boosts_entering_track(self):
        result = classify_road_candidate(
            self.field, LineString([(-10, 50), (20, 50)]), "track", True, TH
        )
        self.assertEqual(result.kind, "OSM_LINE_ENTERS_FIELD_WITH_GATE")
        self.assertEqual(result.confidence, 1.0)

    def test_endpoint_within_five_metres(self):
        result = classify_road_candidate(
            self.field, LineString([(-20, 50), (-3, 50)]), "service", False, TH
        )
        self.assertEqual(result.kind, "OSM_ENDPOINT_WITHIN_5M")

    def test_parallel_road_is_adjacency_only(self):
        result = classify_road_candidate(
            self.field, LineString([(-3, -20), (-3, 120)]), "unclassified", False, TH
        )
        self.assertEqual(result.kind, "ROAD_ADJACENT_ONLY")

    def test_parse_overpass_way_and_gate(self):
        payload = {
            "elements": [
                {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "track"}},
                {"type": "node", "id": 1, "lat": 55.0, "lon": 13.0, "tags": {"barrier": "gate"}},
                {"type": "node", "id": 2, "lat": 55.1, "lon": 13.1},
            ]
        }
        roads, gates = parse_overpass(payload)
        self.assertEqual(len(roads), 1)
        self.assertEqual(len(gates), 1)

    def test_field_key(self):
        self.assertEqual(field_key(123.0, "A"), "123|A")


if __name__ == "__main__":
    unittest.main()
