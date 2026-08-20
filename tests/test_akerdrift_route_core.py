from __future__ import annotations

import math
import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from akerdrift_route_core import RouteConfig, simulate_route  # noqa: E402

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
        for index in range(100):
            key = f"block-{index}|A"
            rows.append({
                "field_key": key,
                "akerdrift_score": float(index),
                "area_ha_route": 0.1 + index / 3.0,
                "hole_count": 2 if index < 20 else 0,
                "stable_hash": RUNNER.stable_hash(key),
            })
        return pd.DataFrame(rows)

    def test_sample_is_bounded_diverse_and_deterministic(self):
        first = RUNNER.select_pilot(self.candidates(), 50)
        second = RUNNER.select_pilot(self.candidates(), 50)
        self.assertEqual(list(first["field_key"]), list(second["field_key"]))
        self.assertEqual(len(first), 50)
        self.assertGreaterEqual(int((first["hole_count"] > 0).sum()), 10)
        self.assertEqual(list(first["selection_order"]), list(range(1, 51)))

    def test_sample_limit_is_hard(self):
        with self.assertRaises(ValueError):
            RUNNER.select_pilot(self.candidates(), 201)


if __name__ == "__main__":
    unittest.main()
