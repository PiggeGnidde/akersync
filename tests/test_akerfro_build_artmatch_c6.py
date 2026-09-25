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

from analysis.akerfro_ertor_v0a.build_artmatch_c6 import (
    WEIGHTS,
    percentile_score,
)


class TestAkerFroArtMatchC6(unittest.TestCase):
    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(WEIGHTS.values()), 1.0)

    def test_percentile_direction(self):
        s = pd.Series([1.0, 2.0, 3.0])
        high = percentile_score(s, s, higher_is_better=True)
        low = percentile_score(s, s, higher_is_better=False)
        self.assertGreater(high.iloc[2], high.iloc[0])
        self.assertGreater(low.iloc[0], low.iloc[2])

    def test_percentile_bounds_and_ties(self):
        s = pd.Series([1.0, 1.0, 2.0, np.nan])
        score = percentile_score(s, s, higher_is_better=True)
        self.assertAlmostEqual(score.iloc[0], score.iloc[1])
        self.assertGreaterEqual(float(score.dropna().min()), 0.0)
        self.assertLessEqual(float(score.dropna().max()), 100.0)
        self.assertTrue(np.isnan(score.iloc[3]))


if __name__ == "__main__":
    unittest.main()
