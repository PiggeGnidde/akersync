from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from importlib import import_module  # noqa: E402

visual = import_module("56_build_akerminne_visual_qa")


class VisualQaTests(unittest.TestCase):
    def _current(self):
        return gpd.GeoDataFrame(
            [{"blockid": "B", "skiftesbeteckning": "A", "geometry": box(0, 0, 100, 100)}],
            crs="EPSG:3006",
        )

    def test_packages_historical_polygon_and_exact_intersection(self):
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td)
            hp = visual._historical_path(raw, 2020)
            hp.parent.mkdir(parents=True)
            hist = gpd.GeoDataFrame(
                [{"blockid": "H", "skiftesbeteckning": "1", "grdkod_mar": "4", "grdkod_und": None,
                  "geometry": box(50, 0, 150, 100)}],
                crs="EPSG:3006",
            )
            hist.to_file(hp, driver="GPKG")
            checklist = pd.DataFrame([{
                "qa_category": "status_edge", "history_year": 2020, "current_field_id": "B|A",
                "status": "PARTIAL_COVERAGE", "coverage_display": .5, "second_crop_share": 0.0,
                "identity_match_confidence": "one_to_one_relaxed", "overlap_excess_raw": 0.0,
            }])
            components = pd.DataFrame([{
                "history_year": 2020, "current_field_id": "B|A", "historical_field_id": "H|1",
                "crop_code_raw": "4", "crop_subcategory_raw": None, "intersection_m2": 5000.0,
                "share_current": .5, "share_historical": .5,
            }])
            cases = visual.build_cases(checklist, components, self._current(), raw)
            self.assertEqual(len(cases), 1)
            self.assertEqual(len(cases[0]["historical"]["features"]), 1)
            self.assertEqual(len(cases[0]["intersections"]["features"]), 1)
            self.assertEqual(cases[0]["historical"]["features"][0]["properties"]["historical_field_id"], "H|1")

    def test_no_match_has_only_current_geometry(self):
        checklist = pd.DataFrame([{
            "qa_category": "status_edge", "history_year": 2020, "current_field_id": "B|A",
            "status": "NO_PUBLIC_MATCH", "coverage_display": 0.0, "second_crop_share": 0.0,
            "identity_match_confidence": "unmatched", "overlap_excess_raw": 0.0,
        }])
        components = pd.DataFrame(columns=["history_year", "current_field_id"])
        cases = visual.build_cases(checklist, components, self._current(), Path("unused"))
        self.assertEqual(len(cases[0]["current"]["features"]), 1)
        self.assertEqual(cases[0]["historical"]["features"], [])
        self.assertEqual(cases[0]["intersections"]["features"], [])


if __name__ == "__main__":
    unittest.main()
