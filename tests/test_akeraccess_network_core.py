#!/usr/bin/env python3
from __future__ import annotations

import unittest
from analysis.akeraccess_v0a.network_core import (
    build_node_graph,
    candidate_connectivity,
    multisource_dijkstra,
)


class IdentityTransformer:
    def transform(self, xs, ys):
        return xs, ys


class TestAkerAccessNetworkCore(unittest.TestCase):
    def test_track_connected_to_unclassified(self):
        payload = {"elements": [
            {"type":"node","id":1,"lon":0,"lat":0},
            {"type":"node","id":2,"lon":10,"lat":0},
            {"type":"node","id":3,"lon":20,"lat":0},
            {"type":"way","id":100,"nodes":[1,2],"tags":{"highway":"track"}},
            {"type":"way","id":200,"nodes":[2,3],"tags":{"highway":"unclassified"}},
        ]}
        g, xy, wn, wh, anchors = build_node_graph(
            payload, IdentityTransformer(), {"track","unclassified"}
        )
        dist = multisource_dijkstra(g, anchors)
        r = candidate_connectivity(100, (0,0), wn, xy, dist, wh)
        self.assertTrue(r["network_connected"])
        self.assertAlmostEqual(r["network_to_anchor_m"], 0.0)  # node 2 is anchor

    def test_isolated_track_not_connected(self):
        payload = {"elements": [
            {"type":"node","id":1,"lon":0,"lat":0},
            {"type":"node","id":2,"lon":10,"lat":0},
            {"type":"node","id":3,"lon":100,"lat":0},
            {"type":"node","id":4,"lon":110,"lat":0},
            {"type":"way","id":100,"nodes":[1,2],"tags":{"highway":"track"}},
            {"type":"way","id":200,"nodes":[3,4],"tags":{"highway":"unclassified"}},
        ]}
        g, xy, wn, wh, anchors = build_node_graph(
            payload, IdentityTransformer(), {"track","unclassified"}
        )
        dist = multisource_dijkstra(g, anchors)
        r = candidate_connectivity(100, (0,0), wn, xy, dist, wh)
        self.assertFalse(r["network_connected"])
        self.assertEqual(r["network_reason"], "LOCAL_COMPONENT_WITHOUT_ANCHOR")


if __name__ == "__main__":
    unittest.main()
