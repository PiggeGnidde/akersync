from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from akerdrift_fast_core import (  # noqa: E402
    config_hash,
    geometry_metrics,
    load_model_config,
    score_field,
    slope_metrics,
)


CONFIG_PATH = ROOT / "config" / "akerdrift_fast_v1_rc0.json"


class AkerdriftFastCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_model_config(CONFIG_PATH)

    def score(self, slopes, slope_coverage=1.0, twi=None, twi_coverage=0.0):
        return score_field(
            area_m2=100_000.0,
            perimeter_m=1_400.0,
            slope_values_deg=slopes,
            slope_coverage=slope_coverage,
            twi_values=twi,
            twi_coverage=twi_coverage,
            config=self.config,
        )

    def test_units_are_m2_and_metres(self):
        result = geometry_metrics(100_000.0, 1_400.0, self.config)
        expected = 0.179 - 0.145 * math.log(1_400.0 / 100_000.0)
        self.assertAlmostEqual(result["pa_ratio"], 0.014)
        self.assertAlmostEqual(result["fe_geom_raw"], expected)
        wrong_hectare_input = geometry_metrics(10.0, 1_400.0, self.config)
        self.assertNotAlmostEqual(result["geometry_score"], wrong_hectare_input["geometry_score"])

    def test_similar_square_scaling(self):
        scores = []
        for hectares in (1.0, 10.0, 100.0):
            area = hectares * 10_000.0
            scores.append(geometry_metrics(area, 4.0 * math.sqrt(area), self.config)["geometry_score"])
        self.assertLess(scores[0], scores[1])
        self.assertLess(scores[1], scores[2])

    def test_same_area_higher_perimeter_scores_lower(self):
        compact = geometry_metrics(100_000.0, 1_300.0, self.config)["geometry_score"]
        complex_boundary = geometry_metrics(100_000.0, 2_600.0, self.config)["geometry_score"]
        self.assertGreater(compact, complex_boundary)

    def test_flat_terrain_does_not_change_geometry_score(self):
        result = self.score([0.0, 2.0, 5.0])
        self.assertEqual(result["drift_slope_difficulty"], 0.0)
        self.assertEqual(result["drift_terrain_factor"], 1.0)
        self.assertAlmostEqual(result["akerdrift_score"], result["geometry_score"])

    def test_slope_penalty_is_monotonic(self):
        flat = self.score([2.0] * 20)["akerdrift_score"]
        moderate = self.score([10.0] * 20)["akerdrift_score"]
        steep = self.score([20.0] * 20)["akerdrift_score"]
        self.assertGreaterEqual(flat, moderate)
        self.assertGreaterEqual(moderate, steep)

    def test_bounds_and_nan_handling(self):
        result = self.score([np.nan, -2.0, 100.0])
        self.assertGreaterEqual(result["akerdrift_score"], 0.0)
        self.assertLessEqual(result["akerdrift_score"], 100.0)
        self.assertGreaterEqual(result["drift_terrain_factor"], 0.8)
        self.assertLessEqual(result["drift_terrain_factor"], 1.0)

    def test_missing_twi_never_changes_score(self):
        missing = self.score([8.0] * 20)
        present = self.score([8.0] * 20, twi=[5.0, 20.0], twi_coverage=1.0)
        self.assertEqual(missing["akerdrift_score"], present["akerdrift_score"])
        self.assertEqual(missing["drift_twi_status"], "MISSING")
        self.assertEqual(present["drift_twi_status"], "OK")

    def test_coverage_statuses(self):
        self.assertEqual(self.score([3.0], 0.95)["drift_status"], "OK")
        self.assertEqual(self.score([3.0], 0.90)["drift_status"], "LIMITED_SLOPE_COVERAGE")
        insufficient = self.score([3.0], 0.79)
        self.assertEqual(insufficient["drift_status"], "INSUFFICIENT_SLOPE_COVERAGE")
        self.assertIsNone(insufficient["akerdrift_score"])
        self.assertIsNotNone(insufficient["geometry_score"])

    def test_config_hash_is_order_independent(self):
        reordered = json.loads(json.dumps(self.config, sort_keys=True))
        self.assertEqual(config_hash(self.config), config_hash(reordered))

    def test_slope_breakpoints(self):
        metrics = slope_metrics([5.0, 16.7], self.config)
        self.assertAlmostEqual(metrics["drift_slope_difficulty"], 0.5)


if __name__ == "__main__":
    unittest.main()
