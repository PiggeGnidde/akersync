#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.akerfro_ertor_v0a.area_logistics_robustness_c9b import (
    corrected_odds_ratio,
    quadratic_optimum,
    sweet_zone_summary,
)


class TestAkerFroAreaLogisticsRobustnessC9b(unittest.TestCase):
    def test_corrected_odds_ratio_positive(self):
        self.assertGreater(corrected_odds_ratio(10, 100, 5, 100), 1.0)

    def test_quadratic_optimum_concave(self):
        got = quadratic_optimum(
            b1=0.0, b2=-1.0,
            mean_raw=np.log1p(8.0), sd_raw=1.0,
            inverse="log1p",
        )
        self.assertAlmostEqual(got, 8.0, places=8)

    def test_quadratic_optimum_convex_is_nan(self):
        got = quadratic_optimum(
            b1=1.0, b2=0.2,
            mean_raw=0.0, sd_raw=1.0,
            inverse="identity",
        )
        self.assertTrue(np.isnan(got))

    def test_sweet_zone_definition(self):
        f = pd.DataFrame({
            "municipality": ["X", "X", "X", "X"],
            "field_area_ha": [6.0, 11.9, 12.0, 8.0],
            "distance_bjuv_km": [10.0, 59.9, 10.0, 60.0],
            "is_positive": [True, False, False, False],
        })
        cfg = {
            "sweet_zone_posthoc": {
                "area_min_ha": 5.0,
                "area_max_ha": 12.0,
                "distance_max_km": 60.0,
            },
            "municipality_min_candidate_fields": 1,
            "municipality_min_sweet_zone_fields": 1,
        }
        out = sweet_zone_summary(f, cfg)
        allrow = out[out["municipality"].eq("__ALL__")].iloc[0]
        self.assertEqual(int(allrow["n_sweet_zone_fields"]), 2)
        self.assertEqual(int(allrow["sweet_zone_positive"]), 1)


if __name__ == "__main__":
    unittest.main()
