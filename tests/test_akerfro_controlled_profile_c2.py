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

from analysis.akerfro_ertor_v0a.controlled_profile_c2 import (
    pooled_smd,
    stage_stats,
)


class TestAkerFroControlledProfileC2(unittest.TestCase):
    def test_pooled_smd_direction(self):
        p = pd.Series([10.0, 11.0]).to_numpy()
        u = pd.Series([1.0, 2.0]).to_numpy()
        self.assertGreater(pooled_smd(p, u), 0)

    def test_stratum_centering_removes_pure_geography_signal(self):
        # Within each stratum positives and unlabeled have identical x values,
        # but positive prevalence is much higher in the high-x stratum.
        frame = pd.DataFrame({
            "is_positive": [
                True, True, True, False,   # high stratum
                True, False, False, False  # low stratum
            ],
            "x__f": [10, 10, 10, 10, 1, 1, 1, 1],
        })
        strata = pd.Series(["H"] * 4 + ["L"] * 4)
        raw = stage_stats(frame, "x__f", None)
        adj = stage_stats(frame, "x__f", strata)
        self.assertGreater(raw["smd"], 0)
        self.assertTrue(adj["smd"] is None or abs(adj["smd"]) < 1e-12)

    def test_common_support_excludes_one_class_stratum(self):
        frame = pd.DataFrame({
            "is_positive": [True, False, True, True],
            "x__f": [2.0, 1.0, 100.0, 101.0],
        })
        strata = pd.Series(["A", "A", "B", "B"])
        adj = stage_stats(frame, "x__f", strata)
        self.assertEqual(adj["n_strata"], 1)
        self.assertEqual(adj["n_positive"], 1)
        self.assertEqual(adj["n_unlabeled"], 1)


if __name__ == "__main__":
    unittest.main()
