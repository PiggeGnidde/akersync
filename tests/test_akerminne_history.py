from __future__ import annotations

import unittest

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from akerminne_history_core import (
    CropRecord,
    CropRegistry,
    build_reference_year,
    component_share_distribution,
    components_from_edges,
    summarize_history_year,
)


def historical() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({
        "blockid": ["H1", "H2"],
        "skiftesbeteckning": ["A", "B"],
        "grdkod_mar": [4, 47],
        "grdkod_und": [None, None],
        "geometry": [box(0, 0, 5, 10), box(5, 0, 10, 10)],
    }, crs="EPSG:3006")


def overlap_edges() -> pd.DataFrame:
    common = {
        "current_idx": 0,
        "current_field_key": "C|1",
        "current_blockid": "C",
        "current_skiftesbeteckning": "1",
        "current_area_m2": 100.0,
        "centroid_distance_m": 2.0,
        "same_admin_key": False,
        "is_historical_primary": True,
        "current_primary_tie": False,
        "historical_primary_tie": False,
        "qualifies_strict": False,
        "qualifies_relaxed": True,
    }
    return pd.DataFrame([
        {
            **common,
            "historical_idx": 0,
            "historical_field_key": "H1|A",
            "historical_blockid": "H1",
            "historical_skiftesbeteckning": "A",
            "intersection_m2": 50.0,
            "historical_area_m2": 50.0,
            "f_current": 0.5,
            "f_historical": 1.0,
            "strict_score": 0.5,
            "relaxed_score": 1.0,
            "is_current_primary": True,
            "is_mutual_primary": True,
        },
        {
            **common,
            "historical_idx": 1,
            "historical_field_key": "H2|B",
            "historical_blockid": "H2",
            "historical_skiftesbeteckning": "B",
            "intersection_m2": 50.0,
            "historical_area_m2": 50.0,
            "f_current": 0.5,
            "f_historical": 1.0,
            "strict_score": 0.5,
            "relaxed_score": 1.0,
            "is_current_primary": False,
            "is_mutual_primary": False,
        },
    ])


def match(status: str = "merge") -> pd.DataFrame:
    return pd.DataFrame([{
        "current_field_id": "C|1",
        "current_block_id": "C",
        "current_skiftesbeteckning": "1",
        "current_area_m2": 100.0,
        "match_confidence": status,
        "match_reason": "TEST",
        "primary_historical_field_id": "H1|A",
        "primary_f_current": 0.5,
        "primary_f_historical": 1.0,
    }])


class HistoryAggregationTests(unittest.TestCase):
    def test_mixed_crop_components_preserved(self):
        registry = CropRegistry({2019: {
            ("4", None): CropRecord("Höstvete", "WINTER_CEREAL"),
            ("47", None): CropRecord("Sockerbetor", "SUGAR_BEET"),
        }})
        components = components_from_edges(overlap_edges(), historical(), 2019, "Skurup", registry=registry)
        self.assertEqual(len(components), 2)
        self.assertEqual(set(components.crop_name), {"Höstvete", "Sockerbetor"})
        summary = summarize_history_year(match(), components, 2019, "Skurup").iloc[0]
        self.assertEqual(summary.crop_count_raw, 2)
        self.assertAlmostEqual(summary.coverage_raw, 1.0)
        self.assertAlmostEqual(summary.dominant_crop_share, 0.5)

    def test_unknown_code_never_falls_back_to_other_year(self):
        registry = CropRegistry({2020: {("4", None): CropRecord("Höstvete")}})
        components = components_from_edges(overlap_edges().iloc[:1], historical(), 2019, "Skurup", registry=registry)
        self.assertFalse(components.iloc[0].crop_known)
        self.assertEqual(components.iloc[0].crop_name, "Okänd grödkod 4 (2019)")

    def test_code_only_lookup_accepts_missing_subcategory(self):
        registry = CropRegistry({2019: {("4", None): CropRecord("Höstvete")}})
        self.assertEqual(registry.lookup(2019, 4, None).crop_name, "Höstvete")

    def test_overlap_anomaly_is_preserved_and_flagged(self):
        edges = overlap_edges().copy()
        edges.loc[0, "intersection_m2"] = 70.0
        edges.loc[0, "f_current"] = 0.7
        components = components_from_edges(edges, historical(), 2019, "Skurup")
        summary = summarize_history_year(match("ambiguous"), components, 2019, "Skurup").iloc[0]
        self.assertGreater(summary.coverage_raw, 1.0)
        self.assertEqual(summary.status, "OVERLAP_ANOMALY")
        self.assertIn("DUPLICATE_OVERLAP", summary.reason_flags)

    def test_no_public_match_is_explicit(self):
        components = components_from_edges(pd.DataFrame(), historical(), 2019, "Skurup")
        summary = summarize_history_year(match("unmatched"), components, 2019, "Skurup").iloc[0]
        self.assertEqual(summary.status, "NO_PUBLIC_MATCH")
        self.assertEqual(summary.coverage_raw, 0.0)

    def test_reference_year_is_exact_self_match(self):
        current = gpd.GeoDataFrame({
            "blockid": ["C"], "skiftesbeteckning": ["1"], "grdkod_mar": [4],
            "grdkod_und": [None], "geometry": [box(0, 0, 10, 10)],
        }, crs="EPSG:3006")
        registry = CropRegistry({2025: {("4", None): CropRecord("Höstvete")}})
        summary, components, _ = build_reference_year(current, "Skurup", registry)
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary.iloc[0].coverage_raw, 1.0)
        self.assertEqual(components.iloc[0].historical_field_id, "C|1")

    def test_small_component_distribution_does_not_apply_threshold(self):
        components = pd.DataFrame({"share_current": [0.0005, 0.004, 0.03, 0.9]})
        distribution = component_share_distribution(components)
        self.assertEqual(distribution["below_0_1pct"], 1)
        self.assertEqual(distribution["below_5pct"], 3)
        self.assertEqual(distribution["rows"], 4)


if __name__ == "__main__":
    unittest.main()
