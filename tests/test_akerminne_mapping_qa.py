from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

spec = importlib.util.spec_from_file_location("mapping_qa", SRC / "53_akerminne_mapping_qa.py")
qa = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(qa)


class MappingQaTests(unittest.TestCase):
    def frame(self, geoms, keys=None):
        keys = keys or [(f"b{i}", f"s{i}") for i in range(len(geoms))]
        return gpd.GeoDataFrame({"blockid": [x[0] for x in keys], "skiftesbeteckning": [x[1] for x in keys]}, geometry=geoms, crs="EPSG:3006")

    def test_self_overlap_detects_duplicate_polygon(self):
        g = qa.prepare(self.frame([box(0,0,10,10), box(0,0,10,10)]))
        summary, pairs = qa.self_overlap_summary(g)
        self.assertEqual(summary["positive_pairs"], 1)
        self.assertEqual(summary["min_fraction_gt_0_90"], 1)
        self.assertAlmostEqual(float(pairs.iloc[0]["intersection_m2"]), 100.0)

    def test_exact_duplicate_geometry_ignores_different_admin_keys(self):
        g = qa.prepare(self.frame([box(0,0,10,10), box(0,0,10,10)], [("A","1"),("B","9")]))
        s = qa.exact_duplicate_geometry_summary(g)
        self.assertEqual(s["duplicate_geometry_groups"], 1)
        self.assertEqual(s["rows_in_duplicate_geometry_groups"], 2)

    def test_anomaly_union_separates_double_counting(self):
        cur = self.frame([box(0,0,10,10)], [("C","1")])
        hist = self.frame([box(0,0,10,10), box(0,0,10,10)], [("H","1"),("H","2")])
        matches = pd.DataFrame([{"current_field_id":"C|1", "match_confidence":"merge", "coverage_raw":2.0, "positive_overlap_edges":2, "qualifying_relaxed_edges":2}])
        edges = pd.DataFrame([
            {"current_field_key":"C|1", "historical_field_key":"H|1", "intersection_m2":100.0},
            {"current_field_key":"C|1", "historical_field_key":"H|2", "intersection_m2":100.0},
        ])
        d = qa.anomaly_union_diagnostics(cur, hist, matches, edges)
        self.assertEqual(len(d), 1)
        self.assertAlmostEqual(float(d.iloc[0]["coverage_union"]), 1.0)
        self.assertAlmostEqual(float(d.iloc[0]["excess_coverage"]), 1.0)
        self.assertEqual(int(d.iloc[0]["exact_duplicate_neighbor_pairs"]), 1)

    def test_nonoverlapping_partition_has_no_excess(self):
        cur = self.frame([box(0,0,10,10)], [("C","1")])
        hist = self.frame([box(0,0,5,10), box(5,0,10,10)], [("H","1"),("H","2")])
        matches = pd.DataFrame([{"current_field_id":"C|1", "match_confidence":"merge", "coverage_raw":1.0, "positive_overlap_edges":2, "qualifying_relaxed_edges":2}])
        edges = pd.DataFrame([
            {"current_field_key":"C|1", "historical_field_key":"H|1", "intersection_m2":50.0},
            {"current_field_key":"C|1", "historical_field_key":"H|2", "intersection_m2":50.0},
        ])
        d = qa.anomaly_union_diagnostics(cur, hist, matches, edges)
        self.assertEqual(len(d), 0)


if __name__ == "__main__":
    unittest.main()
