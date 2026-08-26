#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon, box

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from akerminne_mapping_core import MatchingConfig, map_fields  # noqa: E402


def frame(rows, crs="EPSG:3006"):
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)


def row(block, field, geom):
    return {"blockid": block, "skiftesbeteckning": field, "geometry": geom}


class MappingTests(unittest.TestCase):
    def test_direct_id_requires_strict_geometry(self):
        c = frame([row("B1", "A", box(0, 0, 10, 10))])
        h = frame([row("B1", "A", box(0, 0, 10, 10))])
        m, e, _ = map_fields(c, h)
        self.assertEqual(m.iloc[0].match_confidence, "direct_id")
        self.assertAlmostEqual(e.iloc[0].strict_score, 1.0)

    def test_same_id_does_not_override_split_topology(self):
        # Historical A spans both current A and B. Same id exists for one half,
        # but geometry graph must still classify both as a split.
        c = frame([
            row("B1", "A", box(0, 0, 5, 10)),
            row("B1", "B", box(5, 0, 10, 10)),
        ])
        h = frame([row("B1", "A", box(0, 0, 10, 10))])
        m, _, _ = map_fields(c, h)
        self.assertEqual(set(m.match_confidence), {"split"})

    def test_merge_uses_relaxed_max_fraction(self):
        c = frame([row("C", "1", box(0, 0, 10, 10))])
        h = frame([
            row("H", "1", box(0, 0, 5, 10)),
            row("H", "2", box(5, 0, 10, 10)),
        ])
        m, e, _ = map_fields(c, h)
        self.assertEqual(m.iloc[0].match_confidence, "merge")
        self.assertTrue((e.relaxed_score == 1.0).all())
        self.assertTrue((e.strict_score == 0.5).all())

    def test_one_to_one_relaxed(self):
        c = frame([row("C", "1", box(0, 0, 10, 10))])
        h = frame([row("H", "1", box(0, 0, 8, 10))])
        m, _, _ = map_fields(c, h)
        self.assertEqual(m.iloc[0].match_confidence, "one_to_one_relaxed")
        self.assertAlmostEqual(m.iloc[0].primary_f_current, 0.8)
        self.assertAlmostEqual(m.iloc[0].primary_f_historical, 1.0)

    def test_one_to_one_strict_different_admin_id(self):
        c = frame([row("C", "1", box(0, 0, 10, 10))])
        h = frame([row("H", "9", box(0, 0, 10, 10))])
        m, _, _ = map_fields(c, h)
        self.assertEqual(m.iloc[0].match_confidence, "one_to_one_strict")

    def test_many_to_many_is_ambiguous(self):
        c = frame([
            row("C", "1", box(0, 0, 10, 10)),
            row("C", "2", box(0, 0, 10, 10)),
        ])
        h = frame([
            row("H", "1", box(0, 0, 5, 10)),
            row("H", "2", box(5, 0, 10, 10)),
        ])
        m, _, _ = map_fields(c, h, MatchingConfig(relaxed_max_fraction=0.40))
        self.assertEqual(set(m.match_confidence), {"ambiguous"})

    def test_unmatched_below_threshold_retains_raw_edge(self):
        c = frame([row("C", "1", box(0, 0, 10, 10))])
        h = frame([row("H", "1", box(8, 0, 18, 10))])
        m, e, _ = map_fields(c, h)
        self.assertEqual(len(e), 1)
        self.assertEqual(m.iloc[0].match_confidence, "unmatched")
        self.assertEqual(m.iloc[0].match_reason, "BELOW_RELAXED_THRESHOLD")
        self.assertAlmostEqual(m.iloc[0].coverage_raw, 0.2)

    def test_no_overlap_unmatched(self):
        c = frame([row("C", "1", box(0, 0, 10, 10))])
        h = frame([row("H", "1", box(20, 20, 30, 30))])
        m, e, _ = map_fields(c, h)
        self.assertEqual(len(e), 0)
        self.assertEqual(m.iloc[0].match_reason, "NO_POSITIVE_OVERLAP")

    def test_duplicate_historical_overlap_flags_coverage_over_one(self):
        c = frame([row("C", "1", box(0, 0, 10, 10))])
        h = frame([
            row("H", "1", box(0, 0, 10, 10)),
            row("H", "2", box(0, 0, 10, 10)),
        ])
        m, _, qa = map_fields(c, h)
        self.assertAlmostEqual(m.iloc[0].coverage_raw, 2.0)
        self.assertTrue(bool(m.iloc[0].overlap_anomaly))
        self.assertEqual(qa["overlap_anomaly_count"], 1)

    def test_centroid_breaks_exact_area_primary_tie(self):
        c = frame([row("C", "1", box(0, 0, 10, 10))])
        # Both overlap 50 m2, but Hnear centroid is closer to current centroid.
        h = frame([
            row("H", "far", box(0, 0, 5, 10)),
            row("H", "near", box(5, 0, 10, 10)),
        ])
        # Symmetric halves have equal centroid distance, so move the far polygon's
        # non-overlapping portion outward while preserving 50 m2 intersection.
        h.loc[0, "geometry"] = box(-5, 0, 5, 10)
        _, e, _ = map_fields(c, h)
        primary = e[e["is_current_primary"]].iloc[0]
        self.assertEqual(primary.historical_field_key, "H|near")

    def test_invalid_repairable_geometry_is_reported(self):
        bowtie = Polygon([(0, 0), (10, 10), (0, 10), (10, 0), (0, 0)])
        c = frame([row("C", "1", bowtie)])
        h = frame([row("H", "1", box(0, 0, 10, 10))])
        _, _, qa = map_fields(c, h)
        self.assertEqual(qa["current"]["repaired"], 1)
        self.assertEqual(qa["current"]["failed"], 0)

    def test_missing_crs_rejected(self):
        c = frame([row("C", "1", box(0, 0, 10, 10))], crs=None)
        h = frame([row("H", "1", box(0, 0, 10, 10))])
        with self.assertRaisesRegex(ValueError, "CRS missing"):
            map_fields(c, h)


if __name__ == "__main__":
    unittest.main()
