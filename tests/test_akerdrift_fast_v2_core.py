from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from akerdrift_fast_v2_core import (  # noqa: E402
    geometry_score,
    load_model_config,
    score_from_metrics,
    validate_model_config,
)


def test_config() -> dict:
    continuous = ["fast_geometry_score", "log_area_ha"]
    binary = ["has_holes"]
    # Two continuous features, one knot each => four basis columns + binary.
    return {
        "model_version": "akerdrift-fast-v2-routecal-rc0",
        "geometry_model": {
            "continuous_features": continuous,
            "binary_features": binary,
            "knots": {"fast_geometry_score": [50.0], "log_area_ha": [0.0]},
            "clip_ranges": {"fast_geometry_score": [0.0, 100.0], "log_area_ha": [-5.0, 5.0]},
            "basis_mean": [0.0] * 5,
            "basis_scale": [1.0] * 5,
            "coefficients": [1.0, 0.0, 0.0, 0.0, -2.0],
            "intercept": 0.0,
        },
    }


class AkerdriftFastV2CoreTests(unittest.TestCase):
    def test_frozen_repository_config_loads(self):
        config = load_model_config(ROOT / "config" / "akerdrift_fast_v2_routecal_rc0.json")
        self.assertEqual(config["calibration"]["n_comparable"], 525)

    def test_validates_and_bounds(self):
        config = test_config()
        validate_model_config(config)
        result = geometry_score({"fast_geometry_score": 200, "log_area_ha": 0, "has_holes": 0}, config)
        self.assertEqual(result, 100.0)

    def test_hole_feature_penalizes(self):
        config = test_config()
        clean = geometry_score({"fast_geometry_score": 80, "log_area_ha": 0, "has_holes": 0}, config)
        hole = geometry_score({"fast_geometry_score": 80, "log_area_ha": 0, "has_holes": 1}, config)
        self.assertEqual(clean - hole, 2.0)

    def test_terrain_is_applied_after_geometry(self):
        # Use a full seven-feature config for score_from_metrics.
        config = test_config()
        model = config["geometry_model"]
        model["continuous_features"] = [
            "fast_geometry_score", "log_area_ha", "rectangularity", "compactness", "log_erl_m",
        ]
        model["binary_features"] = ["has_holes", "holes_capped_5"]
        model["knots"] = {name: [0.0] for name in model["continuous_features"]}
        model["clip_ranges"] = {name: [-100.0, 100.0] for name in model["continuous_features"]}
        size = 5 * 2 + 2
        model["basis_mean"] = [0.0] * size
        model["basis_scale"] = [1.0] * size
        model["coefficients"] = [0.0] * size
        model["coefficients"][0] = 1.0
        result = score_from_metrics(
            fast_geometry_score=80, terrain_factor=0.9, area_ha=2,
            rectangularity=0.8, compactness=0.5, erl_m=100,
            hole_count=0, config=config,
        )
        self.assertAlmostEqual(result["geometry_score"], 80.0)
        self.assertAlmostEqual(result["akerdrift_score"], 72.0)


if __name__ == "__main__":
    unittest.main()
