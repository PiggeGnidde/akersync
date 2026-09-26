#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.akerfro_ertor_v0a.operational_c10 import (
    operational_band,
    piecewise_score,
)


class TestAkerFroOperationalC10(unittest.TestCase):
    def test_area_plateau_and_soft_tails(self):
        v = pd.Series([0.0, 2.0, 5.0, 8.0, 12.0, 20.0, 40.0, 120.0])
        got = piecewise_score(
            v,
            [0, 2, 5, 12, 20, 40, 100],
            [25, 40, 100, 100, 75, 55, 40],
            40,
        ).tolist()
        self.assertEqual(got, [25.0, 40.0, 100.0, 100.0, 100.0, 75.0, 55.0, 40.0])

    def test_proximity_is_monotone_nonincreasing(self):
        v = pd.Series([0, 20, 40, 60, 80, 100, 140, 200])
        got = piecewise_score(
            v,
            [0, 20, 40, 60, 80, 100, 140],
            [100, 100, 85, 70, 50, 35, 15],
            15,
        )
        self.assertTrue((got.diff().dropna() <= 1e-12).all())

    def test_operational_band(self):
        cfg = {"operational_bands": {"HIGH": 80, "MEDIUM": 60, "LOW": 0}}
        got = operational_band(pd.Series([90.0, 70.0, 59.9, None]), cfg).tolist()
        self.assertEqual(got, ["HIGH", "MEDIUM", "LOW", "UNKNOWN"])


if __name__ == "__main__":
    unittest.main()
