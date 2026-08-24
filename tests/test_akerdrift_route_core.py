from __future__ import annotations

import math
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from akerdrift_route_core import RouteConfig, is_small_or_narrow_field, simulate_route  # noqa: E402

import pandas as pd  # noqa: E402


RUNNER_SPEC = importlib.util.spec_from_file_location(
    "akerdrift_route_pilot_runner", ROOT / "src" / "45_akerdrift_route_pilot.py"
)
RUNNER = importlib.util.module_from_spec(RUNNER_SPEC)
assert RUNNER_SPEC.loader is not None
RUNNER_SPEC.loader.exec_module(RUNNER)

try:
    from shapely import affinity
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False


@unittest.skipUnless(HAS_SHAPELY, "shapely saknas")
class AkerdriftRouteCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = RouteConfig()

    def score(self, geometry):
        return simulate_route(geometry, self.config)

    def test_large_rectangle_is_high_and_bounded(self):
        result = self.score(box(0, 0, 1200, 1000))
        self.assertGreater(result["geometry_score"], 90)
        self.assertLessEqual(result["geometry_score"], 100)
        self.assertGreater(result["turn_count"], 0)
        self.assertAlmostEqual(
            result["interior_distance_m"] + result["headland_distance_m"],
            result["productive_distance_m"], places=6,
        )
        self.assertEqual(result["route_geometry_status"], "OK")

    def test_empty_headland_core_is_explicitly_small_or_narrow(self):
        result = self.score(box(0, 0, 30, 30))
        self.assertTrue(result["small_or_narrow_field"])
        self.assertEqual(result["route_geometry_status"], "SMALL_OR_NARROW_FIELD")

    def test_nonempty_but_sub_work_width_core_is_small_or_narrow(self):
        shape = box(0, 0, 392, 54)
        self.assertFalse(shape.buffer(-self.config.headland_width_m).is_empty)
        self.assertTrue(is_small_or_narrow_field(shape, self.config))
        result = self.score(shape)
        self.assertEqual(result["interior_distance_m"], 0.0)
        self.assertEqual(result["route_geometry_status"], "SMALL_OR_NARROW_FIELD")

    def test_full_width_interior_pass_remains_normal(self):
        shape = box(0, 0, 392, 70)
        self.assertFalse(is_small_or_narrow_field(shape, self.config))
        result = self.score(shape)
        self.assertGreater(result["interior_distance_m"], 0.0)
        self.assertEqual(result["route_geometry_status"], "OK")

    def test_same_area_long_rectangle_beats_square(self):
        square = self.score(box(0, 0, math.sqrt(100_000), math.sqrt(100_000)))
        long_rectangle = self.score(box(0, 0, 1000, 100))
        self.assertGreater(long_rectangle["geometry_score"], square["geometry_score"])
        self.assertLess(long_rectangle["turn_count"], square["turn_count"])

    def test_l_shape_scores_below_clean_rectangle(self):
        clean = box(0, 0, 300, 100)
        l_shape = unary_union([box(0, 0, 200, 100), box(0, 100, 100, 200)])
        self.assertAlmostEqual(clean.area, l_shape.area)
        self.assertGreater(self.score(clean)["geometry_score"], self.score(l_shape)["geometry_score"])

    def test_central_hole_adds_segments_and_penalty(self):
        clean = box(0, 0, 300, 300)
        with_hole = Polygon(clean.exterior.coords, [box(130, 130, 170, 170).exterior.coords])
        clean_result = self.score(clean)
        hole_result = self.score(with_hole)
        self.assertGreater(hole_result["segment_count"], clean_result["segment_count"])
        self.assertGreater(hole_result["nonproductive_distance_m"], clean_result["nonproductive_distance_m"])
        self.assertLess(hole_result["geometry_score"], clean_result["geometry_score"])

    def test_rotation_is_nearly_invariant(self):
        shape = unary_union([box(0, 0, 420, 180), box(0, 180, 160, 290)])
        baseline = self.score(shape)["geometry_score"]
        rotated = self.score(affinity.rotate(shape, 37, origin="centroid"))["geometry_score"]
        self.assertAlmostEqual(baseline, rotated, delta=1.0)

    def test_repeat_is_deterministic(self):
        shape = box(0, 0, 777, 222)
        first = self.score(shape)
        second = self.score(shape)
        self.assertEqual(first, second)


class AkerdriftRouteSelectionTests(unittest.TestCase):
    @staticmethod
    def candidates():
        rows = []
        for index in range(400):
            key = f"block-{index}|A"
            rows.append({
                "field_key": key,
                "akerdrift_score": float(index),
                "area_ha_route": 0.1 + index / 3.0,
                "hole_count": 2 if 80 <= index < 160 else 0,
                "pa_ratio_route": 1.0 / (index + 1),
                "small_or_narrow_field": index < 80,
                "stable_hash": RUNNER.stable_hash(key),
            })
        return pd.DataFrame(rows)

    def test_sample_is_bounded_diverse_and_deterministic(self):
        first = RUNNER.select_pilot(self.candidates(), 200)
        second = RUNNER.select_pilot(self.candidates(), 200)
        self.assertEqual(list(first["field_key"]), list(second["field_key"]))
        self.assertEqual(len(first), 200)
        self.assertEqual(int(first["validation_cohort"].eq("normal").sum()), 150)
        self.assertEqual(int(first["validation_cohort"].eq("stress").sum()), 50)
        self.assertFalse(first.loc[first["validation_cohort"].eq("normal"), "small_or_narrow_field"].any())
        self.assertGreaterEqual(
            int(first.loc[first["validation_cohort"].eq("stress"), "small_or_narrow_field"].sum()), 25
        )
        self.assertEqual(list(first["selection_order"]), list(range(1, 201)))

    def test_sample_limit_is_hard(self):
        with self.assertRaises(ValueError):
            RUNNER.select_pilot(self.candidates(), 201)

    def test_main_report_excludes_stress_and_small_or_narrow(self):
        frame = pd.DataFrame([
            {"field_key": "1|A", "validation_cohort": "normal", "route_status": "OK", "fast_score": 50.0,
             "route_score": 52.0, "route_score_diagnostic": 52.0, "hole_count": 0, "turn_count": 5,
             "area_ha": 2.0, "score_difference_route_minus_fast": 2.0},
            {"field_key": "2|A", "validation_cohort": "normal", "route_status": "OK", "fast_score": 60.0,
             "route_score": 61.0, "route_score_diagnostic": 61.0, "hole_count": 1, "turn_count": 8,
             "area_ha": 2.0, "score_difference_route_minus_fast": 1.0},
            {"field_key": "3|A", "validation_cohort": "normal", "route_status": "OK", "fast_score": 70.0,
             "route_score": 69.0, "route_score_diagnostic": 69.0, "hole_count": 0, "turn_count": 6,
             "area_ha": 3.0, "score_difference_route_minus_fast": -1.0},
            {"field_key": "4|A", "validation_cohort": "stress", "route_status": "SMALL_OR_NARROW_FIELD",
             "fast_score": 10.0, "route_score": None, "route_score_diagnostic": 100.0, "hole_count": 0,
             "turn_count": 0, "area_ha": 0.01, "score_difference_route_minus_fast": None},
            {"field_key": "5|A", "validation_cohort": "stress", "route_status": "OK", "fast_score": 40.0,
             "route_score": 5.0, "route_score_diagnostic": 5.0, "hole_count": 2, "turn_count": 100,
             "area_ha": 2.0, "score_difference_route_minus_fast": -35.0},
        ])
        with tempfile.TemporaryDirectory() as directory:
            summary = RUNNER.build_report(frame, Path(directory))
            stored = json.loads((Path(directory) / "qa" / "comparison_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["n_main_compared"], 3)
        self.assertEqual(summary["n_stress_selected"], 2)
        self.assertEqual(summary["n_stress_scored"], 1)
        self.assertEqual(summary["n_small_or_narrow"], 1)
        self.assertEqual(stored["n_main_compared"], 3)


if __name__ == "__main__":
    unittest.main()
